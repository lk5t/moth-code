"""Evolution 2.0 end to end with a real (tiny) MOTH model and a real dataset-library build:
curriculum mixture training, the development checkpoint carried to the next cycle, model versions,
early stopping, and Adaptive Parameter Growth with Owner approval."""

import hashlib
import io

from conftest import H, make_tiny_model
from moth_server import models as M
from moth_server.evolution import engine as EN
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S
from moth_server.evolution import v2 as V2
from test_evolution import FAST, drive

STORY = ("Once upon a time a small fox named Pip lived near a quiet river. Every morning Pip walked to the water "
         "and watched the fish swim. One day Pip found a shiny stone and gave it to a friend. ")


def _library(ctx, owner, monkeypatch):
    from moth.datafactory import catalog, fetch
    from moth_server.intelligence import library

    data = "".join(f"{STORY} On day {i} Pip counted {i * 7} birds, {i % 5} clouds and a {['red', 'blue', 'green'][i % 3]} "
                   f"kite.\n<|endoftext|>\n" for i in range(400)).encode()
    f = {"path": "s.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "role": "train"}
    src = {"id": "tiny", "repo": "t/r", "revision": "a" * 40, "format": "stories", "license": "MIT", "license_url": "",
           "attribution": "test", "name": "Tiny", "domain": "language", "description": "", "files": [f]}
    monkeypatch.setattr(catalog, "SOURCES", [src])

    class R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fetch.urllib.request, "urlopen", lambda req, timeout=None: R(data))
    bid = library.start_build(ctx, owner["user"]["id"], {"sources": ["tiny"], "holdout_fraction": 0.05,
                                                         "holdout_overrides": {}, "near_dedupe": False}, wait=True)
    assert library.latest_ready(ctx)["id"] == bid
    return bid


def _world(client, owner, tmp_path, monkeypatch):
    ctx = client.app.state.ctx
    pkg = make_tiny_model(tmp_path, 0, "moth-base")
    rel = M._register(ctx, pkg, "moth-base", {"type": "upload"}, None)
    assert M.evaluate(ctx, rel["version"])["status"] == "published"
    M.deploy(ctx, rel["version"])
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=H(owner["token"]))
    S.update(ctx, {**FAST, "max_experiments_per_cycle": 1})
    _library(ctx, owner, monkeypatch)
    return ctx, rel["version"]


def test_curriculum_cycle_dev_checkpoint_and_model_version(client, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=600)
    exps = MEM.experiments(ctx, cyc["id"])
    assert cyc["status"] == "completed", [(e["status"], e["error"]) for e in exps]
    exp = next(e for e in exps if e["status"] == "passed")
    assert exp["config"]["mixture"]["weights"] == {"language": 1.0}  # the curriculum's mixture, not one file
    gates = {g["gate"]: g for g in exp["metrics"]["gates"]}
    assert gates["target_improvement"]["passed"] and "curriculum" in gates["target_improvement"]["detail"]
    assert any(k.startswith("capability:holdout:") for k in gates)  # capability benchmarks gate promotion
    cand = M.release(ctx, cyc["candidate_version"])
    assert ctx.extras["deployed_version"] == cand["version"]
    assert cand["info"]["dev_checkpoint"]["sha256"] and cand["info"]["model_version"] == "0.1"
    assert cand["info"]["lineage_totals"]["steps"] == FAST["training"]["steps"]
    # the next cycle continues from the development checkpoint (weights + optimizer), not from scratch
    from moth_server.evolution.backends import _v2_spec

    spec = _v2_spec(cand, exp["config"], exp)
    assert spec["init_checkpoint"] == cand["info"]["dev_checkpoint"]["path"]
    assert spec["lineage"]["parent_version"] == cand["version"]
    assert MEM.lineage(ctx)[-1]["parent_version"] == base_v


def test_early_stopping_rules():
    s = {"early_stopping": {"enabled": True, "min_evals": 3, "patience": 3}}
    assert V2.early_stop_reason([3.0, 2.5, 2.2], s) is None
    assert "rose" in V2.early_stop_reason([3.0, 3.1, 3.3], s)
    assert "no held-out improvement" in V2.early_stop_reason([3.0, 2.0, 2.1, 2.05, 2.2], s)
    assert V2.early_stop_reason([3.0, 2.0], s) is None  # too early to judge


