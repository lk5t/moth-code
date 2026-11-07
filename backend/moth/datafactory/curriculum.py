"""The MOTH learning curriculum: which capabilities to train, in what proportion.

Stages run in order and each builds on the previous checkpoint (never from scratch):

1. ``foundation`` — language fundamentals and world knowledge dominate, with some code and chat so the
   chat format is learned early.
2. ``conversation`` — instruction following and dialogue, with replay of earlier domains.
3. ``skills`` — maths, reasoning and code.
4. ``balanced`` — the steady state used by Evolution: weights follow measured weaknesses.

``plan_mixture`` turns stage priorities into sampling weights for a token budget. It caps how many
times any domain is repeated (``max_epochs``) so a small dataset is not memorised, keeps a replay
floor for every domain already learned (to reduce forgetting), and shifts weight toward domains whose
benchmark scores are weakest when ``weakness`` is given (0 = fine, 1 = very weak).
"""

from __future__ import annotations

from typing import Any

STAGES: list[dict[str, Any]] = [
    {"id": "foundation", "name": "Foundation: language and knowledge",
     "priorities": {"language": 0.30, "knowledge": 0.28, "code": 0.14, "conversation": 0.12, "writing": 0.05,
                    "math": 0.06, "reasoning": 0.05}},
    {"id": "conversation", "name": "Conversation and instructions",
     "priorities": {"conversation": 0.35, "writing": 0.12, "knowledge": 0.15, "language": 0.12, "code": 0.1,
                    "math": 0.08, "reasoning": 0.08}},
    {"id": "skills", "name": "Maths, reasoning and code",
     "priorities": {"code": 0.28, "math": 0.2, "reasoning": 0.17, "conversation": 0.15, "knowledge": 0.1,
                    "language": 0.06, "writing": 0.04}},
    {"id": "balanced", "name": "Balanced improvement",
     "priorities": {"conversation": 0.2, "code": 0.18, "knowledge": 0.16, "language": 0.12, "math": 0.12,
                    "reasoning": 0.12, "writing": 0.1}},
]

REPLAY_FLOOR = 0.03  # every learned domain keeps at least this share (memory protection)


def stage(stage_id: str) -> dict[str, Any]:
    for s in STAGES:
        if s["id"] == stage_id:
            return s
    raise KeyError(stage_id)


def next_stage(stage_id: str | None) -> str:
    ids = [s["id"] for s in STAGES]
    if stage_id not in ids:
        return ids[0]
    return ids[min(len(ids) - 1, ids.index(stage_id) + 1)]


def plan_mixture(domain_tokens: dict[str, int], budget_tokens: int, stage_id: str = "foundation",
                 weakness: dict[str, float] | None = None, max_epochs: float = 4.0,
                 learned: set[str] | None = None) -> dict[str, Any]:
    pri = dict(stage(stage_id)["priorities"])
    for d, w in (weakness or {}).items():
        if d in pri:
            pri[d] *= 1.0 + 1.5 * max(0.0, min(1.0, w))  # weak skills get up to 2.5× more attention
    avail = {d: n for d, n in domain_tokens.items() if n > 0 and d in pri}
    for d in learned or set():
        if d in avail:
            pri[d] = max(pri[d], REPLAY_FLOOR)
    weights = {d: pri[d] for d in avail}
    # water-filling: cap each domain at max_epochs passes and give the excess to the others
    capped: dict[str, float] = {}
    for _ in range(len(weights) + 1):
        free = {d: w for d, w in weights.items() if d not in capped}
        if not free:
            break
        remaining = 1.0 - sum(capped.values())
        total = sum(free.values())
        changed = False
        for d, w in free.items():
            share = remaining * w / total
            cap = domain_tokens[d] * max_epochs / max(1, budget_tokens)
            if share > cap:
                capped[d] = cap
                changed = True
        if not changed:
            for d, w in free.items():
                capped[d] = remaining * w / total
            break
    s = sum(capped.values()) or 1.0
    final = {d: round(w / s, 5) for d, w in sorted(capped.items())}
    epochs = {d: round(final[d] * budget_tokens / max(1, domain_tokens[d]), 2) for d in final}
    return {"stage": stage_id, "weights": final, "expected_epochs": epochs, "budget_tokens": budget_tokens,
            "max_epochs": max_epochs}
