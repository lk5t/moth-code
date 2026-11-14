"""Measure how fast this machine really trains a model shape (0.10.0).

The "6 × parameters × tokens" compute rule is far off for small models, where memory traffic and
per-layer overhead dominate (MOTH's first successor trained 3.5× faster than it predicted). Before
MOTH picks a successor's size it trains each candidate shape for a few steps on random tokens and
times it, so the choice rests on measured speed.
"""

from __future__ import annotations

import time
from typing import Any


def measure(model_config: dict[str, Any], seq_len: int, batch_size: int = 1, steps: int = 2,
            device: str = "cpu") -> float:
    """Training tokens per second for this shape (forward, backward and optimizer step)."""
    import torch

    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    cfg = MothConfig.from_dict(model_config)
    seq = max(8, min(int(seq_len), cfg.max_seq_len))
    torch.manual_seed(0)
    model = MothModel(cfg).to(device)
    model.train()
    opt = model.configure_optimizer(1e-3, 0.0, device_type=device)
    x = torch.randint(0, cfg.vocab_size, (batch_size, seq), device=device)
    y = torch.randint(0, cfg.vocab_size, (batch_size, seq), device=device)

    def step() -> None:
        _, loss = model(x, y)
        loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)

    step()  # warm-up: allocation and first-call overhead are not part of the speed
    t0 = time.perf_counter()
    for _ in range(max(1, steps)):
        step()
    seconds = max(1e-6, time.perf_counter() - t0)
    del model, opt
    return batch_size * seq * max(1, steps) / seconds
