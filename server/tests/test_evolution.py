"""Model evolution end to end, with a real (tiny) MOTH model.

Real: dataset preparation, continued training in a separate process (forward/backward passes,
checkpoints, resume), candidate packaging, benchmark subprocesses, the release gate, deployment with
an inference health check, chat requests, worker jobs through the real MOTH worker runner, and the
database. Simulated (and named so in each test): resource shortage (reported free memory), inference
errors after a deployment, and "too many failures".
"""

import io
import json
import os
import signal
import time
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from conftest import H, make_tiny_model, register_verified
from moth_server import models as M
from moth_server.app import create_app
from moth_server.db import evaluation_reports, model_lineage, training_jobs
from moth_server.evolution import compute as C
from moth_server.evolution import engine as EN
from moth_server.evolution import memory as MEM
from moth_server.evolution import planner as P
from moth_server.evolution import settings as S

FAST = {
    "training": {"steps": 60, "lr": 3e-3, "batch_size": 8, "seq_len": 64, "eval_interval": 20, "checkpoint_interval": 20},
    "min_dataset_tokens": 2000, "max_experiments_per_cycle": 1,
    "backends": {"local_gpu": False, "local_cpu": True, "workers": False},
    "limits": {"cpu_threads": 2, "min_free_memory_gb": 0.05, "min_free_disk_gb": 0.05},
    "schedule": {"max_requests_per_minute": 10_000},
    "gates": {"max_speed_regression": 0.9, "max_memory_growth": 5.0},
    "monitoring": {"minutes": 0.0},
}


def stdlib_corpus(n=60) -> bytes:
    """Real, diverse Python (PSF-2.0): standard-library modules *not* in the built-in evaluation sample."""
    import sysconfig
    from pathlib import Path

    from moth_server.evalsets import BUILTIN_FILES

    root = Path(sysconfig.get_paths()["stdlib"])
    skip = {Path(f).name for f in BUILTIN_FILES}
    files = [p for p in sorted(root.glob("*.py")) if p.name not in skip and 4_000 < p.stat().st_size < 60_000][:n]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in files:
            z.writestr(f"stdlib/{p.name}", p.read_text(encoding="utf-8", errors="replace"))
        z.writestr("stdlib/.env", "SECRET_KEY=do-not-train-on-me\n")  # secret-looking files are never included
    return buf.getvalue()


def code_corpus(n=160) -> bytes:
    """Narrow synthetic code: learning it well makes a small model forget general Python."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(n):
            z.writestr(f"src/mod_{i}.py", "".join(
                f"def func_{i}_{j}(x, y):\n    total = x + y * {j}\n    if total > {i}:\n        return total - {j}\n"
                f"    return total\n\n\n" for j in range(6)))
        z.writestr("src/.env", "SECRET_KEY=do-not-train-on-me\n")  # secret-looking files are never included
    return buf.getvalue()


@pytest.fixture
def world(client, settings, owner, tmp_path):
    ctx = client.app.state.ctx
    o = H(owner["token"])
    pkg = make_tiny_model(tmp_path, 0, "moth-base")
    rel = M._register(ctx, pkg, "moth-base", {"type": "upload"}, None)
    assert M.evaluate(ctx, rel["version"])["status"] == "published"
    M.deploy(ctx, rel["version"])
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=o)
    S.update(ctx, FAST)
    return {"ctx": ctx, "o": o, "base": rel["version"]}


def add_dataset(client, o, name="python stdlib", corpus=None, license="PSF-2.0", **form):
    r = client.post("/v1/admin/evolution/datasets", headers=o,
                    data={"name": name, "license": license, "tags": "code", **form},
                    files={"file": ("corpus.zip", corpus or stdlib_corpus(), "application/zip")})
    assert r.status_code == 200, r.text
    return r.json()


def drive(ctx, until, timeout=240.0, sleep=0.3):
    """Tick the engine (as the background thread would) until ``until(cycle)`` is true."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        EN.tick(ctx)
        cyc = MEM.cycles(ctx, 1)[0] if MEM.cycles(ctx, 1) else None
        if cyc and until(cyc):
            return cyc
        time.sleep(sleep)
    raise AssertionError(f"timed out; last cycle: {MEM.cycles(ctx, 1)}; events: "
                         f"{[e['message'] for e in MEM.events(ctx, 15)]}")


