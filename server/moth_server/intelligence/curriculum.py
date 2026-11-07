"""The MOTH learning curriculum on MOTH Cloud: current stage, progress by capability, next mixture.

The stage order and mixture rules live in ``moth.datafactory.curriculum``. Here the server keeps the
lineage's position (``config.curriculum``), measures progress per capability across model versions, and
plans the next training mixture from the latest library build and the weakness analysis. A stage ends
when its token budget is spent or when held-out loss stops improving (plateau); then the next stage
starts, and earlier domains stay in the mixture as replay.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from moth_server.context import Ctx

STAGE_BUDGET_TOKENS = {"foundation": 50_000_000, "conversation": 20_000_000, "skills": 20_000_000}
PLATEAU = 0.01  # < 1% held-out improvement over the last two promotions


def state(ctx: Ctx) -> dict[str, Any]:
    return ctx.db.get_config("curriculum", None) or {"stage": "foundation", "stage_tokens": 0, "history": []}


def save(ctx: Ctx, st: dict[str, Any]) -> None:
    ctx.db.set_config("curriculum", st)


def record_training(ctx: Ctx, tokens: int, holdout_loss: float | None, version: int | None) -> dict[str, Any]:
    """Called after a promoted training cycle: count tokens, detect plateaus, advance the stage."""
    from moth.datafactory.curriculum import next_stage

    st = state(ctx)
    st["stage_tokens"] = int(st.get("stage_tokens", 0)) + int(tokens)
    st.setdefault("losses", []).append({"version": version, "loss": holdout_loss, "stage": st["stage"]})
    st["losses"] = st["losses"][-20:]
    recent = [x["loss"] for x in st["losses"] if x["stage"] == st["stage"] and x["loss"] is not None][-3:]
    plateau = len(recent) == 3 and (recent[0] - recent[-1]) / max(1e-9, recent[0]) < PLATEAU
    budget = STAGE_BUDGET_TOKENS.get(st["stage"])
    if st["stage"] != "balanced" and (plateau or (budget and st["stage_tokens"] >= budget)):
        nxt = next_stage(st["stage"])
        st.setdefault("history", []).append({"stage": st["stage"], "tokens": st["stage_tokens"],
                                             "ended_by": "plateau" if plateau else "budget", "version": version})
        st["stage"], st["stage_tokens"] = nxt, 0
    save(ctx, st)
    return st


def domain_tokens(ctx: Ctx) -> dict[str, int]:
    from moth_server.intelligence import library

    b = library.latest_ready(ctx)
    if not b or not b["path"]:
        return {}
    mix = Path(b["path"]) / "tokens" / "mixture.json"
    if not mix.exists():
        return {}
    return {d: v["tokens"]["train"] for d, v in json.loads(mix.read_text())["domains"].items()}


def plan(ctx: Ctx, budget_tokens: int, analysis: dict[str, Any] | None = None) -> dict[str, Any]:
    from moth.datafactory.curriculum import plan_mixture

    from moth_server.intelligence.weakness import mixture_weakness

    toks = domain_tokens(ctx)
    st = state(ctx)
    if not toks:
        return {"stage": st["stage"], "weights": {}, "note": "no dataset library build yet"}
    weak = mixture_weakness(analysis) if analysis else {}
    learned = {d for x in st.get("history", []) for d in toks}  # replay floor once a stage has completed
    return plan_mixture(toks, budget_tokens, st["stage"], weakness=weak, learned=learned)


def progress(ctx: Ctx, versions: list[int]) -> dict[str, Any]:
    """Capability measurements across lineage versions (oldest first): the learning curve per skill."""
    from moth_server.intelligence.weakness import capability_reports

    curve: dict[str, list[dict[str, Any]]] = {}
    for v in versions:
        for cap, m in capability_reports(ctx, v).items():
            curve.setdefault(cap, []).append({"version": v, "value": m["value"], "metric": m.get("metric"),
                                              "higher_is_better": m.get("higher_is_better")})
    st = state(ctx)
    return {"stage": st["stage"], "stage_tokens": st.get("stage_tokens", 0),
            "stage_budget": STAGE_BUDGET_TOKENS.get(st["stage"]), "history": st.get("history", []),
            "capabilities": curve}
