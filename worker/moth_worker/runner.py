"""Worker loop: heartbeats, job claiming, resumable training, verified uploads, reconnects."""

from __future__ import annotations

import io
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
from moth_worker.hardware import cached_benchmark, compute_kind, detect

CHECKPOINT_EVERY = 25


class Stop(Exception):
    pass


class WorkerRunner:
    def __init__(self, client: WorkerClient, state_dir: Path, allow_cpu: bool = False,
                 log: Callable[[str], None] = print, heartbeat_seconds: float = 30.0,
                 update_check_seconds: float | None = 1800.0):
        self.client = client
        self.state_dir = Path(state_dir)
        (self.state_dir / "jobs").mkdir(parents=True, exist_ok=True)
        self.allow_cpu = allow_cpu
        self.log = log
        self.heartbeat_seconds = heartbeat_seconds
        self.current_job: int | None = None
        self.progress: float | None = None
        self.paused = False
        self.revoked = False
        self.limits: dict[str, Any] = {}
        self.stop_event = threading.Event()
        self.update_check_seconds = update_check_seconds
        self._next_update_check = 0.0
        self.updated_to: str | None = None
        self.device: str | None = None
        self.bench: dict[str, Any] | None = None

    def hardware(self) -> dict[str, Any]:
        """Detected hardware plus the measured benchmark (taken once, cached for a week)."""
        hw = detect()
        if self.device is None:
            self.device = "cuda" if compute_kind(hw) == "gpu" else "cpu"
            self.bench = cached_benchmark(self.state_dir, self.device)
        return {**hw, "benchmark": self.bench}

    # ---- heartbeat -----------------------------------------------------------------------
    def beat(self) -> None:
        resp = self.client.heartbeat(self.hardware(), self.current_job, self.progress)
        self.paused, self.revoked, self.limits = resp["paused"], resp["revoked"], resp.get("limits") or {}
        from moth_worker import updater

        done = updater.confirm_healthy(self.state_dir)
        if done:
            self.log(f"MOTH Worker {__version__} is connected (updated from {done.get('from')})")
            try:
                self.client.report_update(done.get("from"), __version__, True)
            except Exception:  # noqa: BLE001 — reporting is best effort
                pass

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
            self.log(f"update to {info.get('version')} was not installed: {e}")
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
        jid, spec = job["id"], job["spec"]
        self.current_job, self.progress = jid, 0.0
        self.log(f"job {jid}: round {spec['round']}, shard {spec['shard_id']}")
        try:
            weights = self.client.download(jid, "weights", spec["base_sha256"])
            shard = self.client.download(jid, "shard", spec["shard_sha256"])
            tokens = np.frombuffer(shard, dtype=np.uint32)
            device = self.device or ("cuda" if compute_kind(detect()) == "gpu" else "cpu")
            limits = {**job.get("limits", {}), **self.limits}
            if device == "cpu":  # leave a core for the system unless the owner set a limit
                torch.set_num_threads(max(1, int(limits.get("cpu_threads") or max(1, (os.cpu_count() or 2) - 1))))
            if device == "cuda" and limits.get("gpu_memory_fraction"):
                torch.cuda.set_per_process_memory_fraction(float(limits["gpu_memory_fraction"]))
            base = torch.load(io.BytesIO(weights), map_location="cpu", weights_only=True)
            model = MothModel(MothConfig.from_dict(spec["model_config"])).to(device)
            model.load_state_dict(base)
            train = spec["train"]
            opt = model.configure_optimizer(train["lr"], train.get("weight_decay", 0.0), device_type=device)
            gen = torch.Generator().manual_seed(jid)
            ckpt_path = self.state_dir / "jobs" / f"{jid}.pt"
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
            loss_before = batch_loss(_base_model(base, spec, device), held, device)
            seq = min(train["seq_len"], model.cfg.max_seq_len, len(tokens) - 2)
            duty = float(limits.get("duty_cycle") or 1.0)
            model.train()
            def sample(batch, rng=None):
                starts = torch.randint(0, len(tokens) - seq - 1, (batch,), generator=rng or gen).tolist()
                x = torch.from_numpy(np.stack([tokens[s:s + seq] for s in starts]).astype(np.int64)).to(device)
                y = torch.from_numpy(np.stack([tokens[s + 1:s + seq + 1] for s in starts]).astype(np.int64)).to(device)
                return x, y, None

            if tuning is None and train.get("batch_autotune", True):
                from moth.training.autotune import tune_batch

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

            def checkpoint():
                from moth.training.checkpoint import atomic_torch_save

                atomic_torch_save({"model": model.state_dict(), "optimizer": opt.state_dict(), "gen": gen.get_state(),
                                  "batch_tuning": tuning, "step": completed_steps, "tokens": n_tokens,
                                  "rng": {"torch": torch.get_rng_state(),
                                          "cuda": torch.cuda.get_rng_state_all() if device == "cuda" else None},
                                  "base_sha256": spec["base_sha256"]}, ckpt_path)

            for step in range(start_step, train["steps"]):
                if self.stop_event.is_set() or self.revoked:
                    if completed_steps > 0:
                        checkpoint()
                    raise Stop()
                while self.paused and not self.stop_event.is_set():
                    time.sleep(1)
                if self.stop_event.is_set() or self.revoked:
                    if completed_steps > 0:
                        checkpoint()
                    raise Stop()
                t0 = time.time()
                for _ in range(accumulation):
                    x, y, _ = sample(micro)
                    _, loss = model(x, y)
                    if not torch.isfinite(loss):
                        raise RuntimeError("training diverged (non-finite loss)")
                    (loss / accumulation).backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                opt.zero_grad(set_to_none=True)
                n_tokens += micro * seq * accumulation
                completed_steps = step + 1
                self.progress = (step + 1) / train["steps"]
                if (step + 1) % CHECKPOINT_EVERY == 0 and step + 1 < train["steps"]:
                    checkpoint()
                    self.client.progress(jid, self.progress)
                if duty < 1.0:
                    time.sleep((time.time() - t0) * (1 / duty - 1))
            loss_after = batch_loss(model, held, device)
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
            self.log(f"job {jid} failed: {e}")
            try:
                self.client.fail(jid, f"{type(e).__name__}: {e}")
            except Exception:  # noqa: BLE001
                pass
            return {"accepted": False, "error": str(e)}
        finally:
            self.current_job, self.progress = None, None


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