def chat(client, settings, user=None):
    import uuid

    tok = register_verified(client, settings, user or f"user_{uuid.uuid4().hex[:8]}")["token"]
    name = client.get("/cloud/v1/health").json()["models"][0]["name"]
    r = client.post("/cloud/v1/chat", headers=H(tok), json={"model": name, "messages": [{"role": "user",
                    "content": "def add("}], "params": {"max_new_tokens": 4, "temperature": 0}})
    assert r.status_code == 200
    return json.loads(r.text.splitlines()[-1])


# ---- 1, 2, 6, 7, 8, 11, 13, 14: the complete cycle -------------------------------------------------------
def test_full_cycle_continued_training_to_deployment(client, settings, world):
    ctx, o = world["ctx"], world["o"]
    # without approved data nothing trains (and nothing pretends to)
    assert EN.tick(ctx)["state"] == "idle"
    d = add_dataset(client, o)
    assert d["status"] == "pending" and d["sources"][0]["license"] == "PSF-2.0" and d["tokens_train"] > 2000
    assert "corpus.zip" in d["sources"][0]["kind"] or d["sources"][0]["kind"] == "upload"
    assert EN.tick(ctx)["state"] in ("idle", "scheduled") and MEM.active_cycle(ctx) is None  # pending data unused
    r = client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # the cycle: plan → train (real subprocess) → evaluate → deploy → monitor → completed
    seen = set()
    cyc = drive(ctx, lambda c: seen.add(c["status"]) or c["status"] in MEM.TERMINAL_CYCLE)
    assert cyc["status"] == "completed", json.dumps([e["metrics"].get("gates") for e in MEM.experiments(ctx)],
                                                    indent=1, default=str)
    assert "training" in seen
    exp = MEM.experiments(ctx, cyc["id"])[0]
    assert exp["status"] == "passed" and exp["backend"] == "local" and exp["compute_seconds"] > 0
    assert exp["config"]["method"] == "continued" and exp["config"]["base_version"] == world["base"]
    assert exp["metrics"]["training"]["step"] == 60
    gates = {g["gate"]: g for g in exp["metrics"]["gates"]}
    assert gates["target_improvement"]["passed"] and gates["target_improvement"]["change"] >= 0.005
    assert gates["release_checks"]["passed"] and "code_syntax" in gates and "speed" in gates
    assert any(k.startswith("heldout:") for k in gates)  # retention on the general evaluation set
    new = cyc["candidate_version"]
    # a new version: the base model was not overwritten and stays available for rollback
    assert ctx.extras["deployed_version"] == new and new != world["base"]
    assert M.release(ctx, world["base"])["status"] == "published"
    lin = ctx.db.one(select(model_lineage).where(model_lineage.c.version == new))
    assert lin["parent_version"] == world["base"] and lin["method"] == "continued" and lin["cycle_id"] == cyc["id"]
    assert ctx.db.all(select(evaluation_reports).where(evaluation_reports.c.model_version == world["base"]))
    # the new model really serves chat (desktop API unchanged)
    assert chat(client, settings)["stats"]["generated_tokens"] > 0
    # dashboard APIs
    st = client.get("/v1/admin/evolution/status", headers=o).json()
    assert st["active_model"]["version"] == new and st["active_model"]["parent_version"] == world["base"]
    assert st["stable_model"]["version"] == new and st["comparison"]["candidate_version"] == new
    vs = client.get("/v1/admin/evolution/versions", headers=o).json()
    assert next(v for v in vs["versions"] if v["version"] == world["base"])["can_rollback"]
    res = client.get("/v1/admin/evolution/resources", headers=o).json()
    assert res["local"]["memory"]["total"] > 0 and res["local"]["disk"]["total"] > 0 and "cpu" in res["local"]["backends"]
    log = client.get(f"/v1/admin/evolution/experiments/{exp['id']}/log", headers=o).json()["lines"]
    assert any('"split": "val"' in l for l in log)
    assert not any("do-not-train-on-me" in l for l in log)
    # training memory: the same experiment on the same base and data is never repeated
    plan = P.plan(ctx, M.release(ctx, world["base"]), S.get(ctx), 0)
    assert any(exp["config_hash"] == s["config_hash"] for s in plan["skipped"])
    # Owner rollback to the previous version (health-checked switch)
    r = client.post("/v1/admin/evolution/rollback", json={"version": world["base"]}, headers=o)
    assert r.status_code == 200 and ctx.extras["deployed_version"] == world["base"]


