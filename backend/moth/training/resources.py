"""Effective CPU/RAM capacity, including container quotas; native hosts fall back normally."""
import os
from pathlib import Path


def cpu_count() -> int:
    count = os.cpu_count() or 1
    try:
        count = min(count, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        pass
    try:
        quota, period = Path('/sys/fs/cgroup/cpu.max').read_text().split()
        if quota != 'max':
            count = min(count, max(1, int(quota) // int(period)))
    except (OSError, ValueError):
        pass
    return max(1, count)


def memory_budget(total: int, available: int) -> tuple[int, int]:
    try:
        cap = Path('/sys/fs/cgroup/memory.max').read_text().strip()
        if cap != 'max':
            total = min(total, int(cap))
            used = int(Path('/sys/fs/cgroup/memory.current').read_text())
            available = min(available, max(0, int(cap) - used))
    except (OSError, ValueError):
        pass
    return total, min(total, available)
