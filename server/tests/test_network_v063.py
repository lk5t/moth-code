"""0.6.3 unified computing network: MOTH Cloud and MOTH Workers train together in one Evolution cycle.

Real end to end: a dataset-library build with a conversation source (assistant-only loss masks), a
real MOTH Worker loop (claim, download weights + shard + mask, train, upload) and real training on
this server, at the same time. Also: speed-aware placement, the version gate for masked jobs and the
live view of every machine."""
import hashlib
import io
import json
import threading
import time

import pytest

from conftest import H, make_tiny_model
from moth_server import models as M
from moth_server.evolution import compute as C
from moth_server.evolution import engine as EN
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S
from test_evolution import FAST, drive

STORY = ("Once upon a time a small fox named Pip lived near a quiet river. Every morning Pip walked to the water "
         "and counted the stones. ")


def _library(ctx, owner, monkeypatch):
    """A real library build: stories (language) + question/answer pairs (conversation: masked)."""
    from moth.datafactory import catalog, fetch
    from moth_server.intelligence import library

    stories = "".join(f"{STORY} On day {i} Pip counted {i * 7} birds.\n<|endoftext|>\n" for i in range(400)).encode()
    chat = "".join(json.dumps({"question": f"How many birds did Pip count on day {i}?",
                               "answer": f"Pip counted {i * 7} birds on day {i}."}) + "\n" for i in range(400)).encode()
    files = {"s.txt": stories, "c.jsonl": chat}
    src = lambda sid, name, fmt, dom, extra=None: {  # noqa: E731
        "id": sid, "repo": f"t/{sid}", "revision": "a" * 40, "format": fmt, "license": "MIT", "license_url": "",
        "attribution": "test", "name": sid, "domain": dom, "description": "", **(extra or {}),
        "files": [{"path": name, "size": len(files[name]), "sha256": hashlib.sha256(files[name]).hexdigest(), "role": "train"}]}
    monkeypatch.setattr(catalog, "SOURCES", [src("tiny", "s.txt", "stories", "language"),
                                             src("chat", "c.jsonl", "qa_jsonl", "conversation", {"fields": ["question", "answer"]})])

    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        return R(files["c.jsonl" if url.endswith("c.jsonl") else "s.txt"])

    monkeypatch.setattr(fetch.urllib.request, "urlopen", urlopen)
    bid = library.start_build(ctx, owner["user"]["id"], {"sources": ["tiny", "chat"], "holdout_fraction": 0.05,
                                                         "holdout_overrides": {}, "near_dedupe": False}, wait=True)
    assert library.latest_ready(ctx)["id"] == bid
    return bid


def _world(client, owner, tmp_path, monkeypatch, **settings):
    ctx = client.app.state.ctx
    rel = M._register(ctx, make_tiny_model(tmp_path, 0, "moth-base"), "moth-base", {"type": "upload"}, None)
    assert M.evaluate(ctx, rel["version"])["status"] == "published"
    M.deploy(ctx, rel["version"])
    S.update(ctx, {**FAST, "growth": {"enabled": False}, "autopilot": False, **settings})
    _library(ctx, owner, monkeypatch)
    return ctx


def _enroll(client, owner, version="0.6.4", gflops=None):
    e = client.post("/v1/training/enrollments", json={"name": "linux-box"}, headers=H(owner["token"])).json()
    hw = {"gpus": [], "cpu_count": 2, "ram_gb": 8, "ram_available_gb": 6, "compute": "cpu",
          **({"benchmark": {"gflops": gflops}} if gflops else {}), "utilization": {"cpu": 0.25, "memory": 0.25}}
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": hw, "version": version}).json()
    client.post("/v1/worker/heartbeat", json={"hardware": hw, "version": version}, headers=H(w["worker_token"]))
    return w


def _run_worker(client, w, tmp_path, stop, seen):
    from moth.model.transformer import MothModel
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    runner = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / "w", allow_cpu=True,
                          log=lambda m: None, heartbeat_seconds=3600)
    real_forward = MothModel.forward

    def forward(self, idx, targets=None, loss_mask=None, *a, **k):  # observe what the worker trains with
        if targets is not None and threading.current_thread().name == "worker-loop":
            seen.append(None if loss_mask is None else (int(loss_mask.numel()), int(loss_mask.sum())))
        return real_forward(self, idx, targets, loss_mask, *a, **k)

    MothModel.forward = forward

    def work():
        try:
            while not stop.is_set():
                r = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"]))
                job = r.json() if r.status_code == 200 else None
                if job and job.get("kind"):
                    runner.run_job(job)
                else:
                    time.sleep(0.3)
        finally:
            MothModel.forward = real_forward

    t = threading.Thread(target=work, daemon=True, name="worker-loop")
    t.start()
    return t