# ---- 3, 4, 12: pausing for resources, crash/restart, resumption from the checkpoint ----------------------
def test_pause_on_resource_shortage_crash_and_resume(client, settings, world, monkeypatch):
    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {"training": {"steps": 400, "checkpoint_interval": 10}})
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    drive(ctx, lambda c: c["status"] == "training", timeout=60)
    exp = MEM.experiments(ctx)[0]
    run_dir = settings.data_dir / "evolution" / "runs" / f"exp-{exp['id']:05d}"
    deadline = time.time() + 60
    while not list((run_dir / "checkpoints").glob("step_*.pt")) and time.time() < deadline:
        time.sleep(0.3)
    # SIMULATED shortage: the server reports almost no free memory → training pauses with a checkpoint
    real_local = C.local
    monkeypatch.setattr(C, "local", lambda ctx: {**real_local(ctx), "memory": {"total": 8 << 30, "available": 1 << 20}})
    EN.tick(ctx)
    exp = MEM.experiment(ctx, exp["id"])
    assert exp["status"] == "paused" and "free memory" in exp["error"]
    assert json.loads((run_dir / "result.json").read_text())["reason"] == "stopped"
    paused_at = json.loads((run_dir / "checkpoints" / "latest.json").read_text())["file"]
    EN.tick(ctx)
    assert MEM.experiment(ctx, exp["id"])["status"] == "paused"  # stays paused while resources are short
    assert client.get("/v1/admin/evolution/status", headers=o).json()["cycle"]["status"] == "waiting_for_compute"
    monkeypatch.setattr(C, "local", real_local)
    EN.tick(ctx)
    exp = MEM.experiment(ctx, exp["id"])
    assert exp["status"] == "running"
    # the training process crashes (killed); a new server process takes over after a restart
    time.sleep(1.0)
    os.killpg(exp["resources"]["pid"], signal.SIGKILL)
    time.sleep(0.5)
    with TestClient(create_app(settings, extras={"synchronous_jobs": True, "disable_background": True})) as c2:
        ctx2 = c2.app.state.ctx
        EN.tick(ctx2)
        e2 = MEM.experiment(ctx2, exp["id"])
        assert e2["status"] == "paused" and "unexpectedly" in e2["error"]
        cyc = drive(ctx2, lambda c: c["status"] in MEM.TERMINAL_CYCLE or c["status"] in ("evaluating", "deploying",
                                                                                      "monitoring"), timeout=300)
        result = json.loads((run_dir / "result.json").read_text())
        assert result["resumed"] is True and result["step"] == 400
        events = [e["kind"] for e in MEM.events(ctx2, 200)]
        assert "experiment.paused" in events and "experiment.interrupted" in events and "experiment.resumed" in events
        assert cyc["id"]


# ---- inference stays available while training -----------------------------------------------------------
def test_inference_available_during_training(client, settings, world):
    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {"training": {"steps": 300}})
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    drive(ctx, lambda c: c["status"] == "training", timeout=60)
    assert MEM.experiments(ctx)[0]["status"] == "running"
    t0 = time.time()
    assert chat(client, settings)["stats"]["generated_tokens"] > 0
    assert time.time() - t0 < 30
    EN.cancel_cycle(ctx)
    assert MEM.experiments(ctx)[0]["status"] == "cancelled"


