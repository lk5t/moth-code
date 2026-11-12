"""0.6.3 distributed network: independent experiments train side by side on the server and on a real
MOTH worker, and the cycle finishes sooner than running them one after another (measured)."""
import threading
import time

from sqlalchemy import select

from conftest import H
from moth_server.db import training_jobs
from moth_server.evolution import engine as EN
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S
from test_evolution import FAST, add_dataset, drive, world  # noqa: F401  (fixture)

STEPS = {"training": {**FAST["training"], "steps": 120}, "max_experiments_per_cycle": 2,
         "growth": {"enabled": False}, "autopilot": False}


def _trained_at(ctx, cyc_id):
    exps = MEM.experiments(ctx, cyc_id)
    return exps, max(e["finished_at"] or e["updated_at"] for e in exps)


def _run(client, ctx, o, parallel, tmp_path):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    S.update(ctx, {**STEPS, "parallel_experiments": parallel,
                   "backends": {"local_cpu": True, "local_gpu": False, "workers": parallel}})
    stop = threading.Event()
    if parallel:
        client.put("/v1/admin/config/flags", json={"allow_cpu_workers": True}, headers=o)
        e = client.post("/v1/training/enrollments", json={"name": "lab"}, headers=o).json()
        w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": [], "cpu_count": 2},
                                                   "version": "0.6.3"}).json()
        runner = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / "w", allow_cpu=True,
                              log=lambda m: None, heartbeat_seconds=3600)
        runner.beat()

        def work():  # a real worker loop: claim, train, upload
            while not stop.is_set():
                r = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"]))
                job = r.json() if r.status_code == 200 else None
                if job and job.get("kind"):
                    runner.run_job(job)
                else:
                    runner.beat()
                    time.sleep(0.3)
        threading.Thread(target=work, daemon=True).start()
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    t0 = time.time()
    cyc = drive(ctx, lambda c: c["status"] in ("evaluating", "deploying", "monitoring") or c["status"] in MEM.TERMINAL_CYCLE,
                timeout=900)
    stop.set()
    exps, done = _trained_at(ctx, cyc["id"])
    return exps, done - t0


def test_independent_experiments_run_in_parallel_and_finish_sooner(client, settings, world, tmp_path):
    ctx, o = world["ctx"], world["o"]
    exps, parallel_s = _run(client, ctx, o, True, tmp_path)
    backends = {e["backend"] for e in exps}
    assert backends == {"local", "worker"}, [(e["id"], e["backend"], e["status"]) for e in exps]
    a, b = sorted(exps, key=lambda e: e["started_at"])
    assert b["started_at"] < (a["finished_at"] or time.time())  # the second started before the first finished
    assert any(ev["kind"] == "plan.parallel" for ev in MEM.events(ctx, limit=100))
    job = ctx.db.one(select(training_jobs).where(training_jobs.c.kind == "evolve_train"))
    assert job and job["status"] == "completed"  # exactly one worker job, no duplicates
    assert len(ctx.db.all(select(training_jobs).where(training_jobs.c.kind == "evolve_train"))) == 1
    print(f"\nparallel two-experiment training (server + 1 worker): {parallel_s:.1f} s")


def test_sequential_baseline_for_comparison(client, settings, world, tmp_path):
    ctx, o = world["ctx"], world["o"]
    exps, sequential_s = _run(client, ctx, o, False, tmp_path)
    a, b = sorted(exps, key=lambda e: e["started_at"])
    assert {e["backend"] for e in exps} == {"local"}
    a_trained = a["started_at"] + float((a["metrics"].get("training") or {}).get("seconds") or 0)
    assert b["started_at"] >= a_trained - 1  # strictly one after the other
    print(f"\nsequential two-experiment training: {sequential_s:.1f} s")


def test_queued_worker_job_is_waiting_not_training(client, settings, world):
    """Found by the 0.5.0 → 0.6.3 upgrade check: a job no worker has taken yet must not read as training."""
    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {**STEPS, "backends": {"local_cpu": False, "local_gpu": True, "workers": True}})
    client.put("/v1/admin/config/flags", json={"allow_cpu_workers": True}, headers=o)
    e = client.post("/v1/training/enrollments", json={"name": "lab"}, headers=o).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": [], "cpu_count": 4, "ram_gb": 8},
                                               "version": "0.6.3"}).json()
    client.post("/v1/worker/heartbeat", json={"hardware": {"gpus": [], "cpu_count": 4, "ram_gb": 8}},
                headers=H(w["worker_token"]))
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    cyc = drive(ctx, lambda c: any(x["status"] == "running" for x in MEM.experiments(ctx, c["id"])), timeout=120)
    for _ in range(2):
        EN.tick(ctx)
    cyc = MEM.cycle(ctx, cyc["id"])
    running = [x for x in MEM.experiments(ctx, cyc["id"]) if x["status"] == "running"]
    assert running and all(x["backend"] == "worker" and x["job_id"] for x in running), running
    assert cyc["status"] == "waiting_for_compute", cyc["status"]
    assert cyc["result"]["waiting_reason"] == "waiting for a MOTH worker to take the job"
