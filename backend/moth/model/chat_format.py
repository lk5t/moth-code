"""Conversation → token layout shared by training (SFT) and inference.

    <|bos|><|system|>…<|end|><|user|>…<|end|><|assistant|>…<|end|>…
"""

from __future__ import annotations

from dataclasses import dataclass

from moth.model.tokenizer import Tokenizer

ROLE_TOKENS = {"system": "<|system|>", "user": "<|user|>", "assistant": "<|assistant|>",
               "tool_call": "<|tool_call|>", "tool_result": "<|tool_result|>"}


@dataclass
class Message:
    role: str
    content: str
    # Only text MOTH Code itself constructs may contain special tokens. File contents,
    # tool output and user text are always encoded as plain bytes (no token injection).
    allow_special: bool = False


def encode_chat(tok: Tokenizer, messages: list[Message], add_generation_prompt: bool = True,
                train_on: tuple[str, ...] = ("assistant", "tool_call")) -> tuple[list[int], list[int]]:
    """Return (ids, loss_mask). ``loss_mask`` is 1 on tokens the model should learn to produce."""
    ids = [tok.bos_id]
    mask = [0]
    for m in messages:
        role_id = tok.token_id(ROLE_TOKENS[m.role])
        body = tok.encode(m.content, allow_special=m.allow_special) + [tok.end_id]
        learn = 1 if m.role in train_on else 0
        ids += [role_id] + body
        mask += [0] + [learn] * len(body)
    if add_generation_prompt:
        ids.append(tok.token_id("<|assistant|>"))
        mask.append(0)
    return ids, mask