# ---- no suitable hardware: queued, never "training" ---------------------------------------------------
def test_without_compute_training_waits_and_says_why(client, settings, world):
    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": True, "workers": True}})
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    for _ in range(3):
        EN.tick(ctx)
    st = client.get("/v1/admin/evolution/status", headers=o).json()
    assert st["cycle"]["status"] == "waiting_for_compute"
    exp = st["cycle"]["experiments"][0]
    assert exp["status"] == "waiting" and exp["progress"].get("step", 0) == 0
    reason = st["cycle"]["result"]["waiting_reason"]
    assert "no GPU" in reason and "no MOTH workers" in reason and "CPU training" in reason
    assert chat(client, settings)["stats"]["generated_tokens"] > 0  # inference unaffected


# ---- worker backend (existing worker software) ---------------------------------------------------------
def test_experiment_runs_on_a_moth_worker(client, settings, world, tmp_path):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True},
                   "training": {"steps": 40, "lr": 3e-3}})
    client.put("/v1/admin/config/flags", json={"allow_cpu_workers": True}, headers=o)
    e = client.post("/v1/training/enrollments", json={"name": "w1"}, headers=o).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": []}, "version": "0.3.2"}).json()
    runner = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / "w1", allow_cpu=True,
                          log=lambda m: None, heartbeat_seconds=3600)
    runner.beat()
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    for _ in range(3):
        EN.tick(ctx)
    job = ctx.db.one(select(training_jobs).where(training_jobs.c.kind == "evolve_train"))
    assert job and job["status"] == "queued"
    claimed = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    assert claimed["kind"] == "evolve_train"
    outcome = runner.run_job(claimed)
    assert outcome["accepted"], outcome
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE)
    exp = MEM.experiments(ctx, cyc["id"])[0]
    assert exp["backend"] == "worker" and exp["candidate_version"]
    assert exp["status"] in ("passed", "rejected") and exp["metrics"]["gates"]
    lin = ctx.db.one(select(model_lineage).where(model_lineage.c.version == exp["candidate_version"]))
    assert lin["parent_version"] == world["base"]


# ---- 6, 7: catastrophic forgetting is detected even when the target data improves -------------------------
def test_forgetting_is_detected_even_when_the_training_data_improves(client, settings, world):
    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {"training": {"steps": 80}})
    d = add_dataset(client, o, name="narrow synthetic code", corpus=code_corpus(), license="MIT")
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE)
    assert cyc["status"] == "rejected"
    exp = MEM.experiments(ctx, cyc["id"])[0]
    gates = {g["gate"]: g for g in exp["metrics"]["gates"]}
    assert gates["target_improvement"]["passed"]  # it learned its training data (lower loss there)...
    assert not gates["heldout:builtin-python-stdlib"]["passed"]  # ...but forgot general Python
    assert ctx.extras["deployed_version"] == world["base"]  # nothing was deployed
    cand = M.release(ctx, exp["candidate_version"])
    assert cand["status"] in ("evaluated", "failed") and "evolution" in (cand["error"] or "") or cand["status"] == "evaluated"


# ---- 7, 9: regression detection and rollback after a failed deployment --------------------------------
def test_degraded_candidate_is_rejected_and_never_deployed(client, settings, world, tmp_path):
    import torch

    from moth_server.evolution import evaluation as EV
    from moth_server.evolution.backends import register_candidate

    ctx, o = world["ctx"], world["o"]
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    EN.tick(ctx)  # creates a cycle and plans an experiment
    exp = MEM.experiments(ctx)[0]
    EN.cancel_cycle(ctx)
    # a "trained" model that is actually much worse: the base weights plus large noise
    base = M.release(ctx, world["base"])
    bad = tmp_path / "bad"
    import shutil

    shutil.copytree(base["path"], bad)
    state = torch.load(bad / "model.pt", weights_only=True)
    torch.manual_seed(1)
    torch.save({k: v + torch.randn_like(v) * 2.0 if v.is_floating_point() else v for k, v in state.items()}, bad / "model.pt")
    from moth.model.registry import sha256_file

    man = json.loads((bad / "manifest.json").read_text())
    man["sha256"] = sha256_file(bad / "model.pt")
    (bad / "manifest.json").write_text(json.dumps(man))
    cand = register_candidate(ctx, exp, bad)
    verdict = EV.gate(ctx, cand, base, d | {"sha256": d["sha256"]}, S.get(ctx))
    assert not verdict["passed"]
    assert not next(g for g in verdict["gates"] if g["gate"] == "target_improvement")["passed"]
    assert ctx.extras["deployed_version"] == world["base"]


