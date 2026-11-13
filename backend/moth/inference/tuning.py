"""Serving performance: measure a loaded model and keep only optimisations that measurably help (0.8.0).

``profile`` measures generation speed (tokens/s) on a fixed greedy prompt. On CPU it also tries other
thread counts. A different count is kept only if it is at least ``MIN_GAIN`` faster **and** produces
exactly the same greedy output (quality unchanged); otherwise the current setting stays. Everything
measured is returned so it can be shown and compared between model versions.
"""

from __future__ import annotations

import os
import time
from typing import Any

MIN_GAIN = 0.10
PROBE = "def fibonacci(n):"


def _speed(engine, tokens: int) -> tuple[float, str]:
    from moth.model.generation import GenerationParams

    best, text = 0.0, ""
    for _ in range(2):  # best of two: the first run warms caches
        t0 = time.perf_counter()
        text, stats = engine.complete(PROBE, GenerationParams(max_new_tokens=tokens, temperature=0.0, top_k=1))
        dt = time.perf_counter() - t0
        best = max(best, stats.generated_tokens / dt if dt > 0 else 0.0)
    return best, text


def profile(engine, device: str, tokens: int = 32, tune_threads: bool = True) -> dict[str, Any]:
    import torch

    base_threads = torch.get_num_threads()
    base_tps, base_text = _speed(engine, tokens)
    out: dict[str, Any] = {"device": device, "tokens_per_second": round(base_tps, 2), "threads": base_threads,
                           "tried": {str(base_threads): round(base_tps, 2)}, "tuned": False}
    try:
        import resource

        out["peak_rss_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:  # noqa: BLE001 — not available on Windows
        pass
    if device != "cpu" or not tune_threads:
        return out
    cores = os.cpu_count() or 1
    candidates = sorted({n for n in (1, 2, 4, max(1, cores // 2), cores) if 1 <= n <= cores and n != base_threads})
    best_n, best_tps = base_threads, base_tps
    try:
        for n in candidates:
            torch.set_num_threads(n)
            tps, text = _speed(engine, tokens)
            out["tried"][str(n)] = round(tps, 2)
            if text == base_text and tps > best_tps:  # identical output: quality unchanged
                best_n, best_tps = n, tps
    finally:
        keep = best_n != base_threads and best_tps >= base_tps * (1 + MIN_GAIN)
        torch.set_num_threads(best_n if keep else base_threads)
    if keep:
        out.update(threads=best_n, tokens_per_second=round(best_tps, 2), tuned=True,
                   gain=round(best_tps / base_tps - 1, 3) if base_tps else None)
    return out
