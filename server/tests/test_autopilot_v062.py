"""0.6.2 autopilot: adaptive plan from recorded measurements, explained decisions, one-click start."""
import json
import time

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


def test_evolution_is_continuous_even_without_improvement(client):
    """0.6.3: no waiting between rounds — after rejected rounds the next one is due immediately; only a
    failed round waits briefly before its retry."""
    from moth_server.evolution import engine as EN

    ctx = client.app.state.ctx
    for _ in range(3):
        _cycle(ctx, "rejected")
    out, decisions = AP.adapt(ctx, S.get(ctx))
    assert not any(d["kind"] == "pace" for d in decisions)
    import threading

    wake = threading.Event()
    ctx.extras["evolution_wake_event"] = wake
    t = time.time()
    EN._schedule_next(ctx, failed=False)
    assert EN.state(ctx)["next_cycle_at"] <= time.time() and wake.is_set()  # the loop starts the next round now
    wake.clear()
    EN._schedule_next(ctx, failed=True)
    st = EN.state(ctx)
    assert 59 <= st["next_cycle_at"] - t <= 70 and not wake.is_set() and st["consecutive_failures"] == 1


def test_decisions_are_recorded_and_reported(client, owner):
    ctx = client.app.state.ctx
    _exp(ctx, "passed", 0.04); _exp(ctx, "passed", 0.05)
    owner_s = S.get(ctx)
    s, decisions = AP.adapt(ctx, owner_s)
    AP.remember(ctx, s, decisions, None, owner_s)
    assert AP.adapt(ctx, owner_s)[0]["training"]["steps"] >= s["training"]["steps"]  # the adapted plan carries over
    changed = {**owner_s, "training": {**owner_s["training"], "steps": 3}}
    assert AP.adapt(ctx, changed)[0]["training"]["steps"] >= 3  # an Owner change restarts from the Owner's value
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
    from moth_server.routes.admin import flags

    flags_before = flags(ctx)
    r = client.post(f"{BASE}/autopilot/start", headers=o)
    assert r.status_code == 200, r.text
    assert flags(ctx) == flags_before  # safety baseline and every other policy flag untouched
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


def test_worker_connect_and_disconnect_are_recorded_once(client, owner):
    from moth_server import db as D
    from moth_server import training
    from moth_server.evolution import engine as EN

    ctx = client.app.state.ctx
    wid, _ = training.enroll_worker(ctx, training.create_enrollment(ctx, owner["user"], "Lab GPU", None), {}, "0.6.2")
    with ctx.db.tx() as c:
        c.execute(D.workers.update().where(D.workers.c.id == wid).values(last_heartbeat_at=now()))
    EN._watch_workers(ctx, EN.state(ctx))
    EN._watch_workers(ctx, EN.state(ctx))  # no change: no second event
    with ctx.db.tx() as c:
        c.execute(D.workers.update().where(D.workers.c.id == wid).values(last_heartbeat_at=now() - 600))
    EN._watch_workers(ctx, EN.state(ctx))
    kinds = [e["kind"] for e in MEM.events(ctx, limit=20) if e["kind"].startswith("worker.")]
    assert kinds == ["worker.disconnected", "worker.connected"]
    assert "Lab GPU" in MEM.events(ctx, limit=1)[0]["message"]


def test_evolution_memory_runs_the_strategy_that_worked_first(client):
    ctx = client.app.state.ctx
    for status, imp, strat in [("passed", 0.04, "balanced"), ("passed", 0.03, "balanced"),
                               ("rejected", 0.001, "weakness"), ("rejected", -0.01, "weakness")]:
        eid = _exp(ctx, status, imp)
        with ctx.db.tx() as c:
            c.execute(evolution_experiments.update().where(evolution_experiments.c.id == eid)
                      .values(config=json.dumps({"strategy": strat})))
    ranked, note = AP.rank_strategies(ctx, ["weakness", "weakness", "balanced"])
    assert ranked == ["balanced", "weakness"]
    assert "2 of 2 runs" in note and "0 of 2" in note and "balanced experiments run first" in note
    # with too little history the planner keeps exploring in its default order
    assert AP.rank_strategies(ctx, ["weakness", "new-idea"])[0] == ["weakness", "new-idea"]


