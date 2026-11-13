"""Worker loop: heartbeats, job claiming, resumable training, verified uploads, reconnects."""

from __future__ import annotations

import io
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
import torch

from moth_worker import __version__
from moth_worker.client import ServerError, WorkerClient
from moth_worker.hardware import measured_device, compute_kind, detect

CHECKPOINT_EVERY = 25
SNAPSHOT_SECONDS = 600.0  # 0.9.0: how often an evolution job sends its progress to MOTH Cloud


class Stop(Exception):
    pass


def utilization(hw: dict[str, Any]) -> dict[str, float | None]:
    """Current load as the OS reports it (shown in AI → Evolution); unknown values stay None."""
    import os

    cpu = None
    try:
        cpu = round(min(1.0, os.getloadavg()[0] / max(1, int(hw.get("cpu_count") or os.cpu_count() or 1))), 3)
    except (AttributeError, OSError):  # Windows has no load average
        pass
    mem = None
    if hw.get("ram_gb") and hw.get("ram_available_gb") is not None:
        mem = round(max(0.0, 1 - float(hw["ram_available_gb"]) / float(hw["ram_gb"])), 3)
    return {"cpu": cpu, "memory": mem}


class WorkerRunner:
    def __init__(self, client: WorkerClient, state_dir: Path, allow_cpu: bool = False,
                 log: Callable[[str], None] = print, heartbeat_seconds: float = 30.0,
                 update_check_seconds: float | None = 900.0):
        self.client = client
        self.state_dir = Path(state_dir)
        (self.state_dir / "jobs").mkdir(parents=True, exist_ok=True)
        self.allow_cpu = allow_cpu
        self.log = log
        self.heartbeat_seconds = heartbeat_seconds
        self.current_job: int | None = None
        self.progress: float | None = None
        self.training_metrics: dict | None = None
        self.paused = False
        self.cancelled_job: int | None = None
        self.revoked = False
        self.limits: dict[str, Any] = {}
        self.stop_event = threading.Event()
        self.update_check_seconds = update_check_seconds
        self._next_update_check = 0.0
        self._update_retry_after = 0.0  # after a failed install: wait before trying again (backoff)
        self._update_failures = 0
        self.updated_to: str | None = None
        self.device: str | None = None
        self.bench: dict[str, Any] | None = None
        self.hardware_lock = threading.Lock()
        self.reset_generation = None
        self.reset_retained = 0
        self.reset_lock = threading.Lock()

    def hardware(self) -> dict[str, Any]:
        """Detected hardware plus the measured benchmark (taken once, cached for a week)."""
        hw = detect()
        with self.hardware_lock:
            if self.device is None:
                self.device, self.bench = measured_device(self.state_dir, hw)
        # Advertise the selected supported backend, not merely an installed graphics card.
        return {**hw, "compute": "gpu" if self.device == "cuda" else "cpu", "benchmark": self.bench,
                "utilization": utilization(hw)}

    # ---- heartbeat -----------------------------------------------------------------------
    def beat(self) -> None:
        kwargs={} if self.reset_generation is None else {'reset_ack':self.reset_generation,'reset_retained':self.reset_retained}
        resp = self.client.heartbeat(self.hardware(), self.current_job, self.progress, self.training_metrics,**kwargs)
        generation=resp.get('reset_generation',0)
        if generation and generation!=self.reset_generation:
            if self.current_job is not None:
                self.cancelled_job=self.current_job
            else:
                self.clean_reset_cache(generation)
        from moth.training.resources import pressure, pressure_reason
        self.paused, self.revoked, self.limits = bool(resp["paused"] or pressure_reason(pressure())), resp["revoked"], resp.get("limits") or {}
        if resp.get("job_cancelled"):
            self.cancelled_job = self.current_job
        offered = resp.get("update")
        if offered and offered != __version__ and self.update_check_seconds is not None \
                and time.time() >= self._update_retry_after:
            self._next_update_check = 0.0  # MOTH Cloud announced a newer worker: install it between jobs
        from moth_worker import updater

        done = updater.confirm_healthy(self.state_dir)
        if done:
            self.log(f"MOTH Worker {__version__} is connected (updated from {done.get('from')})")
            try:
                self.client.report_update(done.get("from"), __version__, True)
            except Exception:  # noqa: BLE001 — reporting is best effort
                pass

    def cache_scope(self):
        import hashlib
        return hashlib.sha256((str(getattr(self.client,'server',''))+'\0'+str(getattr(self.client,'token',''))).encode()).hexdigest()

    def clean_reset_cache(self,generation):
        """Only delete checkpoint filenames with a matching local deployment ownership marker.

        Legacy/unbound caches are retained and reported for manual review, never guessed owned.
        Caller waits until current_job is None; heartbeats only request cancellation during training.
        """
        with self.reset_lock:
            if self.current_job is not None:return
            root=self.state_dir/'jobs'
            if root.is_symlink():raise RuntimeError('Worker job cache is a symbolic link; reset cleanup requires review')
            scope=self.cache_scope()
            for marker in root.glob('*.owner.json'):
                if marker.is_symlink():continue
                try:owner=json.loads(marker.read_text())
                except (OSError,ValueError):continue
                jid=marker.name.split('.')[0]
                if not jid.isdigit() or owner.get('scope')!=scope:continue
                for suffix in ('.pt','.pt.sha256','.pt.corrupt','.pt.tmp','.pt.sha256.tmp'):
                    file=root/(jid+suffix)
                    if file.is_symlink():continue
                    file.unlink(missing_ok=True)
                marker.unlink()
            self.reset_retained=sum(1 for p in root.glob('*.pt*'))
            self.reset_generation=generation
            self.log(f'Native reset {generation}: owned cached checkpoints removed; {self.reset_retained} unverified/other-scope cache files retained.')

    def maybe_update(self) -> bool:
        """Between jobs only: install a newer verified worker if MOTH Cloud offers one."""
        if self.update_check_seconds is None or time.time() < self._next_update_check:
            return False
        self._next_update_check = time.time() + self.update_check_seconds
        from moth_worker import updater

        try:
            info = self.client.check_update()
        except Exception as e:  # noqa: BLE001
            self.log(f"update check failed: {e}")
            return False
        if not info:
            return False
        try:
            self.updated_to = updater.apply(info, self.state_dir, self.client.download_file, self.log)
            return True
        except Exception as e:  # noqa: BLE001 — a failed update never stops the worker
            # exponential backoff (5 min, 10, 20 … at most 6 h): a refused or broken update is not retried
            # in a loop, whatever the heartbeat announces
            self._update_failures += 1
            wait = min(6 * 3600.0, 300.0 * 2 ** (self._update_failures - 1))
            self._update_retry_after = self._next_update_check = time.time() + wait
            self.log(f"update to {info.get('version')} was not installed: {e} (next attempt in {wait / 60:.0f} min)")
            try:
                self.client.report_update(__version__, info.get("version", "?"), False, str(e))
            except Exception:  # noqa: BLE001
                pass
            return False

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(self.heartbeat_seconds):
            try:
                self.beat()
            except ServerError as e:
                if e.status == 401:
                    self.revoked = True
                    self.log("Worker credential was revoked by its owner; stopping.")
                    self.stop_event.set()
            except Exception as e:  # noqa: BLE001 — network trouble: keep trying
                self.log(f"heartbeat failed: {e}")

    # ---- main loop -------------------------------------------------------------------------
    def run(self, max_jobs: int | None = None, idle_sleep: float = 30.0) -> int:
        threading.Thread(target=self._heartbeat_loop, daemon=True, name="heartbeat").start()
        done, backoff = 0, 2.0
        while not self.stop_event.is_set():
            try:
                self.beat()
                if self.revoked:
                    break
                if self.maybe_update():
                    break  # the CLI restarts into the new version; no job is in progress here
                if self.paused:
                    self.stop_event.wait(idle_sleep)
                    continue
                job = self.client.claim()
                backoff = 2.0
                if not job:
                    self.stop_event.wait(idle_sleep)
                    continue
                self.run_job(job)
                done += 1
                if max_jobs and done >= max_jobs:
                    break
            except Stop:
                continue  # checkpoint saved; normal loop checks pause/exit
            except ServerError as e:
                if e.status == 401:
                    self.log("Worker credential is invalid or revoked; stopping.")
                    break
                self.log(f"server error: {e}; retrying in {backoff:.0f}s")
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, 300)
            except (OSError, RuntimeError, httpx.HTTPError) as e:  # network errors → reconnect with backoff
                self.log(f"connection problem: {e}; reconnecting in {backoff:.0f}s")
                self.stop_event.wait(backoff)
                backoff = min(backoff * 2, 300)
        self.stop_event.set()
        return done

    def run_eval(self, job: dict) -> dict:
        """Measure a candidate on held-out data (evaluation jobs go to CPU workers while GPUs train)."""
        import json as _json

        jid, spec = job["id"], job["spec"]
        self.cancelled_job = None
        self.training_metrics = None
        self.current_job, self.progress = jid, 0.0
        self.log(f"job {jid}: evaluating {spec['eval']['suite_id']} of model v{spec['eval']['version']}")
        try:
            weights = self.client.download(jid, "weights", spec["base_sha256"])
            data = self.client.download(jid, "shard", spec["shard_sha256"])
            torch.set_num_threads(max(1, int(self.limits.get("cpu_threads") or max(1, (os.cpu_count() or 2) - 1))))
            total, count = _eval_loss(weights, data, spec["model_config"],
                                      progress=lambda p: setattr(self, "progress", p))
            payload = _json.dumps({"total": total, "count": count}).encode()
            from moth.community.validation import tensor_bytes_sha256

            meta = {"round": -1, "base_sha256": spec["base_sha256"], "delta_sha256": tensor_bytes_sha256(payload),
                    "tokens": 0, "steps": 0, "protocol": spec.get("protocol", 1), "worker_version": __version__}
            result = self.client.result(jid, meta, payload)
            self.log(f"job {jid}: loss {total / max(1, count):.4f} over {count} tokens "
                     f"({'accepted' if result.get('accepted') else 'rejected'})")
            return result
        except ServerError:
            raise
        except Exception as e:  # noqa: BLE001
            if self.device == "cuda" and any(marker in str(e).lower() for marker in ("cuda", "out of memory", "cublas")):
                self.device, self.bench = "cpu", None
                self.log("GPU failed; subsequent eligible work uses CPU. Saved checkpoints are retained.")
            self.log(f"job {jid} failed: {e}")
            try:
                self.client.fail(jid, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass
            return {"accepted": False, "error": str(e)}
        finally:
            self.current_job, self.progress = None, None
            self.training_metrics = None

    def run_prep(self, job: dict) -> dict:
        """Tokenize one chunk of a dataset build (0.7.2). MOTH Cloud re-encodes records to check it."""
        import tempfile

        from moth.community.validation import tensor_bytes_sha256
        from moth.datafactory.build import chunk_bytes, encode_chunk
        from moth.model.tokenizer import Tokenizer

        jid, spec = job["id"], job["spec"]
        self.cancelled_job = None
        self.current_job, self.progress = jid, 0.0
        self.log(f"job {jid}: preparing data chunk {spec['shard_id']}")
        try:
            tok_bytes = self.client.download(jid, "weights", spec["base_sha256"])  # the lineage's tokenizer
            chunk = self.client.download(jid, "shard", spec["shard_sha256"])
            with tempfile.TemporaryDirectory() as d:
                (Path(d) / "tokenizer.json").write_bytes(tok_bytes)
                (Path(d) / "chunk.jsonl").write_bytes(chunk)
                tok = Tokenizer.load(Path(d) / "tokenizer.json")
                if tok.fingerprint() != spec["tokenizer_fingerprint"]:
                    raise RuntimeError("the tokenizer does not match the build")
                arrays = encode_chunk(tok, Path(d) / "chunk.jsonl")
            payload = chunk_bytes(arrays)
            self.progress = 1.0
            meta = {"round": -1, "base_sha256": spec["base_sha256"], "delta_sha256": tensor_bytes_sha256(payload),
                    "tokens": 0, "steps": 0, "records": int(len(arrays["offsets"]) - 1),
                    "protocol": spec.get("protocol", 1), "worker_version": __version__}
            result = self.client.result(jid, meta, payload)
            self.log(f"job {jid}: {len(arrays['ids']):,} tokens from {meta['records']} records "
                     f"({'accepted' if result.get('accepted') else 'rejected'})")
            return result
        except ServerError:
            raise
        except Exception as e:  # noqa: BLE001
            self.log(f"job {jid} failed: {e}")
            try:
                self.client.fail(jid, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass
            return {"accepted": False, "error": str(e)}
        finally:
            self.current_job, self.progress = None, None

    # ---- one training round ------------------------------------------------------------------
    def run_job(self, job: dict) -> dict:
        from moth.community.client import batch_loss
        from moth.community.validation import serialize_state, tensor_bytes_sha256
        from moth.model.config import MothConfig
        from moth.model.transformer import MothModel

        if job.get("kind") == "eval_loss":
            return self.run_eval(job)
        if job.get("kind") == "prep_tokenize":
            return self.run_prep(job)
        jid, spec = job["id"], job["spec"]
        self.cancelled_job = None
        self.training_metrics = None
        self.current_job, self.progress = jid, 0.0
        owner_path=self.state_dir/'jobs'/f'{jid}.owner.json'
        if not (self.state_dir/'jobs'/f'{jid}.pt').exists():
            owner_path.write_text(json.dumps({'scope':self.cache_scope()}))
        self.log(f"job {jid}: round {spec['round']}, shard {spec['shard_id']}")
        def phase(name: str) -> None:  # 0.9.0: MOTH Cloud shows what the worker is doing before its first step
            self.training_metrics = {"step": 0, "tokens": 0, **(self.training_metrics or {}), "phase": name}

        try:
            phase("downloading the model")
            weights = self.client.download(jid, "weights", spec["base_sha256"])
            phase("downloading the training data")
            shard = self.client.download(jid, "shard", spec["shard_sha256"])
            tokens = np.frombuffer(shard, dtype=np.uint32)
            # conversation data learns only the assistant's replies: apply the job's loss mask (0.6.3)
            loss_mask = (np.frombuffer(self.client.download(jid, "mask", spec["mask_sha256"]), dtype=np.uint8)
                         if spec.get("mask_sha256") else None)
            if loss_mask is not None and len(loss_mask) != len(tokens):
                raise RuntimeError("the job's loss mask does not match its shard")
            device = self.device or ("cuda" if compute_kind(detect()) == "gpu" else "cpu")
            limits = {**job.get("limits", {}), **self.limits}
            if device == "cpu":  # leave a core for the system unless the owner set a limit
                from moth.training.resources import cpu_count
                torch.set_num_threads(min(cpu_count(), max(1, int(limits.get("cpu_threads") or max(1, min(cpu_count() - 1, int((self.bench or {}).get("threads") or cpu_count())))))))
            if device == "cuda" and limits.get("gpu_memory_fraction"):
                torch.cuda.set_per_process_memory_fraction(float(limits["gpu_memory_fraction"]))
            phase("loading the model")
            base = torch.load(io.BytesIO(weights), map_location="cpu", weights_only=True)
            model = MothModel(MothConfig.from_dict(spec["model_config"])).to(device)
            model.load_state_dict(base)
            train = spec["train"]
            opt = model.configure_optimizer(train["lr"], train.get("weight_decay", 0.0), device_type=device)
            gen = torch.Generator().manual_seed(jid)
            ckpt_path = self.state_dir / "jobs" / f"{jid}.pt"
            if not ckpt_path.exists() and ckpt_path.with_name(ckpt_path.name + '.corrupt').exists():
                raise RuntimeError('no valid worker checkpoint remains; refusing to reset existing training progress')
            start_step, n_tokens = 0, 0
            tuning = None
            saved_rng = None
            if ckpt_path.exists():  # resume after an interruption
                from moth.training.checkpoint import verify

                if not verify(ckpt_path):
                    ckpt_path.replace(ckpt_path.with_name(ckpt_path.name + ".corrupt"))
                    raise RuntimeError("worker checkpoint checksum failed; preserved as .corrupt")
                ck = torch.load(ckpt_path, map_location=device, weights_only=False)
                if ck.get("base_sha256") == spec["base_sha256"]:
                    model.load_state_dict(ck["model"])
                    opt.load_state_dict(ck["optimizer"])
                    gen.set_state(ck["gen"].cpu())
                    start_step, n_tokens = ck["step"], ck["tokens"]
                    tuning = ck.get("batch_tuning")
                    saved_rng = ck.get("rng")
                    self.log(f"job {jid}: resuming from step {start_step}")
            held = tokens[-(4 * 257):] if len(tokens) > 4 * 257 * 4 else tokens
            held_mask = None if loss_mask is None else loss_mask[len(tokens) - len(held):]
            loss_before = batch_loss(_base_model(base, spec, device), held, device, mask=held_mask)
            seq = min(train["seq_len"], model.cfg.max_seq_len, len(tokens) - 2)
            duty = float(limits.get("duty_cycle") or 1.0)
            model.train()
            def sample(batch, rng=None):
                starts = torch.randint(0, len(tokens) - seq - 1, (batch,), generator=rng or gen).tolist()
                x = torch.from_numpy(np.stack([tokens[s:s + seq] for s in starts]).astype(np.int64)).to(device)
                y = torch.from_numpy(np.stack([tokens[s + 1:s + seq + 1] for s in starts]).astype(np.int64)).to(device)
                m = (torch.from_numpy(np.stack([loss_mask[s + 1:s + seq + 1] for s in starts]).astype(np.uint8)).to(device)
                     if loss_mask is not None else None)  # aligned with the targets, as in local training
                return x, y, m

            if tuning is None and train.get("batch_autotune", True):
                from moth.training.autotune import tune_batch

                phase("measuring the batch size")
                tuning = tune_batch(model, train["batch_size"], 1,
                                    lambda b: sample(b, torch.Generator().manual_seed(jid)), device, seq_len=seq)
            micro = tuning["batch_size"] if tuning else train["batch_size"]
            accumulation = tuning["grad_accum"] if tuning else 1
            if micro * accumulation != train["batch_size"]:
                raise RuntimeError("worker checkpoint effective batch differs from the assigned job")
            if saved_rng:
                torch.set_rng_state(saved_rng["torch"].cpu())
                if device == "cuda" and saved_rng.get("cuda") is not None:
                    torch.cuda.set_rng_state_all([s.cpu() for s in saved_rng["cuda"]])
            completed_steps = start_step
            phase("training")

            def checkpoint():
                from moth.training.checkpoint import atomic_torch_save

                atomic_torch_save({"model": model.state_dict(), "optimizer": opt.state_dict(), "gen": gen.get_state(),
                                  "batch_tuning": tuning, "step": completed_steps, "tokens": n_tokens,
                                  "rng": {"torch": torch.get_rng_state(),
                                          "cuda": torch.cuda.get_rng_state_all() if device == "cuda" else None},
                                  "base_sha256": spec["base_sha256"]}, ckpt_path)
                self.training_metrics = {**(self.training_metrics or {}), 'step': completed_steps, 'tokens': n_tokens,
                                         'checkpoint_step': completed_steps}

            last_snapshot = [time.time()]

            def snapshot(force: bool = False) -> None:
                """0.9.0: send the progress so far to MOTH Cloud (every 10 minutes, and when pausing), so if
                this job is taken back the experiment continues from here instead of from step 0."""
                if spec.get("round", 0) >= 0 or completed_steps <= 0 or (completed_steps <= start_step and not force):
                    return  # evolution jobs only (shared rounds are short), and only with new progress
                if not force and time.time() - last_snapshot[0] < SNAPSHOT_SECONDS:
                    return
                last_snapshot[0] = time.time()
                try:
                    st = model.state_dict()
                    d = {k: st[k].detach().cpu().float() - base[k].float() for k in base}
                    body = serialize_state(d)
                    self.client.snapshot(jid, {"base_sha256": spec["base_sha256"], "delta_sha256": tensor_bytes_sha256(body),
                                               "step": completed_steps, "tokens": n_tokens}, body)
                except Exception as e:  # noqa: BLE001 — best effort; an older MOTH Cloud has no snapshots
                    self.log(f"job {jid}: progress snapshot not sent ({e})")

            for step in range(start_step, train["steps"]):
                if self.stop_event.is_set() or self.revoked or self.cancelled_job == jid:
                    if completed_steps > 0:
                        checkpoint()
                    raise Stop()
                if self.paused and completed_steps > 0:
                    checkpoint()
                    snapshot(force=True)  # a pause may last: let MOTH Cloud continue elsewhere from here
                while self.paused and not self.stop_event.is_set() and self.cancelled_job != jid:
                    time.sleep(1)
                if self.stop_event.is_set() or self.revoked or self.cancelled_job == jid:
                    if completed_steps > 0:
                        checkpoint()
                    raise Stop()
                t0 = time.time()
                train_loss = 0.0
                for _ in range(accumulation):
                    x, y, m = sample(micro)
                    _, loss = model(x, y, loss_mask=m)
                    if not torch.isfinite(loss):
                        raise RuntimeError("training diverged (non-finite loss)")
                    (loss / accumulation).backward()
                    train_loss += loss.detach().item() / accumulation
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                opt.zero_grad(set_to_none=True)
                n_tokens += micro * seq * accumulation
                completed_steps = step + 1
                self.training_metrics = {**(self.training_metrics or {}), 'step': completed_steps, 'tokens': n_tokens,
                                         'train_loss': train_loss}
                self.progress = (step + 1) / train["steps"]
                if (step + 1) % CHECKPOINT_EVERY == 0 and step + 1 < train["steps"]:
                    checkpoint()
                    self.client.progress(jid, self.progress)
                    snapshot()
                if duty < 1.0:
                    time.sleep((time.time() - t0) * (1 / duty - 1))
            checkpoint()  # an upload failure must not discard completed optimization steps
            loss_after = batch_loss(model, held, device, mask=held_mask)
            if not (math.isfinite(loss_before) and math.isfinite(loss_after)):
                raise RuntimeError("non-finite evaluation loss")
            new = model.state_dict()
            delta = {k: new[k].detach().cpu().float() - base[k].float() for k in base}
            payload = serialize_state(delta)
            meta = {"round": spec["round"], "base_sha256": spec["base_sha256"],
                    "delta_sha256": tensor_bytes_sha256(payload), "tokens": n_tokens, "steps": train["steps"],
                    "loss_before": loss_before, "loss_after": loss_after, "protocol": spec["protocol"],
                    "worker_version": __version__}
            meta["batch_tuning"] = tuning
            meta["train_loss"] = (self.training_metrics or {}).get('train_loss')
            phase("uploading the result")
            result = self.client.result(jid, meta, payload)
            ckpt_path.unlink(missing_ok=True)
            ckpt_path.with_name(ckpt_path.name + ".sha256").unlink(missing_ok=True)
            self.log(f"job {jid}: {'accepted' if result.get('accepted') else 'rejected'} "
                     f"(loss {loss_before:.3f} → {loss_after:.3f})")
            return result
        except Stop:
            self.log(f"job {jid}: stopped; progress is checkpointed and the job will resume")
            raise
        except ServerError:
            raise
        except Exception as e:  # noqa: BLE001 — report and move on
            if self.device == "cuda" and any(marker in str(e).lower() for marker in ("cuda", "out of memory", "cublas")):
                self.device, self.bench = "cpu", None
                self.log("GPU failed; subsequent eligible work uses CPU. Saved checkpoints are retained.")
            self.log(f"job {jid} failed: {e}")
            try:
                self.client.fail(jid, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass
            return {"accepted": False, "error": str(e)}
        finally:
            self.current_job, self.progress = None, None
            self.training_metrics = None


def _eval_loss(weights: bytes, data: bytes, model_config: dict, progress=None) -> tuple[float, int]:
    """Masked negative log-likelihood (sum, count) of a candidate on held-out token data (CPU, fp32)."""
    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    state = torch.load(io.BytesIO(weights), map_location="cpu", weights_only=True)
    d = torch.load(io.BytesIO(data), map_location="cpu", weights_only=True)
    model = MothModel(MothConfig.from_dict(model_config))
    model.load_state_dict({k: v.float() if v.is_floating_point() else v for k, v in state.items()})
    model.eval()
    ids, mask, offs = d["ids"], d["mask"].bool(), d["offsets"].tolist()
    total, count = 0.0, 0
    with torch.no_grad():
        for n, (a, b) in enumerate(zip(offs, offs[1:])):
            x = ids[a:b]
            logits, _ = model(x[:-1].unsqueeze(0))
            lp = torch.log_softmax(logits[0].float(), dim=-1)
            tgt = x[1:]
            m = mask[a + 1:b]
            nll = -lp[torch.arange(len(tgt)), tgt][m]
            total += float(nll.sum())
            count += int(m.sum())
            if progress:
                progress((n + 1) / max(1, len(offs) - 1))
    return total, count


def _base_model(base: dict, spec: dict, device: str):
    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    m = MothModel(MothConfig.from_dict(spec["model_config"])).to(device)
    m.load_state_dict(base)
    return m.eval()
