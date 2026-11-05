"""Autoregressive sampling from MOTH with a KV cache, streaming and cancellation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Iterator

import torch

from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel


@dataclass
class GenerationParams:
    max_new_tokens: int = 256
    temperature: float = 0.8
    top_k: int = 50
    top_p: float = 0.95
    repetition_penalty: float = 1.1
    seed: int | None = None
    stop_strings: list[str] = field(default_factory=list)
    include_special: bool = False  # keep special tokens (e.g. <|tool_call|>) in the decoded text

    @classmethod
    def from_dict(cls, d: dict | None) -> "GenerationParams":
        d = d or {}
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class GenerationStats:
    prompt_tokens: int = 0
    generated_tokens: int = 0
    seconds: float = 0.0
    stop_reason: str = ""  # eos | stop_string | max_tokens | context | cancelled

    @property
    def tokens_per_sec(self) -> float:
        return self.generated_tokens / self.seconds if self.seconds > 0 else 0.0


def sample_next(logits: torch.Tensor, params: GenerationParams, history: torch.Tensor | None,
                generator: torch.Generator | None) -> int:
    logits = logits.float().clone()
    if params.repetition_penalty != 1.0 and history is not None and history.numel():
        prev = torch.unique(history)
        vals = logits[prev]
        logits[prev] = torch.where(vals > 0, vals / params.repetition_penalty, vals * params.repetition_penalty)
    if params.temperature <= 0:
        return int(torch.argmax(logits))
    logits = logits / params.temperature
    if params.top_k and params.top_k < logits.numel():
        kth = torch.topk(logits, params.top_k).values[-1]
        logits[logits < kth] = float("-inf")
    probs = torch.softmax(logits, dim=-1)
    if 0 < params.top_p < 1.0:
        sorted_probs, sorted_idx = torch.sort(probs, descending=True)
        cum = torch.cumsum(sorted_probs, dim=-1)
        cutoff = cum - sorted_probs > params.top_p
        sorted_probs[cutoff] = 0.0
        probs = torch.zeros_like(probs).scatter_(0, sorted_idx, sorted_probs)
        probs = probs / probs.sum()
    return int(torch.multinomial(probs, 1, generator=generator))


@torch.no_grad()
def generate_stream(
    model: MothModel,
    tokenizer: Tokenizer,
    prompt_ids: list[int],
    params: GenerationParams,
    stop_ids: set[int] | None = None,
    cancel_event: threading.Event | None = None,
    stats: GenerationStats | None = None,
) -> Iterator[str]:
    """Yield decoded text increments as the model generates them."""
    stats = stats if stats is not None else GenerationStats()
    stop_ids = stop_ids if stop_ids is not None else {tokenizer.eos_id, tokenizer.end_id}
    device = next(model.parameters()).device
    model.eval()
    ctx = model.cfg.max_seq_len
    # Keep the most recent context if the prompt is too long, leaving room to generate.
    budget = max(1, ctx - min(params.max_new_tokens, ctx // 2))
    if len(prompt_ids) > budget:
        prompt_ids = prompt_ids[-budget:]
    stats.prompt_tokens = len(prompt_ids)
    gen = None
    if params.seed is not None:
        gen = torch.Generator(device="cpu").manual_seed(params.seed)
    start = time.time()
    cache = model.new_cache()
    idx = torch.tensor([prompt_ids], dtype=torch.long, device=device)
    logits, _ = model(idx, cache=cache, start_pos=0)
    pos = len(prompt_ids)
    history = list(prompt_ids)
    out_ids: list[int] = []
    emitted = ""
    stats.stop_reason = "max_tokens"
    for _ in range(params.max_new_tokens):
        if cancel_event is not None and cancel_event.is_set():
            stats.stop_reason = "cancelled"
            break
        hist = torch.tensor(history[-256:], dtype=torch.long)
        nxt = sample_next(logits[0, -1].cpu(), params, hist, gen)
        if nxt in stop_ids:
            stats.stop_reason = "eos"
            break
        out_ids.append(nxt)
        history.append(nxt)
        stats.generated_tokens += 1
        text = tokenizer.decode(out_ids, skip_special=not params.include_special)
        # Hold back incomplete UTF-8 sequences (decoded as U+FFFD at the end).
        if not text.endswith("�"):
            hit = next((s for s in params.stop_strings if s and s in text), None)
            if hit:
                text = text[: text.index(hit)]
                if len(text) > len(emitted):
                    yield text[len(emitted):]
                emitted = text
                stats.stop_reason = "stop_string"
                break
            if len(text) > len(emitted):
                yield text[len(emitted):]
                emitted = text
        if pos >= ctx:
            stats.stop_reason = "context"
            break
        logits, _ = model(torch.tensor([[nxt]], device=device), cache=cache, start_pos=pos)
        pos += 1
    stats.seconds = time.time() - start


def generate(model: MothModel, tokenizer: Tokenizer, prompt: str, params: GenerationParams | None = None,
             on_text: Callable[[str], None] | None = None) -> tuple[str, GenerationStats]:
    params = params or GenerationParams()
    stats = GenerationStats()
    parts = []
    for piece in generate_stream(model, tokenizer, tokenizer.encode(prompt, allow_special=True), params, stats=stats):
        parts.append(piece)
        if on_text:
            on_text(piece)
    return "".join(parts), stats
