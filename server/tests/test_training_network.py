import json
import time

import pytest
from sqlalchemy import select

from conftest import H, register_verified
from moth_server.db import referral_rewards, training_jobs, workers
from moth_worker.client import ServerError, WorkerClient
from moth_worker.runner import Stop, WorkerRunner

HW_CPU = {"gpus": [], "cpu_count": 4, "os": "Linux test"}
HW_GPU = {"gpus": [{"name": "NVIDIA GeForce RTX 3060", "memory_gb": 12.0, "driver": "560"}], "cuda": "12.6"}


def enroll(client, token, hw=HW_CPU, name=None, referral=None):
    r = client.post("/v1/training/enrollments", json={"name": name, "referral_code": referral}, headers=H(token))
    assert r.status_code == 200, r.text
    e = r.json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": hw, "version": "0.2.0"})
    assert w.status_code == 200, w.text
    return e, w.json()


def runner(client, wtoken, tmp_path, name="w"):
    return WorkerRunner(WorkerClient("http://test", wtoken, http=client), tmp_path / name, allow_cpu=True,
                        log=lambda m: None, heartbeat_seconds=3600)


def test_enrollment_tokens_are_single_use_and_expire(client, settings):
    t = register_verified(client, settings, "gpu_owner")["token"]
    e = client.post("/v1/training/enrollments", json={"name": "rtx3060"}, headers=H(t)).json()
    assert e["single_use"] and e["command"] is None and "moth-worker enroll" in e["manual_command"]
    ok = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": HW_GPU})
    assert ok.status_code == 200 and ok.json()["worker_token"].startswith("mw_")
    again = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": HW_GPU})
    assert again.status_code == 400
    e2 = client.post("/v1/training/enrollments", json={}, headers=H(t)).json()
    from moth_server.db import enrollment_tokens
    db = client.app.state.ctx.db
    with db.tx() as c:
        c.execute(enrollment_tokens.update().values(expires_at=0))
    assert client.post("/v1/worker/enroll", json={"token": e2["token"], "hardware": HW_GPU}).status_code == 400
    listing = client.get("/v1/training/workers", headers=H(t)).json()
    assert listing["workers"][0]["name"] == "rtx3060"
    assert listing["workers"][0]["hardware"]["gpus"][0]["memory_gb"] == 12.0


def test_install_command_pins_release_checksum(client, settings, tmp_path):
    import hashlib

    t = register_verified(client, settings, "pin")["token"]
    d = settings.storage_dir / "worker"
    d.mkdir(parents=True)
    (d / "moth-worker-0.2.0.tar.gz").write_bytes(b"release-bytes")
    sha = hashlib.sha256(b"release-bytes").hexdigest()
    (d / "manifest.json").write_text(json.dumps({"version": "0.2.0", "file": "moth-worker-0.2.0.tar.gz", "sha256": sha}))
    e = client.post("/v1/training/enrollments", json={}, headers=H(t)).json()
    assert f"echo '{sha}  moth-worker-0.2.0.tar.gz' | sha256sum -c -" in e["command"]  # Linux
    assert f"echo '{sha}  moth-worker-0.2.0.tar.gz' | shasum -a 256 -c -" in e["command"]  # macOS
    assert e["token"] in e["command"] and "curl -fsSLO https://moth.test/downloads/worker/" in e["command"]
    assert sha.upper() in e["windows_command"] and e["token"] in e["windows_command"]  # Windows
    assert "Get-FileHash" in e["windows_command"] and "install.ps1" in e["windows_command"]
    assert client.get("/downloads/worker/moth-worker-0.2.0.tar.gz").content == b"release-bytes"
    assert client.get("/downloads/worker/other.tar.gz").status_code == 404


def test_credentials_are_isolated(client, settings, training_world):
    t = register_verified(client, settings, "iso")["token"]
    _, w = enroll(client, t)
    wt = w["worker_token"]
    assert client.get("/v1/me", headers=H(wt)).status_code == 401  # worker token is not a user session
    assert client.post("/v1/worker/heartbeat", json={}, headers=H(t)).status_code == 401  # session is not a worker
    other = register_verified(client, settings, "other")["token"]
    assert client.post(f"/v1/training/workers/{w['worker_id']}/pause", headers=H(other)).status_code == 404
    _, w2 = enroll(client, other)
    job = client.post("/v1/worker/jobs/claim", headers=H(wt)).json()
    assert client.get(f"/v1/worker/jobs/{job['id']}/weights", headers=H(w2["worker_token"])).status_code == 409


