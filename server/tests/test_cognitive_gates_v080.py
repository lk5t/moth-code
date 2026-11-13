"""0.8.0: built-in conversation/coding benchmarks join Evolution; a capability group may not get worse."""
from conftest import make_tiny_model
from moth.model import capabilities as C
from moth.model.registry import load_model
from moth_server.evolution import evaluation as EV
from moth_server.intelligence import weakness as W


def test_builtin_suites_are_stable_and_map_to_training_domains():
    a, b = EV.builtin_suites(), EV.builtin_suites()
    assert [s["id"] for s in a] == ["capability:dialogue:builtin", "capability:codegen:builtin", "capability:debugging:builtin"]
    assert [s["sha"] for s in a] == [s["sha"] for s in b]  # deterministic: cached results stay comparable
    assert W.DOMAINS["dialogue"] == ["conversation"] and W.DOMAINS["debugging"] == ["code"]


def test_group_gate_catches_a_coding_regression_hidden_by_conversation_gains():
    suites = [{"id": "capability:dialogue:builtin", "kind": "capability", "capability": "dialogue"},
              {"id": "capability:codegen:builtin", "kind": "capability", "capability": "codegen"},
              {"id": "capability:holdout:code", "kind": "capability", "capability": "holdout"}]
    base = {"capability:dialogue:builtin": {"ok": True, "value": 0.20, "higher_is_better": True},
            "capability:codegen:builtin": {"ok": True, "value": 0.30, "higher_is_better": True},
            "capability:holdout:code": {"ok": True, "value": 3.0, "higher_is_better": False}}
    cand = {"capability:dialogue:builtin": {"ok": True, "value": 0.40, "higher_is_better": True},
            "capability:codegen:builtin": {"ok": True, "value": 0.10, "higher_is_better": True},
            "capability:holdout:code": {"ok": True, "value": 3.3, "higher_is_better": False}}
    g = EV.group_changes(suites, base, cand)
    assert g["conversation"]["mean"] == 0.2
    assert g["coding"]["mean"] < -0.1  # -20 points and 10 % worse loss
    assert g["coding"]["changes"] == {"codegen": -0.2, "holdout_code": -0.1}


def test_suites_run_end_to_end_on_a_real_model(tmp_path):
    model, tok, _ = load_model(make_tiny_model(tmp_path, 0, "cog"))
    d = C.run_suite(model, tok, {"capability": "dialogue", "limit": 8, "max_new": 12})
    assert d["n"] == 8 and 0.0 <= d["value"] <= 1.0 and set(d["skills"]) <= {
        "remember", "correction", "list_recall", "follow_up", "clarify", "unknown", "greeting", "format"}
    c = C.run_suite(model, tok, {"capability": "debugging"})
    assert c["n"] == 10 and c["metric"] == "tests_passed" and 0.0 <= c["value"] <= 1.0


def test_generated_curricula_are_adopted_once_where_generated_data_is_used(client):
    from moth_server.intelligence import discovery as D

    ctx = client.app.state.ctx
    ctx.db.set_config("discovery_generated_v080", None)
    D.update(ctx, {"enabled": True, "approved_sources": ["python-stdlib", "synthetic-arithmetic"]})
    added = D.adopt_generated_sources(ctx)
    assert "synthetic-dialogue" in added and "synthetic-debugging" in added
    assert set(D.GENERATED_V080) <= set(D.policy(ctx)["approved_sources"])
    D.update(ctx, {"approved_sources": ["python-stdlib", "synthetic-arithmetic"]})  # the Owner removes them later
    assert D.adopt_generated_sources(ctx) == []  # once only: the Owner's choice stands
    ctx.db.set_config("discovery_generated_v080", None)
    D.update(ctx, {"approved_sources": ["python-stdlib"]})  # never used generated data: left alone
    assert D.adopt_generated_sources(ctx) == []



def test_builtin_suites_join_candidate_evaluation_unless_turned_off(client, tmp_path, monkeypatch):
    from moth_server.evolution import settings as S
    from moth_server.intelligence import library

    ctx = client.app.state.ctx
    (tmp_path / "eval").mkdir()
    monkeypatch.setattr(library, "eval_dir", lambda c: tmp_path / "eval")
    ids = {s["id"] for s in EV.capability_suites(ctx)}
    assert {"capability:dialogue:builtin", "capability:codegen:builtin", "capability:debugging:builtin"} <= ids
    S.update(ctx, {"evaluation": {"builtin_suites": False}})
    assert not any(i.endswith(":builtin") for i in (s["id"] for s in EV.capability_suites(ctx)))
