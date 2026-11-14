"""The morning report (0.10.0): what MOTH did while the Owner was away, in a few plain lines.

Built from what was recorded (Evolution events, experiments, the self-quiz and the deployed model), so
nothing in it is estimated. The deployed model's answer to the same question is kept with each report,
so the next one can show "then" next to "now".
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx

KEY = "morning_report"
QUESTION = "Hello! What can you help me with today?"
DEFAULT_HOURS = 12.0


def _sample(ctx: Ctx) -> str | None:
    engine = ctx.extras.get("inference_engine")
    if engine is None or not getattr(engine, "manifest", None):
        return None
    from moth.model.chat_format import Message
    from moth.model.generation import GenerationParams

    parts: list[str] = []
    try:
        engine.chat([Message("user", QUESTION)], GenerationParams(max_new_tokens=60, temperature=0.0, seed=0),
                    parts.append, threading.Event())
    except Exception:  # noqa: BLE001 — a report never fails because the model could not answer
        return None
    return "".join(parts).strip()[:400] or None


def build(ctx: Ctx, since: float | None = None) -> dict[str, Any]:
    from moth_server import models as M
    from moth_server.db import evolution_events, evolution_experiments
    from moth_server.intelligence import self_training

    now = time.time()
    since = float(since) if since else now - DEFAULT_HOURS * 3600
    events = [dict(r) for r in ctx.db.all(select(evolution_events).where(evolution_events.c.ts >= since)
                                          .order_by(evolution_events.c.ts))]
    exps = [dict(r) for r in ctx.db.all(select(evolution_experiments).where(evolution_experiments.c.updated_at >= since))]
    kinds: dict[str, int] = {}
    for e in events:
        kinds[e["kind"]] = kinds.get(e["kind"], 0) + 1
    finished = [e for e in exps if e["status"] in ("passed", "rejected", "deployed", "failed")]
    tokens = 0
    for e in exps:
        try:
            tokens += int((json.loads(e["metrics"] or "{}")).get("tokens") or 0)
        except (TypeError, ValueError):
            pass
    promoted = [e for e in events if e["kind"] in ("deploy.done", "deploy.verified")]
    deployed = M.deployed(ctx)
    quiz = self_training.state(ctx).get("history") or []
    quiz_now = [q for q in quiz if float(q.get("at") or 0) >= since]

    def rate(q: dict) -> float:
        k = q.get("kinds") or {}
        tried = sum(int(v.get("tried") or 0) for v in k.values())
        return sum(int(v.get("correct") or 0) for v in k.values()) / max(1, tried)

    previous = ctx.db.get_config(KEY, None) or {}
    answer = _sample(ctx)
    highlights: list[str] = []
    hours = max(1.0, (now - since) / 3600)
    if promoted:
        highlights.append(f"MOTH got a new brain: promoted {len(promoted)} time(s) after passing every check.")
    if finished:
        passed = sum(1 for e in finished if e["status"] in ("passed", "deployed"))
        highlights.append(f"Tried {len(finished)} training experiment(s); {passed} beat the current model.")
    if tokens:
        highlights.append(f"Read {tokens:,} tokens of training data.")
    if kinds.get("distributed.round"):
        highlights.append(f"Trained together with the workers in {kinds['distributed.round']} shared round(s).")
    if kinds.get("data.prepared"):
        highlights.append("Prepared fresh training data.")
    if quiz_now:
        highlights.append(f"Quizzed itself {len(quiz_now)} time(s); latest score {rate(quiz_now[-1]):.0%} correct"
                          + (f" (was {rate(quiz_now[0]):.0%})" if len(quiz_now) > 1 else "") + ".")
    if kinds.get("supervisor.repaired"):
        highlights.append(f"Fixed {kinds['supervisor.repaired']} problem(s) by itself.")
    problems = [e["message"] for e in events if e["level"] == "error"][-3:]
    if not highlights:
        highlights.append("A quiet night: nothing new finished training.")
    report = {"at": now, "since": since, "hours": round(hours, 1), "highlights": highlights, "problems": problems,
              "events": len(events), "experiments_finished": len(finished), "tokens": tokens,
              "promotions": len(promoted),
              "model": {"version": deployed["version"] if deployed else None,
                        "name": (deployed or {}).get("info", {}).get("display_name") if deployed else None,
                        "params": (deployed or {}).get("info", {}).get("params") if deployed else None},
              "question": QUESTION, "answer_now": answer,
              "answer_before": previous.get("answer_now"), "answer_before_at": previous.get("at")}
    if answer and now - float(previous.get("at") or 0) > 6 * 3600:  # "before" stays a real earlier answer
        ctx.db.set_config(KEY, {"at": now, "answer_now": answer, "version": report["model"]["version"]})
    return report
