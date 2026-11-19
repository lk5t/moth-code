"""2.1 promotion rule: better overall and nothing broken. Small drops in one area are trade-offs, not vetoes."""
import pytest

from moth_server import models as M
from moth_server.evolution import evaluation as EV
from moth_server.evolution import settings as S

SUITES = [
    {"id": "retention:target0000000000", "kind": "heldout", "name": "training data"},
    {"id": "heldout:general", "kind": "heldout", "name": "general text"},
    {"id": "capability:dialogue:builtin", "kind": "capability", "capability": "dialogue", "name": "Conversation"},
    {"id": "capability:codegen:builtin", "kind": "capability", "capability": "codegen", "name": "Code generation"},
    {"id": "capability:codegen_js:builtin", "kind": "capability", "capability": "codegen_js", "name": "JavaScript"},
]


def loss(v):
    return {"ok": True, "value": v, "higher_is_better": False}


def acc(v, n=40):
    return {"ok": True, "value": v, "higher_is_better": True, "n": n}


BASE = {"retention:target0000000000": loss(3.00), "heldout:general": loss(3.20),
        "capability:dialogue:builtin": acc(0.50), "capability:codegen:builtin": acc(0.40), "capability:codegen_js:builtin": acc(0.30)}


def run(monkeypatch, cand, general=None, settings=None):
    monkeypatch.setattr(EV, "build_suites", lambda ctx, rel: SUITES)
    monkeypatch.setattr(EV, "_prescreen", lambda *a, **k: None)
    perf = {"tokens_per_second": 50.0, "peak_memory_bytes": 100}
    monkeypatch.setattr(EV, "benchmark", lambda ctx, version, path, suites: {"suites": BASE if version == 1 else cand, "performance": perf})
    ev = {"score": {"value": 3.0}, "baseline": {"score": {"value": 3.0}}}
    status = "published"
    if general is not None:  # candidate scores worse than the deployed model on the general evaluation text
        ev = {"score": {"value": 3.0 * (1 + general)}, "baseline": {"score": {"value": 3.0}}, "reason": "regression"}
        status = "evaluated"
    monkeypatch.setattr(M, "evaluate", lambda ctx, v: {"status": status, "evaluation": ev})
    base = {"version": 1, "path": "/b", "info": {}}
    cand_rel = {"version": 2, "path": "/c", "info": {}}
    return EV.gate(None, cand_rel, base, {"sha256": "target0000000000xx"}, settings or S.DEFAULTS)


def test_better_overall_with_a_small_drop_is_promoted(monkeypatch):
    cand = {**BASE, "retention:target0000000000": loss(2.85), "heldout:general": loss(3.10),
            "capability:dialogue:builtin": acc(0.55), "capability:codegen:builtin": acc(0.46),
            "capability:codegen_js:builtin": acc(0.25)}  # JavaScript dipped 5 points: within noise
    v = run(monkeypatch, cand)
    assert v["passed"], [g for g in v["gates"] if not g["passed"]]
    assert "JavaScript" in v["trade_offs"] and v["decision"].startswith("promoted")


def test_slightly_worse_on_general_text_no_longer_blocks(monkeypatch):
    cand = {**BASE, "retention:target0000000000": loss(2.80), "capability:dialogue:builtin": acc(0.56),
            "capability:codegen:builtin": acc(0.45)}
    v = run(monkeypatch, cand, general=0.03)  # 3 % worse on the general text (blocked before 2.1)
    g = {x["gate"]: x for x in v["gates"]}
    assert v["passed"] and g["release_checks"]["passed"] and g["release_checks"]["trade_off"]


def test_a_collapse_still_blocks(monkeypatch):
    cand = {**BASE, "retention:target0000000000": loss(2.50), "heldout:general": loss(4.30)}  # 34 % worse
    v = run(monkeypatch, cand)
    assert not v["passed"] and "heldout:general" in v["decision"]


def test_a_whole_skill_getting_much_worse_still_blocks(monkeypatch):
    cand = {**BASE, "retention:target0000000000": loss(2.70), "capability:codegen:builtin": acc(0.27, n=400),
            "capability:codegen_js:builtin": acc(0.20, n=400)}  # coding as a whole −11.5 points
    v = run(monkeypatch, cand)
    assert not v["passed"] and "balanced_capabilities" in v["decision"]


def test_not_better_overall_is_not_promoted(monkeypatch):
    v = run(monkeypatch, dict(BASE))
    assert not v["passed"] and "overall_improvement" in v["decision"]


def test_settings_migration_moves_old_defaults_once(client):
    ctx = client.app.state.ctx
    ctx.db.set_config(S.MIGRATION_V21, None)
    ctx.db.set_config(S.KEY, {"gates": {"min_improvement": 0.005, "max_regression": 0.10, "code_tolerance": 0.05}})
    assert S.migrate_v21(ctx)
    g = S.get(ctx)["gates"]
    assert g["min_improvement"] == 0.002 and "max_regression" not in (ctx.db.get_config(S.KEY)["gates"])
    S.update(ctx, {"gates": {"min_improvement": 0.01}}) if hasattr(S, "update") else None
    assert not S.migrate_v21(ctx)  # once only
