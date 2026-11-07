"""Weakness detection: which capabilities MOTH is worst at, from measurements only.

Inputs are the capability benchmark reports stored for a model version (``capability:<cap>:…`` suites,
run on held-out data that is never trained on), the same reports of the model's parent (to find
regressions), and recurring problems in user feedback. Each capability gets a weakness score in 0..1:

* benchmark: ``1 − (value − floor) / (target − floor)`` clipped, where ``floor`` is chance level and
  ``target`` the level this model size should reach next (both listed in ``TARGETS``);
* a regression against the parent beyond the tolerance raises the score and is flagged;
* a feedback negative-rate above 30% (with at least 5 ratings) raises the score.

The ranked result drives the curriculum's mixture weights and the planner's recommendations.
Capabilities without a measurement are reported as "not measured" — never guessed.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import evaluation_reports

# floor (chance / untrained) and next target for a small model; held-out loss is relative to the parent
TARGETS: dict[str, tuple[float, float]] = {
    "math": (0.0, 0.2), "reasoning": (0.25, 0.5), "code": (0.0, 0.15), "instruction": (0.0, 0.8),
    "safety": (0.0, 0.95),
}
# which Data Factory domains train a capability
DOMAINS = {"math": ["math"], "reasoning": ["reasoning", "knowledge"], "code": ["code"],
           "instruction": ["conversation", "writing"], "safety": ["conversation"],
           "language": ["language"], "knowledge": ["knowledge"], "conversation": ["conversation"],
           "writing": ["writing"]}
REGRESSION_TOLERANCE = 0.02


def capability_reports(ctx: Ctx, version: int | None) -> dict[str, dict[str, Any]]:
    """``{capability or holdout_<domain>: metrics}`` of the latest report per suite of a version."""
    if version is None:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for r in ctx.db.all(select(evaluation_reports).where(evaluation_reports.c.model_version == version)
                        .order_by(evaluation_reports.c.id)):
        if not r["suite"].startswith("capability:"):
            continue
        parts = r["suite"].split(":")
        cap = parts[1] if parts[1] != "holdout" else f"holdout_{parts[2]}"
        m = json.loads(r["metrics"])
        if m.get("ok"):
            out[cap] = m
    return out


def analyse(ctx: Ctx, version: int | None, parent: int | None = None,
            feedback_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    cur = capability_reports(ctx, version)
    par = capability_reports(ctx, parent) if parent else {}
    rows = []
    for cap, m in cur.items():
        row: dict[str, Any] = {"capability": cap, "value": m["value"], "metric": m.get("metric"),
                               "higher_is_better": bool(m.get("higher_is_better"))}
        if cap in TARGETS:
            floor, target = TARGETS[cap]
            row["weakness"] = round(max(0.0, min(1.0, 1 - (m["value"] - floor) / (target - floor))), 3)
            row["target"] = target
        else:
            row["weakness"] = None  # held-out loss: only meaningful relative to the parent
        p = par.get(cap)
        if p:
            delta = m["value"] - p["value"]
            rel = delta / max(1e-9, abs(p["value"]))
            worse = rel < -REGRESSION_TOLERANCE if row["higher_is_better"] else rel > REGRESSION_TOLERANCE
            row["parent_value"] = p["value"]
            row["change"] = round(delta, 4)
            if worse:
                row["regression"] = True
                row["weakness"] = round(min(1.0, (row["weakness"] or 0.5) + 0.3), 3)
        rows.append(row)
    for w in (feedback_summary or {}).get("recurring_weaknesses", []):
        cap = w["capability"]
        hit = next((r for r in rows if r["capability"] == cap), None)
        if hit is None:
            hit = {"capability": cap, "value": None, "metric": "feedback", "weakness": 0.0, "higher_is_better": True}
            rows.append(hit)
        hit["feedback_negative_rate"] = w["negative_rate"]
        hit["weakness"] = round(min(1.0, (hit["weakness"] or 0.0) + 0.5 * w["negative_rate"]), 3)
    ranked = sorted([r for r in rows if r.get("weakness") is not None], key=lambda r: -r["weakness"])
    measured = {r["capability"] for r in rows}
    not_measured = [c for c in ("math", "reasoning", "code", "instruction", "safety") if c not in measured]
    return {"version": version, "parent": parent, "capabilities": rows, "ranked": ranked,
            "regressions": [r for r in rows if r.get("regression")], "not_measured": not_measured,
            "recommendations": recommend(ranked)}


def recommend(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for r in ranked[:3]:
        if (r.get("weakness") or 0) < 0.2:
            continue
        doms = DOMAINS.get(r["capability"], [])
        why = "regressed against the previous version" if r.get("regression") else (
            f"scores {r['value']:.0%} against a target of {r['target']:.0%}" if r.get("target") is not None and
            r.get("value") is not None else "users report problems")
        out.append({"capability": r["capability"], "priority": r["weakness"], "domains": doms,
                    "action": f"Continue training with more {', '.join(doms) or r['capability']} data",
                    "reason": f"{r['capability'].capitalize()} {why}."})
    return out


def mixture_weakness(analysis: dict[str, Any]) -> dict[str, float]:
    """Weakness per Data Factory domain (max over the capabilities a domain trains)."""
    out: dict[str, float] = {}
    for r in analysis["ranked"]:
        for d in DOMAINS.get(r["capability"], []):
            out[d] = max(out.get(d, 0.0), float(r["weakness"] or 0.0))
    return out
