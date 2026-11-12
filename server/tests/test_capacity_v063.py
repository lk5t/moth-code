"""0.6.3 capability-based growth: decisions come from measured capabilities, training progress, data
and resources — not from a single loss threshold. The model and its measured size are real (a
registered tiny model); the benchmark histories are supplied per test to exercise each decision."""
import json

import pytest

from conftest import H, make_tiny_model
from moth_server import models as M
from moth_server.evolution import capacity as CAP
from moth_server.evolution import engine as EN
from moth_server.evolution import evaluation as EV
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S
from moth_server.evolution import v2


def acc(*values, n=100):
    """An accuracy history, newest first."""
    return [{"version": 10 - i, "value": v, "n": n, "higher_is_better": True, "failures": None} for i, v in enumerate(values)]


def loss(*values):
    return [{"version": 10 - i, "value": v, "n": 300, "higher_is_better": False, "failures": None} for i, v in enumerate(values)]


@pytest.fixture
def world(client, owner, tmp_path, monkeypatch):
    ctx = client.app.state.ctx
    rel = M._register(ctx, make_tiny_model(tmp_path, 0, "base"), "base", {"type": "upload"}, None)
    base = M.release(ctx, rel["version"])
    params = base["info"]["params_measured"]["total"]
    state = {"history": {}, "evidence": {"recent_improvements": [0.05, 0.04, 0.03], "train_loss": 2.0, "val_loss": 2.1},
             "shares": {"math": 0.1, "code": 0.3, "conversation": 0.3, "language": 0.2, "reasoning": 0.1},
             "tokens": params * 40}
    monkeypatch.setattr(CAP, "capability_history", lambda c, v, w: {k: h[:w] for k, h in state["history"].items()})
    monkeypatch.setattr(v2, "growth_evidence", lambda c, b: state["evidence"])
    monkeypatch.setattr(CAP, "_domain_shares", lambda c: state["shares"])

    def base_now():
        b = M.release(ctx, rel["version"])
        b["info"] = {**b["info"], "lineage_totals": {"tokens": state["tokens"]}}
        return b
    settings = S.get(ctx)
    settings["backends"] = {"local_cpu": True, "local_gpu": False, "workers": True}
    return {"ctx": ctx, "base": base_now, "state": state, "params": params, "settings": settings, "owner": owner}


def test_loss_improving_but_capability_stalled_proposes_a_larger_candidate(world):
    w = world
    w["state"]["history"] = {"math": acc(0.02, 0.02, 0.02), "code": acc(0.0, 0.0, 0.0),
                             "holdout_language": loss(2.10, 2.30, 2.50)}
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["loss_improving"] and d["action"] == "grow" and d["grow"]
    assert set(d["target_capabilities"]) == {"math", "code"}
    assert d["params_before"] == w["params"] and d["params_after"] > w["params"]
    assert d["headline"] == "Current architecture may be limiting progress. Testing a larger candidate."
    assert "while held-out loss still improved" in d["reason"]
    assert d["investigating"] == "Arithmetic remains limited. Evaluating possible causes."
    assert d["estimate"]["memory_bytes"] > 0 and d["estimate"]["fits_server"]
    lang = next(c for c in d["capabilities"] if c["capability"] == "holdout_language")
    assert lang["stalled"] is False and lang["limited"] is None  # a loss has no absolute target


def test_too_little_training_for_the_size_means_train_more_not_grow(world):
    w = world
    w["state"]["history"] = {"math": acc(0.02, 0.02, 0.02)}
    w["state"]["tokens"] = w["params"] * 5
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["action"] == "continue_training" and not d["grow"] and "tokens per parameter" in d["reason"]
    w["state"]["tokens"] = w["params"]
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["action"] == "foundation_training"


def test_overfitting_and_thin_data_point_to_data(world):
    w = world
    w["state"]["history"] = {"math": acc(0.02, 0.02, 0.02)}
    w["state"]["evidence"] = {"recent_improvements": [0.0, 0.0, 0.0], "train_loss": 1.0, "val_loss": 1.6}
    assert CAP.assess(w["ctx"], w["base"](), w["settings"])["action"] == "improve_data"
    w["state"]["evidence"] = {"recent_improvements": [0.0, 0.0, 0.0], "train_loss": 2.0, "val_loss": 2.1}
    w["state"]["shares"] = {"code": 0.99, "math": 0.01}
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["action"] == "improve_data" and "math" in d["reason"]


def test_replies_that_never_end_are_a_format_problem_not_size(world):
    w = world
    hist = acc(0.1, 0.1, 0.1)
    hist[0]["failures"] = {"empty": 1, "no_end": 30, "repetitive": 5}
    w["state"]["history"] = {"instruction": hist}
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["action"] == "adjust_training" and "end on their own" in d["headline"]


def test_improving_capabilities_continue_training(world):
    w = world
    w["state"]["history"] = {"math": acc(0.12, 0.06, 0.02), "reasoning": acc(0.40, 0.33, 0.27, n=200)}
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["action"] == "continue_training" and not d["grow"]
    assert d["headline"].startswith("Capabilities are still improving")