def test_failing_deployment_is_rolled_back_automatically(client, settings, world):
    ctx, o = world["ctx"], world["o"]
    S.update(ctx, {"monitoring": {"minutes": 60.0, "min_requests": 5, "max_error_rate": 0.05}})
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    cyc = drive(ctx, lambda c: c["status"] == "monitoring" or c["status"] in MEM.TERMINAL_CYCLE)
    assert cyc["status"] == "monitoring", [e["message"] for e in MEM.events(ctx, 20)]
    cand = cyc["candidate_version"]
    assert ctx.extras["deployed_version"] == cand
    EN.tick(ctx)
    assert MEM.cycle(ctx, cyc["id"])["status"] == "monitoring"  # healthy so far
    st = client.get("/v1/admin/evolution/status", headers=o).json()
    assert st["active_model"]["version"] == cand and st["stable_model"]["version"] == world["base"]  # not yet stable
    # SIMULATED production failures of the new model: 6 of 8 requests fail
    act = C.activity(ctx)
    for ok in (False, False, True, False, False, True, False, False):
        act.start()
        act.finish(cand, ok, 0.1, 4 if ok else 0)
    EN.tick(ctx)
    cyc = MEM.cycle(ctx, cyc["id"])
    assert cyc["status"] == "rolled_back" and "error rate" in cyc["error"]
    assert ctx.extras["deployed_version"] == world["base"]  # the previous stable model serves again
    assert M.release(ctx, cand)["status"] == "failed"
    assert chat(client, settings)["stats"]["generated_tokens"] > 0
    assert EN.state(ctx)["consecutive_failures"] == 1


def test_repeated_failures_pause_evolution(client, settings, world):
    ctx = world["ctx"]
    S.update(ctx, {"max_consecutive_failures": 2})
    EN._schedule_next(ctx, failed=True)
    first = EN.state(ctx)["next_cycle_at"]
    EN._schedule_next(ctx, failed=True)
    st = EN.state(ctx)
    assert st["consecutive_failures"] == 2 and st["next_cycle_at"] > first  # exponential back-off
    assert S.get(ctx)["paused"] is True
    assert any(e["kind"] == "engine.paused" for e in MEM.events(ctx, 10))
    assert EN.tick(ctx)["state"] == "paused"


# ---- data permissions -------------------------------------------------------------------------------------
def test_training_data_requires_license_approval_and_user_permission(client, settings, world):
    o = world["o"]
    r = client.post("/v1/admin/evolution/datasets", headers=o, data={"name": "x", "license": " "},
                    files={"file": ("a.zip", code_corpus(), "application/zip")})
    assert r.status_code == 422 and "license" in r.json()["detail"]
    d = add_dataset(client, o, name="support chats", contains_user_data="true")
    assert d["contains_user_data"]
    r = client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    assert r.status_code == 422 and "explicit permission" in r.json()["detail"]
    r = client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={"user_data_permission": True}, headers=o)
    assert r.status_code == 200
    ctx = world["ctx"]
    EN.tick(ctx)  # plans the cycle's experiment on the approved data
    assert MEM.active_cycle(ctx) and MEM.experiments(ctx)[0]["status"] in ("planned", "running", "waiting")
    r = client.post(f"/v1/admin/evolution/datasets/{d['id']}/revoke", headers=o).json()
    assert r["status"] == "revoked" and r["experiments_cancelled"] == 1  # unfinished work on it stops
    EN.tick(ctx)
    assert MEM.experiments(ctx)[0]["status"] == "cancelled" and MEM.active_cycle(ctx) is None
    EN._set_state(ctx, next_cycle_at=0)
    assert EN.tick(ctx)["state"] == "idle"  # revoked data is never used again
    # no listing exposes dataset contents or server paths
    listed = client.get("/v1/admin/evolution/datasets", headers=o).text
    assert "path" not in json.loads(listed)[0] and "def func_" not in listed


