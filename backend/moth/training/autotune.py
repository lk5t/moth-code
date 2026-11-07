"""Bounded, real forward/backward batch probes; never take an optimizer step.

Only divisors of the requested microbatch are tried. Accumulation preserves the exact
number of examples per optimizer step, so tuning cannot enlarge a compute budget.
"""
from __future__ import annotations

import gc
import os
import time
from pathlib import Path

import torch


def tune_batch(model, batch, accumulation, sample, device, amp_dtype=None, max_trials=4, seq_len=None):
    if batch < 1 or accumulation < 1:
        raise ValueError("batch size and accumulation must be positive")
    effective = batch * accumulation
    max_trials = max(2, int(max_trials))
    divisors = [b for b in range(1, batch + 1) if batch % b == 0]
    # Always try the safest batch, then progressively larger alternatives, up to the request.
    if len(divisors) > max_trials:
        divisors = sorted({divisors[round(i * (len(divisors) - 1) / (max_trials - 1))]
                           for i in range(max_trials)})
    trials = []
    training = model.training
    devices = [torch.device(device).index or 0] if str(device).startswith("cuda") else []
    try:
        with torch.random.fork_rng(devices=devices):
            model.train()
            for micro in divisors:
                try:
                    # Reserve room for lazy AdamW moments/gradients, not just this probe's activations.
                    if devices:
                        free, total = torch.cuda.mem_get_info()
                        read_fraction = getattr(torch.cuda, "get_per_process_memory_fraction", None)
                        fraction = read_fraction() if read_fraction else 1.0
                        available = min(free, total * fraction - torch.cuda.memory_allocated())
                    else:
                        available = os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else None
                        try:
                            cap = Path("/sys/fs/cgroup/memory.max").read_text().strip()
                            if cap != "max":
                                remaining = int(cap) - int(Path("/sys/fs/cgroup/memory.current").read_text())
                                available = min(available, remaining) if available is not None else remaining
                        except (OSError, ValueError):
                            pass
                    params = sum(p.numel() for p in model.parameters())
                    c = model.cfg
                    needed = params * 12 + micro * (seq_len or c.max_seq_len) * (c.d_model * c.n_layers * 136 + c.vocab_size * 4)
                    if available is not None and needed > available * 0.8:
                        trials.append({"batch_size": micro, "ok": False, "reason": "memory reserve"})
                        break
                    # Each probe gets its own fixed sample; the real sampler is never consumed.
                    x, y, mask = sample(micro)
                    if devices:
                        torch.cuda.synchronize()
                        torch.cuda.reset_peak_memory_stats()
                    elapsed = []
                    for repeat in range(3):  # warm-up, then two timed backward passes
                        model.zero_grad(set_to_none=True)
                        t0 = time.perf_counter()
                        with torch.autocast(str(device).split(":")[0], dtype=amp_dtype,
                                            enabled=amp_dtype is not None):
                            _, loss = model(x, y, loss_mask=mask)
                        if not torch.isfinite(loss):
                            raise FloatingPointError("autotuning encountered a non-finite loss")
                        loss.backward()
                        if devices:
                            torch.cuda.synchronize()
                        if repeat:
                            elapsed.append(time.perf_counter() - t0)
                    seconds = sum(elapsed) / len(elapsed)
                    trials.append({"batch_size": micro, "ok": True, "seconds": seconds,
                                   "tokens_per_second": x.numel() / max(seconds, 1e-9),
                                   "peak_cuda_bytes": torch.cuda.max_memory_allocated() if devices else None})
                except (torch.cuda.OutOfMemoryError, MemoryError):
                    trials.append({"batch_size": micro, "ok": False, "reason": "out of memory"})
                    break
                finally:
                    model.zero_grad(set_to_none=True)
                    x = y = mask = loss = None
                    gc.collect()
                    if devices:
                        torch.cuda.empty_cache()
    finally:
        model.train(training)
    successful = [t for t in trials if t["ok"]]
    if not successful:
        raise RuntimeError("no microbatch fits; reduce sequence length or model size")
    best = max(successful, key=lambda t: t["tokens_per_second"])
    return {"batch_size": best["batch_size"], "grad_accum": effective // best["batch_size"],
            "effective_batch_size": effective, "trials": trials}
