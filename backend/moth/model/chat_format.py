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


def _first_sentence(text: str, limit: int) -> str:
    t = " ".join(text.split())
    for end in (". ", "! ", "? ", "\n"):
        i = t.find(end)
        if 0 < i < limit:
            return t[: i + 1]
    return t[:limit] + ("…" if len(t) > limit else "")


def compact(tok: Tokenizer, messages: list[Message], budget: int) -> tuple[list[Message], bool]:
    """1.0 compaction: fit a long conversation into ``budget`` tokens without cutting messages in half.

    System messages and the most recent turns are kept word for word (as many as fit in about 70 % of the
    budget, always the last user message); everything older is replaced by one short system note that
    summarises it ("Earlier in this conversation: the user asked …; MOTH answered …"). Returns the messages
    and whether anything was compacted."""
    def size(ms: list[Message]) -> int:
        return len(encode_chat(tok, ms, add_generation_prompt=True)[0])

    if size(messages) <= budget:
        return messages, False
    system = [m for m in messages if m.role == "system"]
    turns = [m for m in messages if m.role != "system"]
    keep: list[Message] = []
    room = int(budget * 0.7) - size(system)
    for m in reversed(turns):
        if keep and size(system + [m] + keep) > room + size(system):
            break
        keep.insert(0, m)
    older = turns[: len(turns) - len(keep)]
    if not older:  # a single message larger than the budget: keep its end
        last = keep[-1]
        ids = tok.encode(last.content)[-max(16, budget - size(system) - 8):]
        return system + [Message(last.role, tok.decode(ids))], True
    who = {"user": "the user asked", "assistant": "MOTH answered", "tool_call": "MOTH used a tool",
           "tool_result": "the tool returned"}
    notes = [f"{who.get(m.role, m.role)}: {_first_sentence(m.content, 140)}" for m in older]
    while notes:
        note = Message("system", "Earlier in this conversation (summarised): " + " · ".join(notes))
        if size(system + [note] + keep) <= budget:
            return system + [note] + keep, True
        notes.pop(0)  # drop the oldest notes first
    return system + keep, True