def test_data_that_helped_gets_more_weight(client):
    ctx = client.app.state.ctx
    for imp, w in [(0.05, {"code": 0.8, "language": 0.2}), (0.04, {"code": 0.7, "language": 0.3}),
                   (0.0, {"code": 0.2, "language": 0.8}), (-0.01, {"code": 0.1, "language": 0.9})]:
        eid = _exp(ctx, "passed" if imp > 0 else "rejected", imp)
        with ctx.db.tx() as c:
            c.execute(evolution_experiments.update().where(evolution_experiments.c.id == eid)
                      .values(config=json.dumps({"mixture": {"weights": w}})))
    eff = AP.data_effects(ctx)
    assert eff["code"]["effect"] > 0 > eff["language"]["effect"]
    mix, note = AP.apply_data_effects(ctx, {"weights": {"code": 0.5, "language": 0.5}, "stage": "s"})
    assert mix["weights"]["code"] > 0.5 > mix["weights"]["language"] and abs(sum(mix["weights"].values()) - 1) < 1e-9
    assert mix["weights"]["code"] <= 0.5 * 1.3 / (0.5 * 1.3 + 0.5 * 0.7) + 1e-9  # a bounded shift, not a takeover
    assert "more code data" in note


def test_library_grows_when_the_model_has_used_it_up(client, owner, monkeypatch):
    from moth_server.intelligence import discovery, library
    ctx = client.app.state.ctx
    dep = {"version": 1, "info": {"lineage_totals": {"tokens": 4_000_000}}}
    monkeypatch.setattr("moth_server.models.deployed", lambda ctx: dep)
    monkeypatch.setattr(library, "latest_ready", lambda ctx: {"manifest": {"token_counts": {"code": {"train": 1_000_000}}}})
    monkeypatch.setattr(discovery, "ensure_data", lambda ctx, wait=False: {"status": "preparing"})
    before = discovery.policy(ctx)["max_source_chars"]
    r = AP.scale_data(ctx)
    assert r and discovery.policy(ctx)["max_source_chars"] == before * 2
    assert any(e["kind"] == "data.scaled" for e in MEM.events(ctx, limit=5))
    dep["info"]["lineage_totals"]["tokens"] = 1_000_000  # not used up yet: no change
    assert AP.scale_data(ctx) is None


def test_command_center_reports_workers_tasks_versions_and_bottleneck(client, owner):
    from moth_server import db as D
    from moth_server import training

    ctx = client.app.state.ctx
    wid, _ = training.enroll_worker(ctx, training.create_enrollment(ctx, owner["user"], "Lab GPU", None),
                                    {"compute": "gpu", "gpus": [{"name": "RTX"}]}, "0.6.3")
    with ctx.db.tx() as c:
        c.execute(D.workers.update().where(D.workers.c.id == wid).values(last_heartbeat_at=now(), status="online"))
        c.execute(D.training_jobs.insert().values(kind="evolve_train", status="leased", worker_id=wid, spec="{}",
                                                  progress=0.4, created_at=now(), updated_at=now()))
        c.execute(D.training_jobs.insert().values(kind="evolve_train", status="queued", spec="{}", created_at=now(), updated_at=now()))
    st = client.get(f"{BASE}/autopilot", headers=H(owner["token"])).json()
    w = next(x for x in st["workers"] if x["id"] == wid)
    assert w["online"] and w["compute"] == "GPU" and w["task"] == {"kind": "evolve_train", "progress": 0.4, "experiment": None} and w["state"] == "working"
    assert st["queued_jobs"] == 1 and set(st["versions"]) == {"active", "previous", "active_name", "previous_name"}
    with ctx.db.tx() as c:  # the only worker goes offline: queued work cannot start, and status says so
        c.execute(D.workers.update().where(D.workers.c.id == wid).values(last_heartbeat_at=now() - 600))
    st = client.get(f"{BASE}/autopilot", headers=H(owner["token"])).json()
    assert st["bottleneck"] == "1 job(s) wait for a MOTH worker, but none is online."
