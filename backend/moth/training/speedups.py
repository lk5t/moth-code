"""1.0.5 training speed-ups shared by MOTH Cloud's trainer and the workers.

* ``fold``: short context first. For the first part of a long-context run every batch row of L tokens is
  cut into L/S rows of S tokens. The model sees exactly the same tokens (same data, same tokens per step,
  same learning-rate schedule), but attention over S instead of L tokens makes each step much cheaper,
  and small models learn the basics faster from short windows. The last part trains at the full length.
* ``physical_cores``: hyper-threads share one core's maths units, so training on every logical CPU is
  usually slower than one thread per physical core.
"""
from __future__ import annotations

import os
from pathlib import Path

SHORT_CONTEXT = 256
SHORT_UNTIL = 0.7   # share of a run trained with the short context


def fold(x, y, m, short: int):
    """(B, L) → (B·L/short, short) when it divides evenly; otherwise unchanged."""
    if not short or x.shape[1] <= short or x.shape[1] % short:
        return x, y, m
    r = x.shape[1] // short
    def cut(t):
        return None if t is None else t.reshape(t.shape[0] * r, short)
    return cut(x), cut(y), cut(m)


def physical_cores() -> int:
    """Physical cores this process may use (Linux topology, then a hyper-threading estimate)."""
    try:
        allowed = sorted(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        allowed = list(range(os.cpu_count() or 1))
    cores = set()
    for c in allowed:
        try:
            cores.add(Path(f"/sys/devices/system/cpu/cpu{c}/topology/thread_siblings_list").read_text().strip())
        except OSError:
            cores = set()
            break
    if cores:
        return max(1, len(cores))
    try:
        import psutil  # Windows / macOS when available
        n = psutil.cpu_count(logical=False)
        if n:
            return max(1, min(int(n), len(allowed)))
    except Exception:  # noqa: BLE001
        pass
    return max(1, len(allowed))