def test_cloud_and_worker_train_masked_conversation_data_together(client, owner, tmp_path, monkeypatch):
    ctx = _world(client, owner, tmp_path, monkeypatch, max_experiments_per_cycle=2,
                 training={**FAST["training"], "steps": 60},
                 backends={"local_cpu": True, "local_gpu": False, "workers": True})
    old = _enroll(client, owner, version="0.6.3")  # the published 0.6.3 worker cannot apply loss masks
    w = _enroll(client, owner)
    stop, seen = threading.Event(), []
    t0 = time.time()
    cyc = drive(ctx, lambda c: any(e["backend"] == "worker" and e.get("job_id") for e in MEM.experiments(ctx, c["id"]))
                or c["status"] in MEM.TERMINAL_CYCLE, timeout=300)
    exps = MEM.experiments(ctx, cyc["id"])
    worker_exp = next(e for e in exps if e["backend"] == "worker")
    job = json.loads(EN.B.job(ctx, worker_exp["job_id"])["spec"])
    # the conversation data's mask travels with the job; only a worker that applies it may take it
    assert job["mask_sha256"] and job["min_worker_version"] == "0.6.4"
    assert client.post("/v1/worker/jobs/claim", headers=H(old["worker_token"])).status_code in (200, 204)
    assert EN.B.job(ctx, worker_exp["job_id"])["status"] == "queued"  # the 0.6.2 worker did not get it
    _run_worker(client, w, tmp_path, stop, seen)
    cyc = drive(ctx, lambda c: c["status"] in ("evaluating", "deploying", "monitoring") or c["status"] in MEM.TERMINAL_CYCLE,
                timeout=900)
    stop.set()
    exps = {e["backend"]: e for e in MEM.experiments(ctx, cyc["id"])}
    assert set(exps) == {"local", "worker"}, [(e["backend"], e["status"], e["error"]) for e in MEM.experiments(ctx, cyc["id"])]
    loc, wrk = exps["local"], exps["worker"]
    assert loc["candidate_version"] and wrk["candidate_version"], (loc["error"], wrk["error"])
    assert wrk["worker_id"] == w["worker_id"]
    # they really ran at the same time
    end_l = loc["started_at"] + loc["compute_seconds"]
    assert wrk["started_at"] < end_l and loc["started_at"] < wrk["started_at"] + wrk["compute_seconds"] + 60
    # the worker trained with the mask: some targets were excluded, never all
    masked = [s for s in seen if s]
    assert masked and all(0 < ones <= n for n, ones in masked) and any(ones < n for n, ones in masked)
    assert None not in seen
    tp = C.throughput(ctx)
    assert tp.get(f"worker:{w['worker_id']}", 0) > 0 and tp.get("local:cpu", 0) > 0
    st = client.get("/v1/admin/evolution/autopilot", headers=H(owner["token"])).json()
    me = next(x for x in st["workers"] if x["id"] == w["worker_id"])
    assert me["contribution"]["runs"] == 1 and me["contribution"]["tokens"] > 0
    assert me["utilization"] == {"cpu": 0.25, "memory": 0.25} and me["speed"]["basis"] == "measured"
    assert st["server"]["name"] == "MOTH Cloud (this server)" and st["server"]["contribution"]["runs"] >= 1
    print(f"cloud {loc['compute_seconds']:.1f}s + worker {wrk['compute_seconds']:.1f}s in parallel; cycle "
          f"trained in {time.time() - t0:.1f}s")


def test_placement_prefers_a_comparable_worker_and_never_waits_on_a_slow_one(client, owner, monkeypatch):
    ctx = client.app.state.ctx
    w = _enroll(client, owner)
    settings = {**S.get(ctx), "backends": {"local_cpu": True, "local_gpu": False, "workers": True}}
    monkeypatch.setattr(C, "local", lambda c: {"memory": {"available": 64 << 30, "total": 64 << 30}, "gpus": [],
                                                 "cpu_count": 4, "load_average": None, "disk": {"free": 1 << 40}})
    ctx.db.set_config("compute_throughput", {"local:cpu": 100.0, f"worker:{w['worker_id']}": 90.0})
    choice, _ = C.choose_backend(ctx, settings, 1 << 20)
    assert choice["backend"] == "worker" and choice["worker"]["basis"] == "measured"  # keeps MOTH Cloud free
    ctx.db.set_config("compute_throughput", {"local:cpu": 100.0, f"worker:{w['worker_id']}": 60.0})
    assert C.choose_backend(ctx, settings, 1 << 20)[0]["backend"] == "local"  # the server is clearly faster
    running = [{"backend": "local"}]
    exp = {"base_version": None}
    monkeypatch.setattr(EN, "_need_bytes", lambda c, e: 1 << 20)
    assert EN._free_slots(ctx, settings, running, exp)["settings"]["backends"]["workers"] is True  # 0.6× helps
    ctx.db.set_config("compute_throughput", {"local:cpu": 100.0, f"worker:{w['worker_id']}": 30.0})
    assert EN._free_slots(ctx, settings, running, exp) is None  # 0.3× would make the cycle longer
    # without measurements the benchmark is used, discounted for network transfers
    ctx.db.set_config("compute_throughput", {})
    ctx.db.set_config("local_benchmark", {"gflops": 50.0, "at": time.time()})
    client.post("/v1/worker/heartbeat", json={"hardware": {"gpus": [], "cpu_count": 2, "ram_gb": 8, "compute": "cpu",
                                                           "benchmark": {"gflops": 100.0}}, "version": "0.6.4"},
                headers=H(w["worker_token"]))
    sp = C.worker_speeds(ctx)[0]
    assert sp["basis"] == "benchmark" and sp["ratio"] == round(100.0 * C.NETWORK_FACTOR / 50.0, 3)


