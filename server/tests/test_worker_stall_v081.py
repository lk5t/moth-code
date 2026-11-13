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
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True}})  # nothing else can train it
    clock = [1_000_000.0]
    monkeypatch.setattr(EN, "now", lambda: clock[0])
    _tick(ctx, cyc, exp["id"])  # leased, progress 0: downloading
    clock[0] += 300
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "running"  # 5 minutes: still allowed to start
    clock[0] += 400
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "waiting"  # never started within 10 minutes


def test_idle_moth_cloud_takes_over_a_worker_that_never_starts(client, owner, tmp_path, monkeypatch):
    """0.8.3: while MOTH Cloud has nothing to train, a worker gets 3 minutes (not 10) for its first step."""
    ctx, cyc, exp, jid, w = _leased(client, owner, tmp_path, monkeypatch)
    S.update(ctx, {"backends": {"local_cpu": True, "local_gpu": False, "workers": True}})
    clock = [1_000_000.0]
    monkeypatch.setattr(EN, "now", lambda: clock[0])
    _tick(ctx, cyc, exp["id"])
    clock[0] += 120
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "running"
    clock[0] += 90
    _tick(ctx, cyc, exp["id"])
    assert MEM.experiment(ctx, exp["id"])["status"] == "waiting"


def test_a_busy_computer_is_not_trusted_on_its_benchmark(client, owner, tmp_path, monkeypatch):
    """0.8.3: a worker whose computer is already at 92 % CPU and 91 % memory does not win placement over
    an idle MOTH Cloud because of a benchmark taken when it was free."""
    from moth_server.evolution import compute as C

    ctx = client.app.state.ctx
    monkeypatch.setattr(C, "local_gflops", lambda ctx: 10.0)
    ws = []
    for name, util in (("busy-serv", {"cpu": 0.92, "memory": 0.91}), ("free-pc", {"cpu": 0.1, "memory": 0.3})):
        e = client.post("/v1/training/enrollments", json={"name": name}, headers=H(owner["token"])).json()
        hw = {"compute": "cpu", "gpus": [], "ram_gb": 16, "cpu_count": 4, "benchmark": {"gflops": 50.0},
              "utilization": util, "machine_id": name}
        w = client.post("/v1/worker/enroll", json={"token": e["token"], "version": "0.8.3", "hardware": hw}).json()
        client.post("/v1/worker/heartbeat", json={"version": "0.8.3", "hardware": hw}, headers=H(w["worker_token"]))
        ws.append(w)
    sp = {x["id"]: x for x in C.worker_speeds(ctx)}
    busy, free = sp[ws[0]["worker_id"]], sp[ws[1]["worker_id"]]
    assert busy["ratio"] < C.PREFER_WORKER <= free["ratio"]
    assert "busy" in busy["basis"] and "low memory" in busy["basis"] and free["basis"] == "benchmark"


def test_a_taken_back_experiment_continues_from_the_workers_progress(client, owner, tmp_path, monkeypatch):
    """0.9.0: the worker's verified progress snapshot becomes the next start; only the remaining steps run."""
    import hashlib

    import torch
    from moth.community.validation import serialize_state, tensor_bytes_sha256

    ctx, cyc, exp, jid, w = _leased(client, owner, tmp_path, monkeypatch)
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True}})
    job = client.post(f"/v1/worker/jobs/{jid}/weights", headers=H(w["worker_token"]))  # POST is not allowed
    assert job.status_code == 405
    base = torch.load(__import__("io").BytesIO(client.get(f"/v1/worker/jobs/{jid}/weights",
                                                          headers=H(w["worker_token"])).content), weights_only=True)
    spec = json.loads(B.job(ctx, jid)["spec"])
    steps = int(spec["train"]["steps"])
    delta = {k: torch.full_like(v.float(), 1e-4) for k, v in base.items()}
    body = serialize_state(delta)
    meta = {"base_sha256": spec["base_sha256"], "delta_sha256": tensor_bytes_sha256(body), "step": steps // 2, "tokens": 1234}
    snap = lambda m, b: client.post(f"/v1/worker/jobs/{jid}/snapshot", content=b, headers={
        **H(w["worker_token"]), "x-moth-contribution": json.dumps(m), "content-type": "application/octet-stream"}).json()
    assert not snap({**meta, "delta_sha256": "0" * 64}, body)["accepted"]  # checksum checked
    assert snap(meta, body)["accepted"]
    assert not snap(meta, body)["accepted"]  # not the same or an earlier step again
    clock = [1_000_000.0]
    monkeypatch.setattr(EN, "now", lambda: clock[0])
    client.post("/v1/worker/heartbeat", json={"version": "0.9.0", "job_id": jid, "progress": 0.5}, headers=H(w["worker_token"]))
    _tick(ctx, cyc, exp["id"])
    clock[0] += 200
    _tick(ctx, cyc, exp["id"])  # no progress for 2+ minutes after training started: taken back
    e = MEM.experiment(ctx, exp["id"])
    assert e["status"] == "waiting"
    r = e["config"]["resume"]
    assert r["step"] == steps // 2 and r["tokens"] == 1234 and e["config"]["steps"] == steps - steps // 2
    ev = next(x for x in MEM.events(ctx, 10) if x["kind"] == "experiment.reassigned")
    assert f"continuing from step {steps // 2:,}" in ev["message"]
    # the next job starts from base + delta, for the remaining steps only
    jid2 = B.create_worker_job(ctx, e)
    spec2 = json.loads(B.job(ctx, jid2)["spec"])
    assert spec2["resume_base"] and spec2["train"]["steps"] == steps - steps // 2
    start = torch.load(B.job_files(ctx, spec2)[0], weights_only=True)
    k = next(iter(base))
    assert torch.allclose(start[k].float(), base[k].float() + 1e-4, atol=1e-6)
    assert hashlib.sha256(B.job_files(ctx, spec2)[0].read_bytes()).hexdigest() == spec2["base_sha256"]
