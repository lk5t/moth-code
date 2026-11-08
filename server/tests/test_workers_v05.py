"""0.5 workers: EasyConnect serving, duplicate machines, leaving, and Rewards 2.0 review rules."""

import hashlib
import json

from sqlalchemy import select

from conftest import H, register_verified
from moth_server import referrals as R
from moth_server.db import referral_rewards, workers
from release_helpers import release, worker_bundle
from test_updates import register, signed  # noqa: F401  (fixture)

CPU = {"gpus": [], "cpu_count": 4, "ram_gb": 8.0, "os": "Linux test", "compute": "cpu"}


def enroll(client, token, machine="m-1", referral=None, name=None):
    e = client.post("/v1/training/enrollments", json={"name": name, "referral_code": referral}, headers=H(token)).json()
    r = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {**CPU, "machine_id": machine},
                                               "version": "0.5.0"})
    assert r.status_code == 200, r.text
    return r.json()


def test_relayed_worker_bundle_is_served_with_one_command_installs(client, settings, signed, tmp_path):
    """The bundle the update agent relays from a signed release is downloadable from MOTH Cloud, and the
    enrollment returns Linux/macOS and Windows commands pinned to its SHA-256 (the 0.4.0 VPS returned 404)."""
    s = signed
    user = register_verified(client, settings, "easy")["token"]
    assert client.post("/v1/training/enrollments", json={}, headers=H(user)).json()["command"] is None
    wb = worker_bundle(tmp_path, "0.5.7")
    raw, sig = release(tmp_path, s["key"], "0.5.7", worker=wb, rollout={"worker": {"stages": [100]}})
    register(client, s, raw, sig, [("worker", wb)])
    sha = hashlib.sha256(wb.read_bytes()).hexdigest()
    e = client.post("/v1/training/enrollments", json={}, headers=H(user)).json()
    assert e["release"]["version"] == "0.5.7" and e["release"]["sha256"] == sha
    assert sha in e["command"] and "install.sh --server https://moth.test --token" in e["command"]
    assert sha.upper() in e["windows_command"] and "install.ps1" in e["windows_command"]
    r = client.get("/downloads/worker/moth-worker-0.5.7.tar.gz")
    assert r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == sha
    assert client.get("/downloads/worker/moth-worker-0.0.1.tar.gz").status_code == 404


def test_same_machine_reenrolled_replaces_its_old_registration(client, settings):
    t = register_verified(client, settings, "again")["token"]
    first = enroll(client, t, machine="pc-1")
    second = enroll(client, t, machine="pc-1")
    db = client.app.state.ctx.db
    old = db.one(select(workers).where(workers.c.id == first["worker_id"]))
    assert old["revoked_at"] is not None and old["status"] == "revoked"
    assert client.post("/v1/worker/heartbeat", json={}, headers=H(first["worker_token"])).status_code == 401
    assert client.post("/v1/worker/heartbeat", json={}, headers=H(second["worker_token"])).status_code == 200
    other = enroll(client, t, machine="pc-2")  # a different computer of the same user is a second worker
    assert db.one(select(workers).where(workers.c.id == other["worker_id"]))["revoked_at"] is None


def test_uninstall_leave_revokes_the_worker(client, settings):
    t = register_verified(client, settings, "leaver")["token"]
    w = enroll(client, t, machine="pc-9")
    assert client.post("/v1/worker/leave", headers=H(w["worker_token"])).json()["ok"]
    assert client.post("/v1/worker/heartbeat", json={}, headers=H(w["worker_token"])).status_code == 401
    mine = client.get("/v1/training/workers", headers=H(t)).json()["workers"]
    assert mine == []
    tombstone = client.app.state.ctx.db.one(select(workers).where(workers.c.id == w["worker_id"]))
    assert tombstone["status"] == "revoked" and tombstone["revoked_at"] is not None


def _contribute(client, worker_id, job_id, tokens):
    ctx = client.app.state.ctx
    w = ctx.db.one(select(workers).where(workers.c.id == worker_id))
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == worker_id).values(verified_jobs=workers.c.verified_jobs + 1))
        w = dict(c.execute(select(workers).where(workers.c.id == worker_id)).mappings().first())
        R.on_contribution_verified(ctx, c, w, job_id, tokens=tokens)


def test_rewards_2_proportional_held_for_duplicates_and_unreliable_workers(client, settings, owner):
    ctx = client.app.state.ctx
    client.put("/v1/admin/referral-rules", json={"contributor_min_verified_jobs": 2}, headers=H(owner["token"]))
    ref = register_verified(client, settings, "referrer")
    code = ref["user"]["referral_code"]
    contributor = register_verified(client, settings, "contrib")["token"]
    w = enroll(client, contributor, machine="box-a", referral=code)
    # registration alone and the first verified job earn nothing
    _contribute(client, w["worker_id"], 1, 50_000)
    assert ctx.db.all(select(referral_rewards)) == []
    # then rewards follow the work done: 120,000 tokens × 400 / 1,000 = 48,000 credits
    _contribute(client, w["worker_id"], 2, 120_000)
    rw = ctx.db.all(select(referral_rewards))
    assert len(rw) == 1 and rw[0]["amount"] == 48_000 and rw[0]["status"] == "pending"
    _contribute(client, w["worker_id"], 2, 120_000)  # the same job can never be rewarded twice
    assert len(ctx.db.all(select(referral_rewards))) == 1
    _contribute(client, w["worker_id"], 3, 0)  # no measured work → no reward
    assert len(ctx.db.all(select(referral_rewards))) == 1
    # the same computer enrolled by another account → rewards held for review
    sneaky = register_verified(client, settings, "sneaky")["token"]
    enroll(client, sneaky, machine="box-a")
    _contribute(client, w["worker_id"], 4, 10_000)
    held = ctx.db.one(select(referral_rewards).where(referral_rewards.c.source_ref == "job:4"))
    assert held["status"] == "review" and "another account" in held["reason"]
    # an unreliable worker (most jobs fail) → held for review
    u = enroll(client, contributor, machine="box-b", referral=code)
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == u["worker_id"]).values(verified_jobs=2, failed_jobs=8))
    _contribute(client, u["worker_id"], 5, 10_000)
    bad = ctx.db.one(select(referral_rewards).where(referral_rewards.c.source_ref == "job:5"))
    assert bad["status"] == "review" and "reliability" in bad["reason"]
    # the Owner releases a held reward after reviewing it (others stay held)
    o = H(owner["token"])
    assert client.post(f"/v1/admin/rewards/{held['id']}/approve", headers=o).json()["ok"]
    assert ctx.db.one(select(referral_rewards).where(referral_rewards.c.id == held["id"]))["status"] == "pending"
    assert client.post(f"/v1/admin/rewards/{held['id']}/approve", headers=o).status_code == 409
    # dashboard: contributions per referred worker and the rules in plain words
    d = client.get("/v1/referrals", headers=H(ref["token"])).json()
    assert {x["name"][:2] for x in d["referred_workers"]} and any(x["verified_jobs"] >= 3 for x in d["referred_workers"])
    assert any("per 1,000 tokens" in t for t in d["rules_text"])


def test_owner_cannot_resume_another_accounts_paused_device(client, settings, owner):
    account = register_verified(client, settings, 'private-device')['token']
    w = enroll(client, account, machine='private-pc')
    path = f"/v1/training/workers/{w['worker_id']}"
    assert client.post(path + '/pause', headers=H(account)).status_code == 200
    assert client.post(path + '/resume', headers=H(owner['token'])).status_code == 403
    assert client.post(path + '/resume', headers=H(account)).status_code == 200
