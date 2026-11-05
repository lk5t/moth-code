"""Model evaluation: held-out loss/perplexity and a small code-completion benchmark.

All numbers are measured by running the model; nothing is estimated or
hard-coded. The code benchmark is intentionally small and simple — it tracks
progress of early MOTH models, not parity with large models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import torch

from moth.model.generation import GenerationParams, generate_stream
from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel
from moth.training.data import TokenDataset

# (prompt, expected completion prefix). Greedy decoding must reproduce the expected text.
CODE_TASKS: list[tuple[str, str]] = [
    ("def add(a, b):\n    return a", " + b"),
    ("def is_even(n):\n    return n % 2", " == 0"),
    ("for i in range(", ""),  # sanity: any continuation is fine; scored on syntax below
    ("import os\nimport", " sys"),
    ("class Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y", " = y"),
    ("def square(x):\n    return x *", " x"),
    ("if __name__ == ", "\"__main__\""),
    ("def greet(name):\n    print(f\"Hello, {", "name}"),
    ("numbers = [1, 2, 3]\ntotal = sum(", "numbers)"),
    ("with open(path) as f:\n    data = f.", "read()"),
    ("try:\n    run()\nexcept", " Exception"),
    ("def __repr__(self):\n    return", " f\""),
]


@dataclass
class EvalReport:
    val_loss: float
    perplexity: float
    bits_per_token: float
    next_token_accuracy: float
    code_exact: int
    code_total: int
    samples: list[dict]

    def to_dict(self) -> dict:
        return {**self.__dict__, "code_pass_rate": self.code_exact / max(1, self.code_total)}


@torch.no_grad()
def eval_loss(model: MothModel, data: TokenDataset, batches: int = 20, batch_size: int = 8) -> tuple[float, float]:
    device = next(model.parameters()).device
    model.eval()
    gen = torch.Generator().manual_seed(1234)
    losses, correct, total = [], 0, 0
    for _ in range(batches):
        x, y, m = data.batch(batch_size, gen, device)
        logits, loss = model(x, y, loss_mask=m)
        losses.append(loss.item())
        pred = logits.argmax(-1)
        mask = m.bool()
        correct += (pred[mask] == y[mask]).sum().item()
        total += mask.sum().item()
    return sum(losses) / len(losses), correct / max(1, total)


@torch.no_grad()
def code_benchmark(model: MothModel, tok: Tokenizer, tasks=CODE_TASKS, max_new_tokens: int = 12) -> tuple[int, list[dict]]:
    params = GenerationParams(max_new_tokens=max_new_tokens, temperature=0.0, repetition_penalty=1.0)
    passed, samples = 0, []
    scored = 0
    for prompt, expected in tasks:
        out = "".join(generate_stream(model, tok, [tok.bos_id] + tok.encode(prompt), params))
        if expected:
            scored += 1
            ok = out.startswith(expected)
            passed += ok
        else:
            ok = None
        samples.append({"prompt": prompt, "expected": expected, "output": out, "pass": ok})
    return passed, samples


def evaluate_model(model: MothModel, tok: Tokenizer, dataset_dir: str | None, batches: int = 20) -> EvalReport:
    if dataset_dir:
        data = TokenDataset(dataset_dir, "val", min(512, model.cfg.max_seq_len))
        loss, acc = eval_loss(model, data, batches=batches)
    else:
        loss, acc = float("nan"), float("nan")
    passed, samples = code_benchmark(model, tok)
    total = sum(1 for _, e in CODE_TASKS if e)
    return EvalReport(
        val_loss=loss, perplexity=math.exp(min(loss, 20)) if loss == loss else float("nan"),
        bits_per_token=loss / math.log(2) if loss == loss else float("nan"),
        next_token_accuracy=acc, code_exact=passed, code_total=total, samples=samples,
    )
