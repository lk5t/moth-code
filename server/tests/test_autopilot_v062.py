"""0.6.2 autopilot: adaptive plan from recorded measurements, explained decisions, one-click start."""
import json

from conftest import H
from moth_server import models as M
from moth_server.db import evolution_cycles, evolution_experiments, now
from moth_server.evolution import autopilot as AP
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S

BASE = "/v1/admin/evolution"


def _cycle(ctx, status="rejected"):
    t = now()
    with ctx.db.tx() as c:
        return c.execute(evolution_cycles.insert().values(status=status, trigger="schedule", plan="{}", result="{}",
                                                           created_at=t, updated_at=t, finished_at=t)).inserted_primary_key[0]


def _exp(ctx, status, improvement=None, error=None, **metrics):
    cid = _cycle(ctx)
    m = dict(metrics)
    if improvement is not None:
        m["primary_improvement"] = improvement
    t = now()
    with ctx.db.tx() as c:
        return c.execute(evolution_experiments.insert().values(
            cycle_id=cid, status=status, config="{}", config_hash=f"h{t}", dataset_id=1, base_version=1,
            base_sha256="x", rationale="test", attempts=1, max_attempts=3, metrics=json.dumps(m), resources="{}",
            compute_seconds=1.0, error=error, created_at=t, updated_at=t, finished_at=t)).inserted_primary_key[0]


def test_no_history_changes_nothing_and_manual_mode_is_respected(client):
    ctx = client.app.state.ctx
    s = S.get(ctx)
    out, decisions = AP.adapt(ctx, s)
    assert decisions == [] and out["training"] == s["training"]
    _exp(ctx, "passed", 0.05); _exp(ctx, "passed", 0.04)
    out, decisions = AP.adapt(ctx, {**s, "autopilot": False})
    assert decisions == [] and out["training"]["steps"] == s["training"]["steps"]


def test_trains_longer_when_results_keep_improving(client):
    ctx = client.app.state.ctx
    _exp(ctx, "passed", 0.04); _exp(ctx, "passed", 0.05)
    s = S.get(ctx)
    out, decisions = AP.adapt(ctx, s)
    assert out["training"]["steps"] == int(s["training"]["steps"] * 1.5)
    d = next(d for d in decisions if d["kind"] == "steps")
    assert "5.0%" in d["message"] and "4.0%" in d["message"] and "training longer" in d["message"]


def test_lower_learning_rate_when_progress_stalls(client):
    ctx = client.app.state.ctx
    _exp(ctx, "rejected", 0.001); _exp(ctx, "rejected", 0.002)
    s = S.get(ctx)
    out, decisions = AP.adapt(ctx, s)
    assert out["training"]["lr"] == s["training"]["lr"] / 2
    assert any(d["kind"] == "lr" and "lower learning rate" in d["message"] for d in decisions)


def test_smaller_batch_after_out_of_memory(client):
    ctx = client.app.state.ctx
    _exp(ctx, "failed", error="RuntimeError: CUDA error: out of memory")
    s = S.get(ctx)
    out, decisions = AP.adapt(ctx, s)
    assert out["training"]["batch_size"] == s["training"]["batch_size"] // 2
    assert "ran out of memory" in decisions[0]["message"]


def test_fits_measured_step_time_into_the_cycle_budget(client):
    ctx = client.app.state.ctx
    _exp(ctx, "rejected", 0.01, training={"step": 10, "seconds": 3600.0})  # 360 s per step
    s = S.get(ctx)
    out, decisions = AP.adapt(ctx, s)
    budget = s["budget"]["max_cycle_hours"] * 3600 * 0.8
    assert out["training"]["steps"] == max(AP.MIN_STEPS, int(budget / (360.0 * s["max_experiments_per_cycle"])))
    assert any(d["kind"] == "budget" and "360.00 s" in d["message"] for d in decisions)


def test_slows_down_instead_of_looping_without_improvement(client):
    ctx = client.app.state.ctx
    for _ in range(3):
        _cycle(ctx, "rejected")
    s = S.get(ctx)
    out, decisions = AP.adapt(ctx, s)
    assert out["interval_hours"] >= 1.0 > s["interval_hours"]
    assert any(d["kind"] == "pace" and "no accepted improvement" in d["message"] for d in decisions)


def test_decisions_are_recorded_and_reported(client, owner):
    ctx = client.app.state.ctx
    _exp(ctx, "passed", 0.04); _exp(ctx, "passed", 0.05)
    s, decisions = AP.adapt(ctx, S.get(ctx))
    AP.remember(ctx, s, decisions, None)
    ev = [e for e in MEM.events(ctx, limit=20) if e["kind"] == "plan.adjusted"]
    assert ev and "training longer" in ev[0]["message"]
    st = client.get(f"{BASE}/autopilot", headers=H(owner["token"])).json()
    assert st["plan"]["steps"] == s["training"]["steps"] and st["decisions"][0]["kind"] == "steps"


def test_one_click_start_from_genesis_and_pause(client, owner, settings):
    from conftest import register_verified

    ctx = client.app.state.ctx
    o = H(owner["token"])
    assert M.deployed(ctx) is None
    assert client.get(f"{BASE}/autopilot", headers=o).json()["stage"] == "genesis"
    user = register_verified(client, settings, "plainuser")["token"]
    assert client.post(f"{BASE}/autopilot/start", headers=H(user)).status_code == 403
    r = client.post(f"{BASE}/autopilot/start", headers=o)
    assert r.status_code == 200, r.text
    body = r.json()
    assert M.deployed(ctx)["info"]["params"] == 99_648  # a real, untrained seed model
    assert any("Created the first MOTH model" in step for step in body["steps"])
    s = S.get(ctx)
    assert s["enabled"] and not s["paused"] and s["automatic"]
    from moth_server.intelligence import discovery

    approved = discovery.policy(ctx)["approved_sources"]
    assert "python-stdlib" in approved and set(approved) <= set(AP.PRIORITY)
    kinds = [e["kind"] for e in MEM.events(ctx, limit=30)]
    assert "genesis.created" in kinds and "engine.started" in kinds
    # starting again never creates a second model
    assert client.post(f"{BASE}/autopilot/start", headers=o).status_code == 200
    assert len(M.list_releases(ctx)) == 1
    p = client.post(f"{BASE}/autopilot/pause", headers=o).json()
    assert p["status"]["stage"] == "paused" and S.get(ctx)["paused"]
