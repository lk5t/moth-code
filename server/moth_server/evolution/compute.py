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
    from moth.training.resources import cpu_count, memory_budget, pressure

    out: dict[str, Any] = {"cpu_count": cpu_count(), "load_average": None, "memory": memory(), "gpus": [],
                           "backends": ["cpu"], "pressure": pressure()}
    if out['memory']:
        total, avail = memory_budget(out['memory']['total'], out['memory']['available'])
        out['memory'] = {'total': total, 'available': avail, 'used': total - avail,
                         'percent': round(100 * (total - avail) / max(1, total), 1)}
    try:
        out["load_average"] = [round(x, 2) for x in os.getloadavg()]
    except (OSError, AttributeError):
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
    from moth_server.training import capacity_bytes, worker_allowed

    rows = ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
    if worker_ids is not None:
        rows = [w for w in rows if w['id'] in worker_ids]
    online = [w for w in rows if worker_allowed(ctx, w) and w["status"] == "online" and not w["paused"]
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


# ---- speed-aware placement (0.6.3) -----------------------------------------------------------------------
NETWORK_FACTOR = 0.8   # until a worker's real throughput is measured, assume transfers cost it 20 %
PREFER_WORKER = 0.8    # a worker at least this fast (relative to this server) takes work first: MOTH Cloud stays responsive
MIN_PARALLEL = 0.5     # slower than this, a parallel experiment would make the cycle longer than running it here later


def throughput(ctx: Ctx) -> dict[str, float]:
    """Measured end-to-end training throughput (tokens/s, including downloads and uploads for workers),
    per ``local:<device>`` and ``worker:<id>``."""
    return ctx.db.get_config("compute_throughput", {}) or {}


def record_throughput(ctx: Ctx, key: str, tokens: float | None, seconds: float | None) -> None:
    if not tokens or not seconds or seconds <= 0:
        return
    tp = throughput(ctx)
    new = float(tokens) / float(seconds)
    tp[key] = round(new if key not in tp else 0.5 * tp[key] + 0.5 * new, 3)  # recent runs count most
    ctx.db.set_config("compute_throughput", tp)


def local_gflops(ctx: Ctx) -> float | None:
    """This server's measured CPU matrix-multiply speed (the same benchmark workers run), cached a day."""
    cached = ctx.db.get_config("local_benchmark", {}) or {}
    if cached.get("gflops") and time.time() - float(cached.get("at") or 0) < 86400:
        return float(cached["gflops"])
    try:
        import torch

        n, runs = 512, 8
        a, b = torch.randn(n, n), torch.randn(n, n)
        torch.mm(a, b)
        t0 = time.perf_counter()
        for _ in range(runs):
            torch.mm(a, b)
        g = round(2 * n ** 3 * runs / (time.perf_counter() - t0) / 1e9, 1)
    except Exception:  # noqa: BLE001
        return None
    ctx.db.set_config("local_benchmark", {"gflops": g, "at": time.time()})
    return g


def available_workers(ctx: Ctx, need_bytes: int = 0, worker_ids: list[int] | None = None,
                      min_version: str | None = None) -> list[dict[str, Any]]:
    """Workers that could start this job now: compatible (version), not busy with another job, and not
    already spoken for by jobs still waiting in the queue (those go to the fastest free workers first)."""
    from moth_server.db import training_jobs
    from moth_server.training import version_at_least

    jobs = ctx.db.all(select(training_jobs.c.status, training_jobs.c.worker_id, training_jobs.c.kind).where(
        training_jobs.c.status.in_(("queued", "leased"))))
    busy = {j["worker_id"] for j in jobs if j["status"] == "leased" and j["worker_id"]}
    queued = sum(1 for j in jobs if j["status"] == "queued" and j["kind"] in ("evolve_train", "dist_shard"))
    versions = {w["id"]: w.get("version") for w in ctx.db.all(select(workers.c.id, workers.c.version))}
    free = [w for w in worker_speeds(ctx, need_bytes, worker_ids) if w["id"] not in busy
            and (not min_version or version_at_least(versions.get(w["id"]), min_version))]
    return free[queued:]


def worker_speeds(ctx: Ctx, need_bytes: int = 0, worker_ids: list[int] | None = None) -> list[dict[str, Any]]:
    """Online workers that can hold the job, with their speed relative to this server's CPU: measured
    throughput when both have run jobs, else the benchmark with a network discount, else unknown
    (an unmeasured worker is tried, so its first job measures it)."""
    from moth_server.training import capacity_bytes, worker_allowed

    rows = ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
    if worker_ids is not None:
        rows = [w for w in rows if w["id"] in worker_ids]
    tp, lg = throughput(ctx), None
    out = []
    for w in rows:
        if not (worker_allowed(ctx, w) and w["status"] == "online" and not w["paused"]
                and (w.get("last_heartbeat_at") or 0) >= time.time() - 180):
            continue
        hw = json.loads(w["hardware"] or "{}")
        if capacity_bytes(hw, json.loads(w["limits"] or "{}")) < need_bytes:
            continue
        gpu = hw.get("compute") == "gpu" or (hw.get("compute") is None and bool(hw.get("gpus")))
        if tp.get(f"worker:{w['id']}") and tp.get("local:cpu"):
            ratio, basis = tp[f"worker:{w['id']}"] / tp["local:cpu"], "measured"
        else:
            g = (hw.get("benchmark") or {}).get("gflops")
            lg = lg if lg is not None else local_gflops(ctx)
            if g and lg:
                ratio, basis = float(g) * NETWORK_FACTOR / lg, "benchmark"
            else:
                ratio, basis = 1.0, "unmeasured"
        out.append({"id": w["id"], "name": w["name"], "gpu": gpu, "ratio": round(ratio, 3), "basis": basis})
    return sorted(out, key=lambda x: -x["ratio"])


def choose_backend(ctx: Ctx, settings: dict, need_bytes: int,
                   min_worker_version: str | None = None) -> tuple[dict | None, list[str]]:
    """Where an experiment can train now: {"backend": "local"|"worker", "device": ...} or None + reasons."""
    reasons: list[str] = []
    be = settings["backends"]
    hw = local(ctx)
    if be.get("local_gpu") and hw["gpus"]:
        fraction = float(settings["limits"]["gpu_memory_fraction"])
        for index, gpu in enumerate(hw['gpus']):
            if gpu["memory_free"] * fraction >= need_bytes:
                return {"backend": "local", "device": "cuda" if index == 0 else f"cuda:{index}"}, []
        reasons.append(f"the local GPU does not have {need_bytes / GB:.1f} GB of free memory for training")
    elif be.get("local_gpu"):
        reasons.append("this server has no GPU")
    free: list[dict[str, Any]] = []
    if be.get("workers"):
        cap = worker_capacity(ctx, need_bytes, settings.get("worker_ids"))
        free = available_workers(ctx, need_bytes, settings.get("worker_ids"), min_worker_version)
        if any(w["gpu"] for w in free):
            return {"backend": "worker", "device": "worker", "worker": next(w for w in free if w["gpu"])}, []
        if not cap["total"]:
            reasons.append("no MOTH workers are enrolled")
        elif not cap["online"]:
            reasons.append("no MOTH worker is online")
        elif not cap["usable"]:
            reasons.append(f"no online MOTH worker has {need_bytes / GB:.1f} GB of memory for this job")
        elif not free:
            reasons.append("every suitable MOTH worker is busy" + (f" or older than {min_worker_version} (this "
                           "job's conversation data needs a worker that applies its loss mask)" if min_worker_version else ""))
    local_fits = False
    if be.get("local_cpu"):
        mem = hw["memory"] or {}
        reserve = float(settings["limits"]["min_free_memory_gb"]) * GB
        local_fits = bool(mem and mem.get("available", 0) - reserve >= need_bytes)
    if free:
        # Prefer a suitable external worker: it keeps MOTH Cloud's CPU free for answering and coordination.
        best = free[0]
        if not local_fits or best["ratio"] >= PREFER_WORKER:
            return {"backend": "worker", "device": "worker", "worker": best}, []
    if be.get("local_cpu"):
        if local_fits:
            return {"backend": "local", "device": "cpu"}, []
        reasons.append(f"not enough free memory for CPU training (needs {need_bytes / GB:.1f} GB plus the "
                       f"{reserve / GB:.1f} GB reserve)")
    else:
        reasons.append("CPU training on this server is turned off (Evolution → Settings → Compute)")
    if free:
        return {"backend": "worker", "device": "worker", "worker": free[0]}, []
    return None, reasons


def local_blockers(ctx: Ctx, settings: dict, device: str, need_disk: int = 0) -> list[str]:
    """Why local training must not run right now (empty list = it may run)."""
    from moth_server.evolution import memory as MEM

    out = []
    lim = settings["limits"]
    hw = local(ctx)
    from moth.training.resources import pressure_reason
    reason = pressure_reason(hw.get("pressure") or {})
    if reason:
        out.append(reason)
    mem = hw["memory"] or {}
    if mem and mem.get("available", 0) < float(lim["min_free_memory_gb"]) * GB:
        out.append(f"free memory is below the {lim['min_free_memory_gb']} GB reserve")
    if hw["disk"]["free"] < float(lim["min_free_disk_gb"]) * GB + need_disk:
        out.append(f"free disk space is below the {lim['min_free_disk_gb']} GB reserve")
    act = activity(ctx)
    # Balanced yields even GPU training to active inference. Training First still enforces
    # CPU contention, the owner's traffic ceiling, reserves, quiet hours and compute budgets.
    selected_priority = (ctx.db.get_config("evolution_settings", {}) or {}).get("training_priority")
    if act.active > 0 and (device == "cpu" or selected_priority == "balanced"):
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