# ---- authorization ---------------------------------------------------------------------------------------
def test_evolution_api_is_owner_only_and_sensitive_actions_need_reauth(client, settings, world):
    ctx, o = world["ctx"], world["o"]
    user = register_verified(client, settings, "not_owner")["token"]
    for path in ("status", "resources", "datasets", "versions", "cycles", "events"):
        assert client.get(f"/v1/admin/evolution/{path}", headers=H(user)).status_code == 403
    assert client.post("/v1/admin/evolution/run", headers=H(user)).status_code == 403
    assert client.get("/v1/admin/evolution/status").status_code == 401
    from moth_server.db import sessions

    with ctx.db.tx() as c:
        c.execute(sessions.update().values(reauth_at=0))
    r = client.put("/v1/admin/evolution/settings", json={"changes": {"interval_hours": 2}}, headers=o)
    assert r.status_code == 428
    assert client.post("/v1/admin/evolution/rollback", json={"version": world["base"]}, headers=o).status_code == 428
    assert client.get("/v1/admin/evolution/status", headers=o).status_code == 200  # reading needs no re-auth


def test_settings_are_validated(client, settings, world):
    ctx = world["ctx"]
    with pytest.raises(S.SettingsError):
        S.update(ctx, {"training": {"lr": 5.0}})
    with pytest.raises(S.SettingsError):
        S.update(ctx, {"schedule": {"quiet_hours_utc": [25, 3]}})
    with pytest.raises(S.SettingsError):
        S.update(ctx, {"unknown_thing": 1})
    assert S.update(ctx, {"schedule": {"quiet_hours_utc": [1, 6]}})["schedule"]["quiet_hours_utc"] == [1, 6]


# ---- 10: migration from the installed 0.3.x schema ------------------------------------------------------
def test_migration_from_schema_2_keeps_everything_and_records_lineage(settings, tmp_path):
    from moth_server.db import Database

    with TestClient(create_app(settings, extras={"synchronous_jobs": True, "disable_background": True})) as c:
        ctx = c.app.state.ctx
        pkg = make_tiny_model(tmp_path, 3, "legacy")
        rel = M._register(ctx, pkg, "legacy", {"type": "upload"}, None)
    # turn the database back into what a 0.3.2 server has: schema 2, no evolution tables
    db = Database(settings.db_url)
    with db.engine.begin() as conn:
        for t in ("evolution_events", "evolution_experiments", "evolution_cycles", "evaluation_reports",
                  "model_lineage", "training_datasets"):
            conn.execute(text(f"DROP TABLE {t}"))
        conn.execute(text("DELETE FROM schema_version"))
        conn.execute(text("INSERT INTO schema_version (version) VALUES (2)"))
    assert db.pending_migrations()[0]["version"] == 3 and not db.pending_migrations()[0]["destructive"]
    db.engine.dispose()
    with TestClient(create_app(settings, extras={"synchronous_jobs": True, "disable_background": True})) as c:
        ctx = c.app.state.ctx
        from moth_server.db import SCHEMA_VERSION

        assert ctx.db.schema_version() == SCHEMA_VERSION
        kept = M.release(ctx, rel["version"])
        assert kept["sha256"] == rel["sha256"] and kept["status"] == rel["status"]
        lin = ctx.db.one(select(model_lineage).where(model_lineage.c.version == rel["version"]))
        assert lin["method"] == "upload" and lin["parent_version"] is None
