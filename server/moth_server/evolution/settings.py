"""Evolution settings (stored in ``server_config['evolution_settings']``), with validation."""

from __future__ import annotations

import copy
import os
from typing import Any

from moth_server.context import Ctx

KEY = "evolution_settings"

DEFAULTS: dict[str, Any] = {
    # Automatic evolution is on by default, but a cycle only starts once its prerequisites exist: a
    # deployed model, an Owner-approved training dataset for it, and a compute backend that can train.
    "enabled": True,
    "paused": False,
    "interval_hours": 24.0,          # time between the end of one cycle and the start of the next
    "auto_deploy": True,             # deploy a candidate that passed every gate (then monitor it)
    "max_experiments_per_cycle": 2,
    "training": {"steps": 200, "lr": 3e-4, "batch_size": 8, "seq_len": 256, "weight_decay": 0.0,
                 "eval_interval": 50, "checkpoint_interval": 25},
    "min_dataset_tokens": 20_000,    # an approved dataset needs at least this many training tokens
    "gates": {
        "min_improvement": 0.005,      # primary held-out score must improve by at least 0.5 %
        "retention_tolerance": 0.02,   # no retained capability may get more than 2 % worse
        "code_tolerance": 0.05,        # valid-Python rate may drop by at most 5 points
        "task_tolerance": 0.02,        # task-suite accuracy may drop by at most 2 points
        "max_speed_regression": 0.25,  # generation speed may drop by at most 25 %
        "max_memory_growth": 0.25,     # peak memory may grow by at most 25 %
    },
    "monitoring": {"minutes": 30.0, "max_error_rate": 0.05, "max_latency_factor": 2.0, "min_requests": 5},
    "backends": {"local_gpu": True, "local_cpu": False, "workers": True},
    "limits": {"cpu_threads": max(1, (os.cpu_count() or 2) // 2), "min_free_memory_gb": 1.0,
               "min_free_disk_gb": 5.0, "gpu_memory_fraction": 0.8, "duty_cycle": 1.0},
    # Train during low activity: local training waits (or pauses with a checkpoint) while MOTH Cloud
    # serves more than this many chat requests per minute, and outside quiet hours if they are set.
    "schedule": {"max_requests_per_minute": 2.0, "quiet_hours_utc": None},
    "budget": {"max_compute_hours_per_day": 6.0, "max_cycle_hours": 12.0},
    "max_consecutive_failures": 3,
    "allow_from_scratch": False,     # an incompatible architecture/tokenizer is never loaded blindly
    "retention_days": 180,           # evolution events and experiment logs (model versions are kept)
}

_BOUNDS = {
    "interval_hours": (0.01, 24 * 90), "max_experiments_per_cycle": (1, 8), "min_dataset_tokens": (1, 10**12),
    "max_consecutive_failures": (1, 50), "retention_days": (1, 3650),
    "training.steps": (1, 1_000_000), "training.lr": (1e-7, 1e-1), "training.batch_size": (1, 512),
    "training.seq_len": (8, 32768), "training.weight_decay": (0.0, 1.0), "training.eval_interval": (1, 100_000),
    "training.checkpoint_interval": (1, 100_000),
    "gates.min_improvement": (0.0, 0.5), "gates.retention_tolerance": (0.0, 0.5), "gates.code_tolerance": (0.0, 1.0),
    "gates.task_tolerance": (0.0, 1.0), "gates.max_speed_regression": (0.0, 0.9), "gates.max_memory_growth": (0.0, 5.0),
    "monitoring.minutes": (0.0, 24 * 60), "monitoring.max_error_rate": (0.0, 1.0),
    "monitoring.max_latency_factor": (1.0, 100.0), "monitoring.min_requests": (0, 10_000),
    "limits.cpu_threads": (1, 1024), "limits.min_free_memory_gb": (0.0, 4096.0), "limits.min_free_disk_gb": (0.0, 1e6),
    "limits.gpu_memory_fraction": (0.05, 1.0), "limits.duty_cycle": (0.05, 1.0),
    "schedule.max_requests_per_minute": (0.0, 1e6),
    "budget.max_compute_hours_per_day": (0.0, 24.0), "budget.max_cycle_hours": (0.01, 24 * 30),
}


class SettingsError(ValueError):
    pass


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def get(ctx: Ctx) -> dict[str, Any]:
    return _merge(DEFAULTS, ctx.db.get_config(KEY, {}) or {})


def validate(s: dict[str, Any]) -> None:
    for path, (lo, hi) in _BOUNDS.items():
        node: Any = s
        for part in path.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            continue
        if not isinstance(node, (int, float)) or isinstance(node, bool) or not (lo <= node <= hi):
            raise SettingsError(f"{path} must be a number between {lo} and {hi}")
    for b in ("enabled", "paused", "auto_deploy", "allow_from_scratch"):
        if not isinstance(s.get(b), bool):
            raise SettingsError(f"{b} must be true or false")
    for b, v in (s.get("backends") or {}).items():
        if b not in DEFAULTS["backends"] or not isinstance(v, bool):
            raise SettingsError(f"backends.{b} is not a known backend switch")
    q = (s.get("schedule") or {}).get("quiet_hours_utc")
    if q is not None and not (isinstance(q, list) and len(q) == 2 and all(isinstance(h, int) and 0 <= h <= 23 for h in q)):
        raise SettingsError("schedule.quiet_hours_utc must be null or [start_hour, end_hour] (0–23, UTC)")


def update(ctx: Ctx, changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - set(DEFAULTS)
    if unknown:
        raise SettingsError(f"unknown setting(s): {', '.join(sorted(unknown))}")
    stored = ctx.db.get_config(KEY, {}) or {}
    new_stored = _merge(stored, changes)
    merged = _merge(DEFAULTS, new_stored)
    validate(merged)
    ctx.db.set_config(KEY, new_stored)
    return merged
