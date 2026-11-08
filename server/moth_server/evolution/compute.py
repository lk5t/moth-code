"""Smart compute manager: what can train, where, and when — measured, never assumed.

* Detects the server's CPU, RAM, disk, GPUs/VRAM and acceleration backends (CUDA via PyTorch), and the
  capabilities MOTH workers report (``workers.hardware``).
* Chooses a backend for an experiment: a local GPU, an online MOTH GPU worker, or (only if the Owner
  enables it) the local CPU — and only if the estimated memory fits with the configured reserve.
  If nothing suitable exists the experiment **waits** for compute; it is never reported as training.
* Protects live inference: local training starts only during low activity (chat requests per minute
  below the configured threshold, inside quiet hours if set) and is paused with a checkpoint when
  activity rises, memory or disk run low, or the daily compute budget is used up.
* One training process at a time per host; worker jobs are leased to one worker each.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import workers

GB = 1024**3


# ---- activity (fed by the inference route) ------------------------------------------------------------
class Activity:
    """Recent MOTH Cloud inference requests: count, active streams, errors and latency per model version."""

    def __init__(self, keep: int = 5000):
        self.lock = threading.Lock()
        self.requests: deque = deque(maxlen=keep)  # (ts, version, ok, seconds, tokens)
        self.active = 0

    def start(self) -> None:
        with self.lock:
            self.active += 1

    def finish(self, version: int | None, ok: bool, seconds: float, tokens: int) -> None:
        with self.lock:
            self.active = max(0, self.active - 1)
            self.requests.append((time.time(), version, ok, seconds, tokens))

    def per_minute(self, window_s: float = 300.0) -> float:
        cutoff = time.time() - window_s
        with self.lock:
            n = sum(1 for r in self.requests if r[0] >= cutoff)
        return n / (window_s / 60.0)

    def stats(self, version: int | None, since: float, until: float | None = None) -> dict[str, Any]:
        until = until or time.time()
        with self.lock:
            rows = [r for r in self.requests if r[1] == version and since <= r[0] <= until]
        n = len(rows)
        errors = sum(1 for r in rows if not r[2])
        ok_rows = [r for r in rows if r[2] and r[4] > 0]
        spt = (sum(r[3] for r in ok_rows) / sum(r[4] for r in ok_rows)) if ok_rows else None
        return {"requests": n, "errors": errors, "error_rate": errors / n if n else 0.0,
                "seconds_per_token": spt}


def activity(ctx: Ctx) -> Activity:
    a = ctx.extras.get("inference_activity")
    if a is None:
        a = ctx.extras.setdefault("inference_activity", Activity())
    return a


# ---- local hardware ------------------------------------------------------------------------------------
def local(ctx: Ctx) -> dict[str, Any]:
    from moth_server.routes.system import memory
    from moth.training.resources import cpu_count, memory_budget

    out: dict[str, Any] = {"cpu_count": cpu_count(), "load_average": None, "memory": memory(), "gpus": [],
                           "backends": ["cpu"]}
    if out['memory']:
        total, avail = memory_budget(out['memory']['total'], out['memory']['available'])
        out['memory'] = {'total': total, 'available': avail, 'used': total - avail,
                         'percent': round(100 * (total - avail) / max(1, total), 1)}
    try:
        out["load_average"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        pass
    du = shutil.disk_usage(ctx.settings.data_dir)
    out["disk"] = {"total": du.total, "free": du.free, "used": du.used, "path": "data"}
    try:
        import torch

        if torch.cuda.is_available():
            out["backends"].append("cuda")
            for i in range(torch.cuda.device_count()):
                free, total = torch.cuda.mem_get_info(i)
                out["gpus"].append({"name": torch.cuda.get_device_name(i), "memory_total": total, "memory_free": free})
    except Exception:  # noqa: BLE001 — a broken driver means "no GPU", not a crash
        pass
    return out


def worker_capacity(ctx: Ctx, need_bytes: int = 0, worker_ids: list[int] | None = None) -> dict[str, Any]:
    """Online MOTH workers (CPU and GPU) and how many can take a job needing ``need_bytes``."""
    from moth_server.training import capacity_bytes

    rows = ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
    if worker_ids is not None:
        rows = [w for w in rows if w['id'] in worker_ids]
    online = [w for w in rows if w["status"] == "online" and not w["paused"]
              and (w.get("last_heartbeat_at") or 0) >= time.time() - 180]
    hws = [json.loads(w["hardware"] or "{}") for w in online]
    gpu = [h for h in hws if h.get("compute") == "gpu" or (h.get("compute") is None and h.get("gpus"))]
    fitting = [h for h, w in zip(hws, online) if capacity_bytes(h, json.loads(w['limits'] or '{}')) >= need_bytes]
    fitting_gpu = [h for h in fitting if h.get("compute") == "gpu" or (h.get("compute") is None and h.get("gpus"))]
    return {"total": len(rows), "online": len(online), "online_gpu": len(gpu), "online_cpu": len(hws) - len(gpu),
            "usable_gpu": len(fitting_gpu),
            "usable": len(fitting), "gpus": [g.get("name") for h in gpu for g in h.get("gpus", [])],
            "gflops": round(sum(((h.get("benchmark") or {}).get("gflops") or 0) for h in hws), 1)}


def estimate_training_memory(params: int, batch: int, seq: int, d_model: int, layers: int) -> int:
    """fp32 weights + gradients + AdamW moments (16 bytes/param) plus activations and overhead."""
    activations = batch * seq * d_model * layers * 34 * 4
    return int(params * 16 + activations + 0.6 * GB)


# ---- decisions ------------------------------------------------------------------------------------------
def in_quiet_hours(settings: dict) -> bool:
    q = (settings.get("schedule") or {}).get("quiet_hours_utc")
    if not q:
        return True
    h = datetime.now(timezone.utc).hour
    start, end = q
    return start <= h < end if start <= end else (h >= start or h < end)


def choose_backend(ctx: Ctx, settings: dict, need_bytes: int) -> tuple[dict | None, list[str]]:
    """Where an experiment can train now: {"backend": "local"|"worker", "device": ...} or None + reasons."""
    reasons: list[str] = []
    be = settings["backends"]
    hw = local(ctx)
    if be.get("local_gpu") and hw["gpus"]:
        fraction = float(settings["limits"]["gpu_memory_fraction"])
        if any(g["memory_free"] * fraction >= need_bytes for g in hw["gpus"]):
            return {"backend": "local", "device": "cuda"}, []
        reasons.append(f"the local GPU does not have {need_bytes / GB:.1f} GB of free memory for training")
    elif be.get("local_gpu"):
        reasons.append("this server has no GPU")
    if be.get("workers"):
        cap = worker_capacity(ctx, need_bytes, settings.get("worker_ids"))
        if cap["usable_gpu"]:
            return {"backend": "worker", "device": "worker"}, []
        if not cap["total"]:
            reasons.append("no MOTH workers are enrolled")
        elif not cap["online"]:
            reasons.append("no MOTH worker is online")
        else:
            reasons.append(f"no online MOTH worker has {need_bytes / GB:.1f} GB of memory for this job")
    if be.get("local_cpu"):
        mem = hw["memory"] or {}
        reserve = float(settings["limits"]["min_free_memory_gb"]) * GB
        if mem and mem.get("available", 0) - reserve >= need_bytes:
            return {"backend": "local", "device": "cpu"}, []
        reasons.append(f"not enough free memory for CPU training (needs {need_bytes / GB:.1f} GB plus the "
                       f"{reserve / GB:.1f} GB reserve)")
    else:
        reasons.append("CPU training on this server is turned off (Evolution → Settings → Compute)")
    if be.get("workers") and cap["usable"]:
        return {"backend": "worker", "device": "worker"}, []
    return None, reasons


def local_blockers(ctx: Ctx, settings: dict, device: str, need_disk: int = 0) -> list[str]:
    """Why local training must not run right now (empty list = it may run)."""
    from moth_server.evolution import memory as MEM

    out = []
    lim = settings["limits"]
    hw = local(ctx)
    mem = hw["memory"] or {}
    if mem and mem.get("available", 0) < float(lim["min_free_memory_gb"]) * GB:
        out.append(f"free memory is below the {lim['min_free_memory_gb']} GB reserve")
    if hw["disk"]["free"] < float(lim["min_free_disk_gb"]) * GB + need_disk:
        out.append(f"free disk space is below the {lim['min_free_disk_gb']} GB reserve")
    act = activity(ctx)
    if device == "cpu" and act.active > 0:
        out.append("MOTH Cloud is answering requests (CPU is shared with inference)")
    rpm = act.per_minute()
    if rpm > float(settings["schedule"]["max_requests_per_minute"]):
        out.append(f"MOTH Cloud is busy ({rpm:.1f} requests/min)")
    if not in_quiet_hours(settings):
        out.append("outside the configured training hours")
    budget_h = float(settings["budget"]["max_compute_hours_per_day"])
    used = MEM.compute_seconds_since(ctx, time.time() - 86400) / 3600
    if used >= budget_h:
        out.append(f"today's training budget ({budget_h:g} h) is used up")
    return out