def test_parameter_growth_waits_for_approval_then_trains_a_larger_candidate(client, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    # evidence of a plateau (three cycles below 1%) without overfitting
    monkeypatch.setattr(V2, "growth_evidence", lambda ctx_, base: {"recent_improvements": [0.002, 0.001, 0.0],
                                                                  "train_loss": 3.0, "val_loss": 3.05})
    S.update(ctx, {"growth": {"approval_ratio": 1.01}})  # any growth needs the Owner here
    cyc = drive(ctx, lambda c: any(e["config"].get("method") == "expansion" for e in MEM.experiments(ctx, c["id"]))
                and (c["result"] or {}).get("waiting_reason") == "waiting for the Owner to approve a parameter expansion"
                or c["status"] in MEM.TERMINAL_CYCLE, timeout=600)
    grow = next(e for e in MEM.experiments(ctx, cyc["id"]) if e["config"].get("method") == "expansion")
    assert grow["status"] == "planned" and grow["config"]["requires_approval"]
    assert grow["config"]["grow"]["params_after"] > grow["config"]["grow"]["params_before"]
    o = H(owner["token"])
    assert client.post(f"/v1/admin/evolution/experiments/{grow['id']}/approve", headers=o).status_code == 200
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=900)
    grow = MEM.experiment(ctx, grow["id"])
    assert grow["status"] in ("passed", "rejected"), grow["error"]
    cand = M.release(ctx, grow["candidate_version"])
    assert cand["info"]["params"] == grow["config"]["grow"]["params_after"]  # the model really grew
    assert MEM.lineage(ctx)[-1]["method"] in ("expansion", "continued")
    stable = M.deployed(ctx)
    if grow["status"] == "rejected":  # an unsuccessful expansion never touches the stable model
        assert stable["version"] != cand["version"]
    assert any(e["kind"] == "experiment.approved" for e in MEM.events(ctx, 200))


def test_distributed_rounds_across_two_real_workers_with_recovery(client, owner, tmp_path, monkeypatch):
    """One experiment trained by two MOTH workers in rounds (real training in the real worker runner):
    verified deltas averaged per round, a duplicate submission refused, a disconnected worker's shard
    taken over after its lease expired, contributions credited per worker."""
    from sqlalchemy import select

    from moth_server.db import training_jobs, workers
    from moth_server.training import requeue_expired
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True},
                   "training": {"steps": 20, "lr": 3e-3}, "distributed": {"min_participants": 2, "rounds": 2}})
    o = H(owner["token"])
    runners = []
    for name in ("cpu-box-1", "cpu-box-2"):
        e = client.post("/v1/training/enrollments", json={"name": name}, headers=o).json()
        w = client.post("/v1/worker/enroll", json={"token": e["token"], "version": "0.5.3", "hardware": {
            "gpus": [], "cpu_count": 4, "ram_gb": 16.0, "compute": "cpu", "machine_id": name}}).json()
        r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / name,
                         log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None)
        r.beat()
        runners.append((w, r))
    for _ in range(4):
        EN.tick(ctx)
    exp = next(e for e in MEM.experiments(ctx) if e["backend"] == "distributed")
    st = exp["resources"]["distributed"]
    assert st["shards"] == 2 and st["rounds"] == 2 and st["local_steps"] == 10
    # round 0: each worker trains its own shard
    for w, r in runners:
        job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
        assert job["kind"] == "dist_shard" and job["spec"]["dist"]["round"] == 0
        assert r.run_job(job)["accepted"]
    # the same shard submitted again is refused (no step counted twice)
    from moth_server.evolution.distributed import accept_shard

    done_job = ctx.db.one(select(training_jobs).where(training_jobs.c.kind == "dist_shard",
                                                      training_jobs.c.status == "completed"))
    import io as _io

    import torch
    from moth.community.validation import serialize_state, tensor_bytes_sha256

    payload = serialize_state({"x": torch.zeros(1)})
    dup = accept_shard(ctx, done_job, {"base_sha256": json_spec(done_job)["base_sha256"],
                                       "delta_sha256": tensor_bytes_sha256(payload)}, payload)
    assert not dup["accepted"] and any("already submitted" in x or "round 0 is over" in x for x in dup["reasons"])
    EN.tick(ctx)
    exp = MEM.experiment(ctx, exp["id"])
    st = exp["resources"]["distributed"]
    assert st["round"] == 1 and st["history"][0]["participants"] == 2 and len(st["history"][0]["contributors"]) == 2
    # round 1: worker 1 takes a shard and disconnects; after its lease expires worker 2 finishes both
    w1, r1 = runners[0]
    w2, r2 = runners[1]
    lost = client.post("/v1/worker/jobs/claim", headers=H(w1["worker_token"])).json()
    with ctx.db.tx() as c:
        c.execute(training_jobs.update().where(training_jobs.c.id == lost["id"]).values(lease_expires_at=0))
    requeue_expired(ctx)
    for _ in range(2):
        job = client.post("/v1/worker/jobs/claim", headers=H(w2["worker_token"])).json()
        assert job["spec"]["dist"]["round"] == 1
        assert r2.run_job(job)["accepted"]
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE or c["status"] in ("evaluating", "deploying",
                                                                                  "monitoring"), timeout=600)
    exp = MEM.experiment(ctx, exp["id"])
    st = exp["resources"]["distributed"]
    assert st["round"] == 2 and [h["participants"] for h in st["history"]] == [2, 2]
    assert exp["status"] in ("trained", "evaluating", "passed", "rejected") and exp["candidate_version"]
    cand = M.release(ctx, exp["candidate_version"])
    assert cand["info"]["training"]["backend"] == "distributed"
    ws = {w["id"]: w for w in ctx.db.all(select(workers))}
    assert ws[w1["worker_id"]]["verified_jobs"] == 1 and ws[w2["worker_id"]]["verified_jobs"] == 3
    assert ws[w2["worker_id"]]["trained_tokens"] > ws[w1["worker_id"]]["trained_tokens"] > 0