def test_cpu_and_gpu_workers_get_jobs_that_fit_them(client, settings, training_world):
    """0.5: CPU workers are production workers; jobs are matched to memory, not to a GPU flag."""
    t = register_verified(client, settings, "cpuonly")["token"]
    _, w = enroll(client, t, hw=HW_CPU)
    assert client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).status_code == 200
    _, g = enroll(client, t, hw=HW_GPU)
    assert client.post("/v1/worker/jobs/claim", headers=H(g["worker_token"])).status_code == 200
    _, tiny = enroll(client, t, hw={"gpus": [], "cpu_count": 2, "ram_gb": 0.5, "os": "Linux test"})
    from sqlalchemy import update

    with client.app.state.ctx.db.tx() as c:  # a job that needs more memory than that machine has
        c.execute(update(training_jobs).where(training_jobs.c.status == "queued").values(
            kind="evolve_train", spec=json.dumps({"requirements": {"memory_bytes": 4 << 30}, "round": -1})))
    assert client.post("/v1/worker/jobs/claim", headers=H(tiny["worker_token"])).status_code == 204


def test_two_workers_complete_a_verified_round(client, settings, training_world, tmp_path):
    t = register_verified(client, settings, "trainer")["token"]
    results = []
    for name in ("a", "b"):
        _, w = enroll(client, t, name=name)
        r = runner(client, w["worker_token"], tmp_path, name)
        r.beat()
        results.append(r.run_job(client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()))
    assert all(r["accepted"] for r in results), results
    assert results[1]["aggregated"] is True
    coord = client.app.state.ctx.extras["coordinator"]
    assert coord.config["version"] == 1 and coord.config["round"] == 1
    listing = client.get("/v1/training/workers", headers=H(t)).json()
    assert [w["verified_jobs"] for w in listing["workers"]] == [1, 1]
    assert listing["network"]["checkpoint_version"] == 1
    assert sorted(j["status"] for j in listing["jobs"]) == ["completed", "completed"]


def test_expired_lease_is_requeued_and_reconnect_resumes(client, settings, training_world):
    t = register_verified(client, settings, "lease")["token"]
    _, a = enroll(client, t)
    _, b = enroll(client, t)
    job = client.post("/v1/worker/jobs/claim", headers=H(a["worker_token"])).json()
    again = client.post("/v1/worker/jobs/claim", headers=H(a["worker_token"])).json()
    assert again["id"] == job["id"]  # reconnecting worker gets its leased job back
    db = client.app.state.ctx.db
    with db.tx() as c:
        c.execute(training_jobs.update().where(training_jobs.c.id == job["id"]).values(lease_expires_at=time.time() - 1))
    taken = client.post("/v1/worker/jobs/claim", headers=H(b["worker_token"])).json()
    assert taken["id"] == job["id"]
    assert client.get(f"/v1/worker/jobs/{job['id']}/shard", headers=H(a["worker_token"])).status_code == 409


def test_pause_and_revoke(client, settings, training_world):
    t = register_verified(client, settings, "ctl")["token"]
    _, w = enroll(client, t)
    wt, wid = w["worker_token"], w["worker_id"]
    job = client.post("/v1/worker/jobs/claim", headers=H(wt)).json()
    client.post(f"/v1/training/workers/{wid}/pause", headers=H(t))
    assert client.post("/v1/worker/heartbeat", json={}, headers=H(wt)).json()["paused"] is True
    assert client.post("/v1/worker/jobs/claim", headers=H(wt)).status_code == 204
    client.post(f"/v1/training/workers/{wid}/revoke", headers=H(t))
    assert client.post("/v1/worker/heartbeat", json={}, headers=H(wt)).status_code == 401
    db = client.app.state.ctx.db
    assert db.one(select(training_jobs.c.status).where(training_jobs.c.id == job["id"]))["status"] == "queued"


