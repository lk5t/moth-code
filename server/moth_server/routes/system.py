"""Owner Dashboard → Server: health and resource usage of this MOTH Cloud host (no shell access).

Reads ``/proc`` and the filesystem directly (Linux), so it needs no extra dependencies and
never runs commands. On other platforms the numbers that can't be read are ``null``.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy import desc, func, select

from moth_server.context import Ctx, get_ctx
from moth_server.db import error_log, now, sessions
from moth_server.deps import Auth, require_owner

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _cpu_times() -> tuple[int, int] | None:
    try:
        parts = [int(x) for x in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
        return sum(parts), idle
    except (OSError, ValueError, IndexError):
        return None


def cpu_percent(sample_s: float = 0.25) -> float | None:
    a = _cpu_times()
    if not a:
        return None
    time.sleep(sample_s)
    b = _cpu_times()
    total, idle = b[0] - a[0], b[1] - a[1]
    return round(100.0 * (1 - idle / total), 1) if total > 0 else 0.0


def memory() -> dict | None:
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) * 1024
        total, avail = info["MemTotal"], info.get("MemAvailable", info.get("MemFree", 0))
        return {"total": total, "used": total - avail, "available": avail,
                "percent": round(100 * (total - avail) / total, 1)}
    except (OSError, KeyError, ValueError):
        return None


def disk(path: Path) -> dict:
    u = shutil.disk_usage(path)
    return {"total": u.total, "used": u.used, "free": u.free, "percent": round(100 * u.used / u.total, 1)}


def process_rss() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def hardware() -> dict:
    """What MOTH Cloud inference can use on this host. Never assumes a GPU exists."""
    out: dict = {"cpu_count": os.cpu_count(), "cuda": False, "gpus": []}
    try:
        import torch

        if torch.cuda.is_available():
            out["cuda"] = True
            out["gpus"] = [{"name": torch.cuda.get_device_name(i),
                            "memory": torch.cuda.get_device_properties(i).total_memory}
                           for i in range(torch.cuda.device_count())]
    except Exception:  # noqa: BLE001 — a broken driver means "no GPU", not a crash
        pass
    return out


@router.get("/system")
def system(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server import __version__

    t = now()
    active = ctx.db.one(select(func.count(func.distinct(sessions.c.user_id)).label("n"))
                        .where(sessions.c.last_used_at > t - 900, sessions.c.revoked_at.is_(None)))["n"]
    errors = ctx.db.all(select(error_log).order_by(desc(error_log.c.id)).limit(20))
    errors_24h = ctx.db.one(select(func.count().label("n")).where(error_log.c.ts > t - 86400))["n"]
    load = None
    try:
        load = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    except (OSError, ValueError):
        pass
    engine = ctx.extras.get("inference_engine")
    return {"version": __version__, "environment": ctx.settings.environment, "status": "ok",
            "cpu_percent": cpu_percent(), "load": load, "memory": memory(), "disk": disk(ctx.settings.data_dir),
            "process_rss": process_rss(), "hardware": hardware(),
            "active_users_15m": active, "errors_24h": errors_24h, "recent_errors": errors,
            "inference": {"loaded": engine is not None, "model_version": ctx.extras.get("deployed_version")},
            "time": t}