def json_spec(job):
    import json

    return json.loads(job["spec"])


def test_moth_code_contributes_its_computer_to_the_same_experiment(client, owner, tmp_path, monkeypatch):
    """MOTH Code enrolls its own computer with the signed-in account and trains a shard of the same
    distributed experiment as a standalone MOTH worker; the Owner sees both contributions."""
    import time as _time

    from moth.community.participant import Participant
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True},
                   "training": {"steps": 10, "lr": 3e-3}, "distributed": {"min_participants": 2, "rounds": 1}})
    o = H(owner["token"])
    settings_store: dict = {}

    class Http:  # the participant's HTTP client: the test server
        def __init__(self, base):
            pass

        def __enter__(self):
            return client

        def __exit__(self, *a):
            return False

    import moth_worker.client as wc

    real_init = wc.WorkerClient.__init__
    monkeypatch.setattr(wc.WorkerClient, "__init__", lambda self, server, token=None, http=None, timeout=120:
                        real_init(self, server, token, http=client, timeout=timeout))
    p = Participant(tmp_path / "app", account=lambda: {"server_url": "http://testserver", "token": owner["token"]},
                    get_setting=settings_store.get, set_setting=settings_store.__setitem__,
                    publish=lambda *a: None, http_factory=Http)
    st = p.enable()
    assert st["enabled"] and st["worker_id"]
    # a standalone MOTH worker joins too
    e = client.post("/v1/training/enrollments", json={"name": "ubuntu-cpu"}, headers=o).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "version": "0.5.3", "hardware": {
        "gpus": [], "cpu_count": 4, "ram_gb": 16.0, "compute": "cpu", "machine_id": "ubuntu"}}).json()
    worker = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / "w",
                          log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None)
    worker.beat()
    deadline = _time.time() + 120
    while _time.time() < deadline and not any(x.get("backend") == "distributed" for x in MEM.experiments(ctx)):
        EN.tick(ctx)
        _time.sleep(0.5)
    job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    assert job["kind"] == "dist_shard" and worker.run_job(job)["accepted"]
    deadline = _time.time() + 300  # MOTH Code's own loop picks up the other shard by itself
    while _time.time() < deadline:
        c = client.get("/v1/admin/evolution/contributions", headers=o).json()["experiment"]
        if c and c["round"] == 1:
            break
        EN.tick(ctx)
        _time.sleep(1)
    p.stop()
    c = client.get("/v1/admin/evolution/contributions", headers=o).json()["experiment"]
    assert c["round"] == 1, c
    names = {x["name"]: x for x in c["contributors"]}
    assert set(names) == {"MOTH Code on this computer", "ubuntu-cpu"} and names["MOTH Code on this computer"]["this_app"]
    assert all(x["tokens"] > 0 for x in c["contributors"])