def test_resource_limits_ceiling_and_cooldown_block_growth(world, monkeypatch):
    w = world
    w["state"]["history"] = {"math": acc(0.02, 0.02, 0.02)}
    s = w["settings"]
    from moth_server.evolution import compute as C

    monkeypatch.setattr(C, "estimate_training_memory", lambda *a, **k: 10 ** 15)
    d = CAP.assess(w["ctx"], w["base"](), s)
    assert d["action"] == "continue_training" and "more memory than any available computer" in d["headline"]
    monkeypatch.undo()
    monkeypatch.setattr(CAP, "capability_history", lambda c, v, win: {"math": acc(0.02, 0.02, 0.02)[:win]})
    monkeypatch.setattr(v2, "growth_evidence", lambda c, b: w["state"]["evidence"])
    monkeypatch.setattr(CAP, "_domain_shares", lambda c: w["state"]["shares"])
    s2 = {**s, "growth": {**s["growth"], "max_params": w["params"]}}
    assert "largest size" in CAP.assess(w["ctx"], w["base"](), s2)["headline"]
    s3 = {**s, "growth": {**s["growth"], "enabled": False}}
    assert "turned off" in CAP.assess(w["ctx"], w["base"](), s3)["reason"]
    # a rejected growth candidate in the latest cycle → cooldown
    monkeypatch.setattr(CAP, "growth_attempts", lambda c, limit=200: [
        {"id": 7, "status": "rejected", "cycle_id": 5, "config": {"grow": {}}}])
    monkeypatch.setattr(MEM, "cycles", lambda c, limit=50: [{"id": 5, "status": "rejected"}])
    d = CAP.assess(w["ctx"], w["base"](), s)
    assert d["action"] == "continue_training" and "was rejected 0 cycle(s) ago" in d["reason"]
    monkeypatch.setattr(MEM, "cycles", lambda c, limit=50: [{"id": i, "status": "completed"} for i in range(9, 5, -1)]
                        + [{"id": 5, "status": "rejected"}])
    assert CAP.assess(w["ctx"], w["base"](), s)["action"] == "grow"  # 4 cycles later: allowed again


def test_no_measurements_means_measure_first(world):
    w = world
    w["state"]["evidence"] = {"recent_improvements": [], "train_loss": None, "val_loss": None}
    d = CAP.assess(w["ctx"], w["base"](), w["settings"])
    assert d["action"] == "continue_training" and "Measuring" in d["headline"] and not d["grow"]


def test_growth_candidate_must_improve_the_capability_that_motivated_it():
    suites = [{"id": "capability:math:math", "kind": "capability", "capability": "math", "name": "Maths"},
              {"id": "capability:holdout:language", "kind": "capability", "capability": "holdout", "name": "Held-out language"}]
    base = {"capability:math:math": {"ok": True, "value": 0.05, "n": 100, "higher_is_better": True},
            "capability:holdout:language": {"ok": True, "value": 2.0, "higher_is_better": False}}
    within_noise = {**base, "capability:math:math": {"ok": True, "value": 0.08, "n": 100, "higher_is_better": True}}
    g = EV.growth_gate(["math"], suites, base, within_noise)
    assert not g["passed"] and "5.0% → 8.0%" in g["detail"]
    better = {**base, "capability:math:math": {"ok": True, "value": 0.15, "n": 100, "higher_is_better": True}}
    assert EV.growth_gate(["math"], suites, base, better)["passed"]
    lower_loss = {**base, "capability:holdout:language": {"ok": True, "value": 1.9, "higher_is_better": False}}
    assert EV.growth_gate(["holdout_language"], suites, base, lower_loss)["passed"]
    assert not EV.growth_gate(["math"], suites, base, lower_loss)["passed"]  # lower loss elsewhere is not enough


def test_assessment_is_reported_truthfully_in_the_feed_and_the_workspace(world, client):
    w = world
    w["state"]["history"] = {"math": acc(0.02, 0.02, 0.02)}
    base = w["base"]()
    M.deploy(w["ctx"], base["version"]) if M.evaluate(w["ctx"], base["version"])["status"] == "published" else None
    d = CAP.assess(w["ctx"], base, w["settings"])
    EN._growth_event(w["ctx"], {"id": None}, base, d, w["settings"])
    ev = next(e for e in MEM.events(w["ctx"], 20) if e["kind"] == "growth.proposed")
    assert ev["message"].startswith("Current architecture may be limiting progress. Testing a larger candidate: "
                                    f"{w['params']:,} → {d['params_after']:,} parameters")
    assert "Estimated training memory" in ev["message"] and ev["data"]["estimate"]["memory_bytes"] > 0
    st = client.get("/v1/admin/evolution/autopilot", headers=H(w["owner"]["token"])).json()
    intel = st["intelligence"]
    assert intel["params"] == w["params"] and intel["params_verified"] is True
    assert intel["assessment"]["action"] == "grow" and intel["assessment"]["headline"] == d["headline"]
    # a different, non-growth decision is recorded once
    keep = {**d, "grow": False, "action": "continue_training", "headline": "Keeping the current architecture for now.",
            "reason": "a growth candidate is already being trained or evaluated", "investigating": None}
    EN._growth_event(w["ctx"], {"id": None}, base, keep, w["settings"])
    EN._growth_event(w["ctx"], {"id": None}, base, keep, w["settings"])
    assert len([e for e in MEM.events(w["ctx"], 50) if e["kind"] == "growth.not_proposed"]) == 1


def test_foundation_training_lengthens_runs_within_budget(world):
    from moth_server.evolution import autopilot as AP

    w = world
    out, decisions = AP.adapt(w["ctx"], w["settings"], None, capacity={"action": "foundation_training", "tokens_per_param": 0.5})
    base = int(w["settings"]["training"]["steps"])
    assert out["training"]["steps"] == min(AP.MAX_STEPS, base * 2)
    again, _ = AP.adapt(w["ctx"], w["settings"], None, capacity={"action": "foundation_training", "tokens_per_param": 0.5})
    assert again["training"]["steps"] == min(AP.MAX_STEPS, base * 2)  # never compounding
    assert any("Foundation training" in d["message"] for d in decisions)