@pytest.mark.timeout(1200)
def test_cloud_plus_worker_finishes_a_cycle_sooner_than_cloud_alone(client, owner, tmp_path, monkeypatch):
    """Measured, same machine: the same two-experiment cycle on MOTH Cloud alone, then on MOTH Cloud plus a
    real worker. (Here the worker shares this machine's CPU; separate computers gain more.)"""
    steps = 240
    ctx = _world(client, owner, tmp_path, monkeypatch, max_experiments_per_cycle=2, retention={"models": 0},
                 monitoring={"minutes": 0.0, "min_requests": 0}, training={**FAST["training"], "steps": steps},
                 backends={"local_cpu": True, "local_gpu": False, "workers": False})

    def cycle_seconds():
        cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE or c["status"] in ("evaluating", "deploying", "monitoring"),
                    timeout=1200)
        exps = [e for e in MEM.experiments(ctx, cyc["id"]) if e["started_at"]]
        start = min(e["started_at"] for e in exps)
        end = max(e["started_at"] + e["compute_seconds"] for e in exps)
        return cyc, exps, end - start

    cyc1, exps1, alone = cycle_seconds()
    assert {e["backend"] for e in exps1} == {"local"} and len(exps1) == 2
    S.update(ctx, {"automatic": False})  # let this cycle finish without the next one starting on its own
    deadline = time.time() + 600
    while MEM.cycle(ctx, cyc1["id"])["status"] not in MEM.TERMINAL_CYCLE and time.time() < deadline:
        EN.tick(ctx)
        time.sleep(0.3)
    assert MEM.cycle(ctx, cyc1["id"])["status"] in MEM.TERMINAL_CYCLE
    w = _enroll(client, owner)
    S.update(ctx, {"automatic": True, "backends": {"local_cpu": True, "local_gpu": False, "workers": True}})
    stop, seen = threading.Event(), []
    _run_worker(client, w, tmp_path, stop, seen)
    EN.wake(ctx)
    cyc2, exps2, together = cycle_seconds()
    stop.set()
    assert cyc2["id"] != cyc1["id"] and {e["backend"] for e in exps2} == {"local", "worker"}
    tokens = lambda es: sum(int(((e["metrics"] or {}).get("training") or {}).get("tokens") or 0) for e in es)  # noqa: E731
    print(f"\nMOTH Cloud alone: {alone:.1f} s for {tokens(exps1):,} tokens ({tokens(exps1) / alone:,.0f} tokens/s); "
          f"MOTH Cloud + worker: {together:.1f} s for {tokens(exps2):,} tokens ({tokens(exps2) / together:,.0f} tokens/s); "
          f"speedup {alone / together:.2f}x")
    assert together < alone


def test_a_disconnected_workers_experiment_continues_on_moth_cloud_without_duplicates(client, owner, tmp_path, monkeypatch):
    from moth_server.db import training_jobs
    from moth_server.training import requeue_expired

    ctx = _world(client, owner, tmp_path, monkeypatch, max_experiments_per_cycle=1,
                 backends={"local_cpu": True, "local_gpu": False, "workers": True})
    w = _enroll(client, owner)
    cyc = drive(ctx, lambda c: any(e["backend"] == "worker" and e.get("job_id") for e in MEM.experiments(ctx, c["id"])),
                timeout=300)  # the comparable worker is preferred
    exp = next(e for e in MEM.experiments(ctx, cyc["id"]) if e["backend"] == "worker")
    job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    assert job["id"] == exp["job_id"]
    # the worker disappears: its lease expires and the job goes back to the queue
    with ctx.db.tx() as c:
        c.execute(training_jobs.update().where(training_jobs.c.id == job["id"]).values(lease_expires_at=time.time() - 1))
        c.execute(__import__("moth_server.db", fromlist=["workers"]).workers.update().values(last_heartbeat_at=time.time() - 3600))
    requeue_expired(ctx)
    assert EN.B.job(ctx, job["id"])["status"] == "queued"
    monkeypatch.setattr(EN, "REASSIGN_SECONDS", 0.0)
    cyc = drive(ctx, lambda c: c["status"] in ("evaluating", "deploying", "monitoring") or c["status"] in MEM.TERMINAL_CYCLE,
                timeout=600)
    exp = MEM.experiment(ctx, exp["id"])
    assert exp["backend"] == "local" and exp["candidate_version"], (exp["status"], exp["error"])
    assert EN.B.job(ctx, job["id"])["status"] == "cancelled"
    assert any(e["kind"] == "experiment.reassigned" for e in MEM.events(ctx, 100))
    # the worker comes back late: it can neither take the job again nor upload a result for it
    r = client.post(f"/v1/worker/jobs/{job['id']}/result", headers=H(w["worker_token"]),
                    files={"meta": (None, json.dumps({})), "delta": ("d", b"x")})
    assert r.status_code >= 400
