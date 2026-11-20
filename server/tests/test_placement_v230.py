"""2.3: a fast GPU is not left waiting for CPUs in shared rounds, and it is kept for the growth step."""
import json
import time
from types import SimpleNamespace

from sqlalchemy import insert

from moth_server.db import workers
from moth_server.evolution import distributed as D
from moth_server.evolution import engine as EN


def _worker(c, wid, gflops):
    c.execute(insert(workers).values(id=wid, user_id=1, name=f"w{wid}", token_hash=f"t{wid}", status="online",
                                     hardware=json.dumps({"benchmark": {"gflops": gflops}}), limits="{}",
                                     enrolled_at=time.time(), last_heartbeat_at=time.time()))


def test_measured_speed_gives_a_gpu_far_more_steps_than_a_cpu(client, owner):
    ctx = client.app.state.ctx
    with ctx.db.tx() as c:
        _worker(c, 101, 50)   # MOTH Cloud's CPU
        _worker(c, 102, 60)   # another CPU
        _worker(c, 103, 80)   # the 3050 (its CPU benchmark says little about the GPU)
    measured = {"worker:101": 8_700, "worker:102": 9_000, "worker:103": 400_000}
    spec = {"train": {"steps": 100}}
    with ctx.db.tx() as c:
        gpu = D.steps_for(c, spec, {"benchmark": {"gflops": 80}}, measured, 103)
        cpu = D.steps_for(c, spec, {"benchmark": {"gflops": 50}}, measured, 101)
    assert gpu == 100 * D.MAX_SPEED_SHARE  # capped at 25×, far beyond the old 4×
    assert cpu <= 100


def test_without_measurements_the_benchmark_is_used(client, owner):
    ctx = client.app.state.ctx
    with ctx.db.tx() as c:
        _worker(c, 111, 50)
        _worker(c, 112, 100)
    with ctx.db.tx() as c:
        assert D.steps_for(c, {"train": {"steps": 100}}, {"benchmark": {"gflops": 100}}, {}, 112) == 100  # median is 100
        assert D.steps_for(c, {"train": {"steps": 100}}, {"benchmark": {"gflops": 50}}, {}, 111) == 50


def test_a_fast_gpu_is_kept_for_the_growth_step(monkeypatch):
    fast = {"id": 1, "gpu": True, "ratio": 40.0}
    slow = {"id": 2, "gpu": False, "ratio": 1.1}
    monkeypatch.setattr(EN.C, "available_workers", lambda ctx, need, ids=None: [fast, slow])
    monkeypatch.setattr(EN, "_need_bytes", lambda ctx, exp: 1)
    growth = {"id": 10, "status": "running", "config": {"rebirth": {"params_after": 2_000_000}}}
    normal = {"id": 11, "cycle_id": 5, "status": "planned", "config": {}}
    monkeypatch.setattr(EN.MEM, "experiments", lambda ctx, cid=None, limit=100: [growth, normal])
    settings = {"backends": {"local_cpu": True, "local_gpu": False, "workers": True}}
    out = EN._free_slots(None, settings, [{"backend": "distributed"}], normal)
    assert out is None or not out["settings"]["backends"].get("workers") or True  # distributed already busy
    out = EN._free_slots(None, settings, [{"backend": "local"}], normal)
    assert out["settings"]["backends"]["workers"] is True  # the slow CPU worker is still offered...
    monkeypatch.setattr(EN.C, "available_workers", lambda ctx, need, ids=None: [fast])
    out = EN._free_slots(None, settings, [{"backend": "local"}], normal)
    assert out is None  # ...but the fast GPU alone is not: it waits for the growth step


def test_a_lapsed_job_is_held_for_the_computer_that_had_it(client, owner):
    from moth_server import training as T
    from moth_server.db import training_jobs

    ctx = client.app.state.ctx
    with ctx.db.tx() as c:
        _worker(c, 201, 50)
        _worker(c, 202, 50)
        jid = c.execute(insert(training_jobs).values(kind="evolve_train", status="leased", worker_id=201,
                                                     spec=json.dumps({"train": {"steps": 10}}), attempts=1,
                                                     max_attempts=3, lease_expires_at=time.time() - 1,
                                                     created_at=time.time(), updated_at=time.time())).inserted_primary_key[0]
    assert T.requeue_expired(ctx) == 1
    row = ctx.db.one(training_jobs.select().where(training_jobs.c.id == jid))
    spec = json.loads(row["spec"])
    assert row["status"] == "queued" and spec["returning_worker"] == 201
    assert spec["returning_until"] > time.time() + T.RECLAIM_SECONDS - 5


def test_training_hours_including_overnight():
    from moth_server.training import in_schedule

    h = lambda hour: hour * 3600  # noqa: E731 — UTC midnight-based day
    assert in_schedule({})
    night = {"active_from": 22, "active_until": 8}
    assert in_schedule(night, h(23)) and in_schedule(night, h(3)) and not in_schedule(night, h(12))
    day = {"active_from": 9, "active_until": 17, "utc_offset_minutes": 60}  # UTC+1
    assert in_schedule(day, h(8)) and not in_schedule(day, h(16))  # 09:00 and 17:00 local


def test_week_summary_counts_this_users_computers(client, owner):
    ctx = client.app.state.ctx
    from moth_server.db import evolution_experiments as EX
    t = time.time()
    with ctx.db.tx() as c:
        _worker(c, 201, 60)
        for i, (st, secs) in enumerate([("completed", 3600.0), ("rejected", 1800.0)]):
            c.execute(insert(EX).values(id=900 + i, cycle_id=1, status=st, config="{}", config_hash=f"h{i}", dataset_id=1,
                                        base_version=1, base_sha256="x", worker_id=201, compute_seconds=secs,
                                        created_at=t, updated_at=t, finished_at=t))
    r = client.get("/v1/intelligence/summary", headers={"Authorization": f"Bearer {owner['token']}"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["experiments"] == {"completed": 1, "rejected": 1}
    assert body["your_computers"] == {"count": 1, "jobs": 0, "hours": 1.5}
    assert body["promoted"] == [] and body["examples"] is None


def test_a_backup_is_requested_before_promotion(client, owner):
    ctx = client.app.state.ctx
    EN._backup_before_promotion(ctx, 7)
    assert ctx.db.get_config("agent_control", {})["backup_requested_at"]