def test_cpu_workers_evaluate_candidates_with_two_independent_results(client, owner, tmp_path, monkeypatch):
    """While training runs elsewhere, two CPU workers measure the candidate's held-out losses; the result
    is used only because both agree, and is stored as the suite's report."""
    import time as _time

    from sqlalchemy import select

    from moth_server.db import evaluation_reports, training_jobs
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    import moth_worker

    monkeypatch.setattr(moth_worker, "__version__", "0.5.3")  # evaluation jobs need MOTH Worker 0.5.3+
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    S.update(ctx, {"backends": {"local_cpu": True, "local_gpu": False, "workers": False},
                   "distributed": {"enabled": False, "eval_on_workers": True, "eval_wait_minutes": 10}})
    o = H(owner["token"])
    runners = []
    for name in ("eval-1", "eval-2"):
        e = client.post("/v1/training/enrollments", json={"name": name}, headers=o).json()
        w = client.post("/v1/worker/enroll", json={"token": e["token"], "version": "0.5.3", "hardware": {
            "gpus": [], "cpu_count": 4, "ram_gb": 16.0, "compute": "cpu", "machine_id": name}}).json()
        r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / name,
                         log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None)
        r.beat()
        runners.append((w, r))
    deadline = _time.time() + 600
    while _time.time() < deadline:
        EN.tick(ctx)
        for w, r in runners:
            r.beat()
        if ctx.db.one(select(training_jobs).where(training_jobs.c.kind == "eval_loss")):
            break
        _time.sleep(0.5)
    jobs = ctx.db.all(select(training_jobs).where(training_jobs.c.kind == "eval_loss"))
    assert len(jobs) == 2, (MEM.cycles(ctx, 1), [m["message"] for m in MEM.events(ctx, 12)])  # two replicas
    for w, r in runners:
        job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
        assert job["kind"] == "eval_loss"
        assert r.run_job(job)["accepted"]
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=600)
    exp = next(e for e in MEM.experiments(ctx, cyc["id"]) if e["candidate_version"])
    rep = ctx.db.one(select(evaluation_reports).where(evaluation_reports.c.model_version == exp["candidate_version"],
                                                      evaluation_reports.c.suite == "capability:holdout:language"))
    import json as _json

    m = _json.loads(rep["metrics"])
    assert sorted(m["computed_by"]) == sorted(w["worker_id"] for w, _ in runners)
    assert exp["metrics"]["remote_eval"]["accepted"] == ["capability:holdout:language"]
    assert any(g["gate"] == "capability:holdout:language" for g in exp["metrics"]["gates"])


def test_progress_dashboard_and_timeline_from_measurements(client, settings, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=600)
    from conftest import register_verified

    t = register_verified(client, settings, "viewer")["token"]
    p = client.get("/v1/intelligence/progress", headers=H(t)).json()
    assert [v["version"] for v in p["timeline"]] == [base_v, cyc["candidate_version"]]
    cur = p["current"]
    assert cur["model_version"] == "0.1" and cur["stable"] and cur["has_dev_checkpoint"]
    assert "capability:holdout:language" not in cur["benchmarks"] and "holdout_language" in cur["benchmarks"]
    assert p["development"]["version"] == cyc["candidate_version"]
    assert p["training"]["experiments"]
    experiment = p["training"]["experiments"][0]
    stored = MEM.experiment(ctx, experiment["id"])
    assert experiment["status"] == stored["status"]
    assert experiment["metrics"] == stored["metrics"]
    assert experiment["metrics"]["training"]["batch_tuning"]["effective_batch_size"] == 8
    assert p["datasets"]["sources"][0]["license"] == "MIT" and p["timeline"][1]["datasets"][0]["build"]