def test_tampered_results_are_rejected_without_credit(client, settings, training_world):
    import torch

    from moth.community.validation import serialize_state, tensor_bytes_sha256

    t = register_verified(client, settings, "cheat")["token"]
    _, w = enroll(client, t)
    job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    base = torch.load(training_world["base_model"] / "model.pt", weights_only=True)
    junk = {k: torch.full_like(v.float(), 50.0) for k, v in base.items()}
    payload = serialize_state(junk)
    meta = {"round": 0, "base_sha256": job["spec"]["base_sha256"], "delta_sha256": tensor_bytes_sha256(payload),
            "tokens": 10_000_000, "steps": 6, "loss_before": 5.0, "loss_after": 1.0, "protocol": "moth-community/1"}
    r = client.post(f"/v1/worker/jobs/{job['id']}/result", content=payload,
                    headers={**H(w["worker_token"]), "x-moth-contribution": json.dumps(meta)}).json()
    assert r["accepted"] is False and any("too large" in x for x in r["reasons"])
    row = client.app.state.ctx.db.one(select(workers).where(workers.c.id == w["worker_id"]))
    assert row["verified_jobs"] == 0 and row["failed_jobs"] == 1


def test_gpu_server_referral_rewards_after_verified_jobs(client, settings, training_world, tmp_path):
    referrer = register_verified(client, settings, "refgpu")
    code = referrer["user"]["referral_code"]
    client.put("/v1/admin/referral-rules", json={"contributor_min_verified_jobs": 1},
               headers=H(training_world["owner"]["token"]))
    t = register_verified(client, settings, "renter")["token"]
    _, w = enroll(client, t, referral=code)
    _, self_ref = enroll(client, t, referral=client.get("/v1/me", headers=H(t)).json()["referral_code"])
    db = client.app.state.ctx.db
    assert db.one(select(workers.c.referrer_id).where(workers.c.id == self_ref["worker_id"]))["referrer_id"] is None
    r = runner(client, w["worker_token"], tmp_path, "ref")
    r.beat()
    res = r.run_job(client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json())
    assert res["accepted"]
    rewards = db.all(select(referral_rewards))
    assert len(rewards) == 1 and rewards[0]["kind"] == "gpu" and rewards[0]["status"] == "pending"
    tokens = db.one(select(workers.c.trained_tokens).where(workers.c.id == w["worker_id"]))["trained_tokens"]
    assert tokens > 0 and rewards[0]["amount"] == min(100_000, round(tokens / 1000 * 400))  # proportional to work
    # idle enrolled servers earn nothing
    assert all(rw["worker_id"] == w["worker_id"] for rw in rewards)


def test_worker_resumes_mid_job_from_checkpoint(client, settings, training_world, tmp_path, monkeypatch):
    from moth_worker import runner as runner_mod

    monkeypatch.setattr(runner_mod, "CHECKPOINT_EVERY", 2)
    t = register_verified(client, settings, "resume")["token"]
    _, w = enroll(client, t)
    r1 = runner(client, w["worker_token"], tmp_path, "rs")
    job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    calls = {"n": 0}
    orig = r1.client.progress

    def progress_then_stop(jid, p):
        calls["n"] += 1
        out = orig(jid, p)
        r1.stop_event.set()  # simulate the machine going away after the first checkpoint
        return out

    r1.client.progress = progress_then_stop
    with pytest.raises(Stop):
        r1.run_job(job)
    checkpoint = tmp_path / "rs" / "jobs" / f"{job['id']}.pt"
    from moth.training.checkpoint import load_checkpoint, verify

    assert checkpoint.exists() and verify(checkpoint)
    state = load_checkpoint(checkpoint)
    assert state["batch_tuning"]["effective_batch_size"] == job["spec"]["train"]["batch_size"]
    assert state["rng"]["torch"].device.type == "cpu"
    logs = []
    r2 = WorkerRunner(WorkerClient("http://test", w["worker_token"], http=client), tmp_path / "rs", allow_cpu=True,
                      log=logs.append, heartbeat_seconds=3600)
    again = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    assert again["id"] == job["id"]
    import moth.training.autotune as tuning

    def no_reprobe(*args, **kwargs):
        raise AssertionError("a resumed worker must reuse its checkpointed batch choice")

    monkeypatch.setattr(tuning, "tune_batch", no_reprobe)
    assert r2.run_job(again)["accepted"]
    assert not checkpoint.exists() and not checkpoint.with_name(checkpoint.name + ".sha256").exists()
    assert any("resuming from step 2" in m for m in logs)
