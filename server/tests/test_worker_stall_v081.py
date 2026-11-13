"""0.8.1: a worker that holds a job without training progress loses it within minutes."""
import json

from conftest import H
from moth_server.db import training_jobs
from moth_server.evolution import backends as B, engine as EN, memory as MEM, settings as S
from test_evolution_v053 import _world


def _leased(client, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    cyc = EN.start_cycle(ctx)
    EN._planning(ctx, cyc, S.get(ctx))
    exp = MEM.experiments(ctx, cyc["id"])[0]
    MEM.update_experiment(ctx, exp["id"], status="running", backend="worker")
    exp = MEM.experiment(ctx, exp["id"])
    jid = B.create_worker_job(ctx, exp)
    MEM.update_experiment(ctx, exp["id"], job_id=jid)
    e = client.post("/v1/training/enrollments", json={"name": "slow-pc"}, headers=H(owner["token"])).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "version": "0.8.1",
                                               "hardware": {"compute": "cpu", "gpus": [], "ram_gb": 16, "cpu_count": 2}}).json()
    claim = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"]))
    assert claim.status_code == 200 and claim.json()["id"] == jid
    return ctx, cyc, MEM.experiment(ctx, exp["id"]), jid, w


def _tick(ctx, cyc, exp_id):
    EN._advance_running(ctx, MEM.cycle(ctx, cyc["id"]), MEM.experiment(ctx, exp_id), S.get(ctx))


def test_stalled_worker_job_is_taken_back(client, owner, tmp_path, monkeypatch):
    ctx, cyc, exp, jid, w = _leased(client, owner, tmp_path, monkeypatch)
    hb = lambda p: client.post("/v1/worker/heartbeat", json={"version": "0.8.1", "job_id": jid, "progress": p},
                               headers=H(w["worker_token"]))
    clock = [1_000_000.0]
    monkeypatch.setattr(EN, "now", lambda: clock[0])
    hb(0.1)
    _tick(ctx, cyc, exp["id"])  # progress seen
    clock[0] += 60
    hb(0.2)
    _tick(ctx, cyc, exp["id"])  # still training: keeps the job
    assert MEM.experiment(ctx, exp["id"])["status"] == "running"
    clock[0] += 100
    hb(0.2)  # heartbeats continue (e.g. paused), progress does not
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "running"  # 100 s: within the 2-minute allowance
    clock[0] += 30
    _tick(ctx, cyc, exp["id"])
    e = MEM.experiment(ctx, exp["id"])
    assert e["status"] == "waiting" and e["backend"] is None and e["job_id"] is None  # placed again
    job = ctx.db.one(training_jobs.select().where(training_jobs.c.id == jid))
    assert job["status"] == "cancelled" and "no training progress" in job["error"]
    assert hb(0.2).json()["job_cancelled"]  # the worker is told to stop
    assert any(ev["kind"] == "experiment.reassigned" and "no training progress" in ev["message"] for ev in MEM.events(ctx, 10))


def test_worker_gets_time_to_start(client, owner, tmp_path, monkeypatch):
    ctx, cyc, exp, jid, w = _leased(client, owner, tmp_path, monkeypatch)
    clock = [1_000_000.0]
    monkeypatch.setattr(EN, "now", lambda: clock[0])
    _tick(ctx, cyc, exp["id"])  # leased, progress 0: downloading
    clock[0] += 300
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "running"  # 5 minutes: still allowed to start
    clock[0] += 400
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "waiting"  # never started within 10 minutes
