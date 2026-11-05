"""Worker loop: heartbeats, job claiming, resumable training, verified uploads, reconnects."""

from __future__ import annotations

import io
import math
import threading
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import numpy as np
import torch

from moth_worker import __version__
from moth_worker.client import ServerError, WorkerClient
from moth_worker.hardware import detect

CHECKPOINT_EVERY = 25


class Stop(Exception):
    pass


class WorkerRunner:
    def __init__(self, client: WorkerClient, state_dir: Path, allow_cpu: bool = False,
                 log: Callable[[str], None] = print, heartbeat_seconds: float = 30.0):
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

    # ---- heartbeat -----------------------------------------------------------------------
    def beat(self) -> None:
        resp = self.client.heartbeat(detect(), self.current_job, self.progress)
        self.paused, self.revoked, self.limits = resp["paused"], resp["revoked"], resp.get("limits") or {}

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

    # ---- one training round ------------------------------------------------------------------
    def run_job(self, job: dict) -> dict:
        from moth.community.client import batch_loss
        from moth.community.validation import serialize_state, tensor_bytes_sha256
        from moth.model.config import MothConfig
        from moth.model.transformer import MothModel
        from moth.training.trainer import pick_device

        jid, spec = job["id"], job["spec"]
        self.current_job, self.progress = jid, 0.0
        self.log(f"job {jid}: round {spec['round']}, shard {spec['shard_id']}")
        try:
            weights = self.client.download(jid, "weights", spec["base_sha256"])
            shard = self.client.download(jid, "shard", spec["shard_sha256"])
            tokens = np.frombuffer(shard, dtype=np.uint32)
            device = pick_device("cpu" if self.allow_cpu and not torch.cuda.is_available() else "auto")
            limits = {**job.get("limits", {}), **self.limits}
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
            if ckpt_path.exists():  # resume after an interruption
                ck = torch.load(ckpt_path, map_location=device, weights_only=False)
                if ck.get("base_sha256") == spec["base_sha256"]:
                    model.load_state_dict(ck["model"])
                    opt.load_state_dict(ck["optimizer"])
                    gen.set_state(ck["gen"])
                    start_step, n_tokens = ck["step"], ck["tokens"]
                    self.log(f"job {jid}: resuming from step {start_step}")
            held = tokens[-(4 * 257):] if len(tokens) > 4 * 257 * 4 else tokens
            loss_before = batch_loss(_base_model(base, spec, device), held, device)
            seq = min(train["seq_len"], model.cfg.max_seq_len, len(tokens) - 2)
            duty = float(limits.get("duty_cycle") or 1.0)
            model.train()
            for step in range(start_step, train["steps"]):
                if self.stop_event.is_set() or self.revoked:
                    raise Stop()
                while self.paused and not self.stop_event.is_set():
                    time.sleep(1)
                t0 = time.time()
                starts = torch.randint(0, len(tokens) - seq - 1, (train["batch_size"],), generator=gen).tolist()
                x = torch.from_numpy(np.stack([tokens[s:s + seq] for s in starts]).astype(np.int64)).to(device)
                y = torch.from_numpy(np.stack([tokens[s + 1:s + seq + 1] for s in starts]).astype(np.int64)).to(device)
                _, loss = model(x, y)
                if not torch.isfinite(loss):
                    raise RuntimeError("training diverged (non-finite loss)")
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                opt.zero_grad(set_to_none=True)
                n_tokens += x.numel()
                self.progress = (step + 1) / train["steps"]
                if (step + 1) % CHECKPOINT_EVERY == 0 and step + 1 < train["steps"]:
                    torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), "gen": gen.get_state(),
                                "step": step + 1, "tokens": n_tokens, "base_sha256": spec["base_sha256"]}, ckpt_path)
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
            result = self.client.result(jid, meta, payload)
            ckpt_path.unlink(missing_ok=True)
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


def _base_model(base: dict, spec: dict, device: str):
    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    m = MothModel(MothConfig.from_dict(spec["model_config"])).to(device)
    m.load_state_dict(base)
    return m.eval()
