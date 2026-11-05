"""Update service: signed releases, desktop updater endpoint, staged rollouts, worker updates,
compatibility enforcement, agent API isolation and Owner controls."""

import base64
import json
import shutil

import pytest

from conftest import H, register_verified
from moth_server import releases as R
from release_helpers import TestKey, release, worker_bundle


@pytest.fixture
def signed(client, settings, owner, tmp_path):
    key = TestKey()
    ctx = client.app.state.ctx
    ctx.settings.release_pubkey = key.public_b64
    token = tmp_path / "agent.token"
    token.write_text("agent-secret-for-tests")
    ctx.settings.agent_token_file = str(token)
    return {"key": key, "ctx": ctx, "agent": {"X-Moth-Agent-Token": "agent-secret-for-tests"}, "o": H(owner["token"]),
            "out": tmp_path}


def register(client, s, raw, sig, files=()):
    r = client.post("/v1/agent/releases", json={"manifest": base64.b64encode(raw).decode(), "signature": sig},
                    headers=s["agent"])
    assert r.status_code == 200, r.text
    incoming = s["ctx"].settings.releases_dir / "incoming"
    for comp, path in files:
        shutil.copy(path, incoming / path.name)
        rr = client.post("/v1/agent/files", json={"component": comp, "version": json.loads(raw)["version"],
                                                  "path": str(incoming / path.name)}, headers=s["agent"])
        assert rr.status_code == 200, rr.text
    return r.json()


def test_agent_api_is_hidden_and_signatures_enforced(client, signed):
    s = signed
    raw, sig = release(s["out"], s["key"], "0.3.1", desktop=True)
    # without the agent token the agent API does not exist
    assert client.get("/v1/agent/control").status_code == 404
    assert client.get("/v1/agent/control", headers={"X-Moth-Agent-Token": "wrong"}).status_code == 404
    # a tampered manifest or a signature from another key is refused
    tampered = raw.replace(b"test release", b"evil release")
    bad = client.post("/v1/agent/releases", json={"manifest": base64.b64encode(tampered).decode(), "signature": sig},
                      headers=s["agent"])
    assert bad.status_code == 422 and "signature" in bad.json()["detail"]
    other = TestKey()
    bad2 = client.post("/v1/agent/releases", json={"manifest": base64.b64encode(raw).decode(),
                                                   "signature": other.sign(raw)}, headers=s["agent"])
    assert bad2.status_code == 422
    # a file that doesn't match the signed SHA-256 is rejected
    register(client, s, raw, sig)
    fake = s["ctx"].settings.releases_dir / "incoming" / "MOTH.Code_0.3.1_x64-setup.exe"
    fake.write_bytes(b"not the signed installer")
    r = client.post("/v1/agent/files", json={"component": "desktop", "version": "0.3.1", "path": str(fake)},
                    headers=s["agent"])
    assert r.status_code == 422 and "SHA-256" in r.json()["detail"]
    # files outside the incoming area are refused
    r = client.post("/v1/agent/files", json={"component": "desktop", "version": "0.3.1", "path": "/etc/passwd"},
                    headers=s["agent"])
    assert r.status_code == 422


def test_desktop_updates_staged_rollout_and_automatic_halt(client, signed):
    s = signed
    raw, sig = release(s["out"], s["key"], "0.3.1", desktop=True,
                       rollout={"desktop": {"stages": [10, 50, 100], "interval_hours": 0, "max_failure_rate": 0.2,
                                            "min_reports": 5}})
    register(client, s, raw, sig, [("desktop", s["out"] / "MOTH.Code_0.3.1_x64-setup.exe")])
    url = "/v1/updates/desktop/windows/x86_64/0.3.0"
    offered = [i for i in range(200) if client.get(url, headers={"X-Moth-Install-Id": f"install-{i}"}).status_code == 200]
    assert 5 <= len(offered) <= 40  # ~10% stage
    body = client.get(url, headers={"X-Moth-Install-Id": f"install-{offered[0]}"}).json()
    assert body["version"] == "0.3.1" and body["signature"].endswith("SIG0.3.1")
    assert body["url"].endswith("/v1/updates/files/desktop/0.3.1/MOTH.Code_0.3.1_x64-setup.exe")
    dl = client.get(body["url"].replace("https://moth.test", ""))
    assert dl.status_code == 200 and dl.content.startswith(b"MZ fake installer")
    # up to date → 204; unknown platforms → 204
    assert client.get("/v1/updates/desktop/windows/x86_64/0.3.1").status_code == 204
    assert client.get("/v1/updates/desktop/linux/x86_64/0.3.0").status_code == 204
    # next stage after the interval
    R.advance_rollouts(s["ctx"])
    rel = next(r for r in R.list_releases(s["ctx"], "desktop") if r["version"] == "0.3.1")
    assert rel["rollout_percent"] == 50 and rel["status"] == "rolling_out"
    # failures above the limit halt the rollout automatically and notify the Owner
    for i in range(4):
        client.post("/v1/updates/report", json={"component": "desktop", "from_version": "0.3.0", "to_version": "0.3.1",
                                                "ok": False, "error": "installer failed"},
                    headers={"X-Moth-Install-Id": f"bad-{i}"})
    client.post("/v1/updates/report", json={"component": "desktop", "from_version": "0.3.0", "to_version": "0.3.1",
                                            "ok": True}, headers={"X-Moth-Install-Id": "good"})
    R.advance_rollouts(s["ctx"])
    rel = next(r for r in R.list_releases(s["ctx"], "desktop") if r["version"] == "0.3.1")
    assert rel["status"] == "halted" and rel["reports"]["failed"] == 4
    assert all(client.get(url, headers={"X-Moth-Install-Id": f"install-{i}"}).status_code == 204 for i in offered)
    from moth_server.db import error_log
    assert "halted" in s["ctx"].db.all(error_log.select())[-1]["message"]
    # the Owner can resume, set the percentage or promote to everyone (re-authenticated)
    assert client.post("/v1/admin/updates/releases/desktop/0.3.1/promote", headers=s["o"]).json()["rollout_percent"] == 100
    assert client.get(url, headers={"X-Moth-Install-Id": "anyone"}).status_code == 200
    overview = client.get("/v1/admin/updates", headers=s["o"]).json()
    assert overview["signing_configured"] and any(r["version"] == "0.3.1" for r in overview["releases"])


def test_outdated_clients_get_426_but_can_still_update(client, signed, settings):
    s = signed
    user = register_verified(client, settings, "compat_user")["token"]
    hdr = {**H(user), "X-Moth-Client": "desktop/0.3.0"}
    assert client.get("/v1/me", headers=hdr).status_code == 200
    assert client.get("/v1/me", headers=H(user)).status_code == 200  # v0.2 desktops (no header) still served
    r = client.put("/v1/admin/updates/min-versions", json={"desktop": "0.3.0"}, headers=s["o"])
    assert r.json()["desktop"] == "0.3.0"
    old = client.get("/v1/me", headers={**H(user), "X-Moth-Client": "desktop/0.2.1"})
    assert old.status_code == 426 and old.headers["X-Moth-Reason"] == "client_outdated"
    assert client.get("/v1/me", headers=H(user)).status_code == 426  # header-less = v0.2 → too old now
    assert client.get("/v1/me", headers=hdr).status_code == 200
    # outdated clients can still reach health and the update service
    assert client.get("/v1/health", headers={"X-Moth-Client": "desktop/0.2.1"}).status_code == 200
    assert client.get("/v1/updates/desktop/windows/x86_64/0.2.1",
                      headers={"X-Moth-Client": "desktop/0.2.1"}).status_code in (200, 204)
    health = client.get("/v1/health").json()
    assert health["api_version"] == 3 and health["min_client_versions"]["desktop"] == "0.3.0"
    # the floor can't be lowered below the built-in minimum
    client.put("/v1/admin/updates/min-versions", json={"desktop": "0.1.0"},
               headers={**s["o"], "X-Moth-Client": "desktop/0.3.0"})
    assert client.get("/v1/health").json()["min_client_versions"]["desktop"] == "0.2.0"


def test_owner_update_controls_require_owner(client, signed, settings):
    s = signed
    user = register_verified(client, settings, "not_owner")["token"]
    for method, path in (("get", "/v1/admin/updates"), ("post", "/v1/admin/updates/server/pause"),
                         ("post", "/v1/admin/updates/server/rollback"), ("get", "/v1/admin/system")):
        assert getattr(client, method)(path, headers=H(user)).status_code == 403
    assert client.post("/v1/admin/updates/server/pause", headers=s["o"]).json()["paused"] is True
    assert client.get("/v1/agent/control", headers=s["agent"]).json()["paused"] is True
    client.post("/v1/admin/updates/server/check-now", headers=s["o"])
    assert client.get("/v1/agent/control", headers=s["agent"]).json()["check_now_at"]
    client.post("/v1/agent/heartbeat", json={"agent_version": "0.3.0", "state": "idle", "current": "0.3.0",
                                             "ack_check_now": True}, headers=s["agent"])
    ctl = client.get("/v1/agent/control", headers=s["agent"]).json()
    assert ctl["check_now_at"] is None
    over = client.get("/v1/admin/updates", headers=s["o"]).json()
    assert over["agent"]["online"] and over["agent"]["current"] == "0.3.0"
    # deployment history reported by the agent; failures notify the Owner
    d = client.post("/v1/agent/deployments", json={"component": "server", "from_version": "0.3.0", "to_version": "0.3.1",
                                                   "status": "started", "log": "backup ok\n"}, headers=s["agent"]).json()
    client.post("/v1/agent/deployments", json={"id": d["id"], "status": "rolled_back", "error": "health check failed",
                                               "log": "rolled back\n"}, headers=s["agent"])
    dep = client.get("/v1/admin/updates", headers=s["o"]).json()["deployments"][0]
    assert dep["status"] == "rolled_back" and "backup ok" in dep["log"] and dep["finished_at"]
    from moth_server.db import error_log
    assert any("rolled back" in e["message"] for e in s["ctx"].db.all(error_log.select()))
    sysinfo = client.get("/v1/admin/system", headers=s["o"]).json()
    assert sysinfo["memory"]["total"] > 0 and sysinfo["disk"]["total"] > 0 and "cuda" in sysinfo["hardware"]


def test_worker_update_waits_for_job_and_verifies(client, signed, training_world, tmp_path, monkeypatch):
    """In-process: the update is applied only after the running job finished; tampering is refused."""
    from moth_worker import updater
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    s = signed
    monkeypatch.setenv("MOTH_RELEASE_PUBKEY", s["key"].public_b64)
    user = register_verified(client, s["ctx"].settings, "gpu_friend")["token"]
    e = client.post("/v1/training/enrollments", json={"name": "w"}, headers=H(user)).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": []}}).json()
    home = tmp_path / "worker-home"
    r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), home, allow_cpu=True,
                     log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=0)
    r.beat()
    job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
    bundle = worker_bundle(tmp_path, "0.3.1")
    raw, sig = release(tmp_path, s["key"], "0.3.1", worker=bundle, rollout={"worker": {"stages": [100]}})
    register(client, s, raw, sig, [("worker", bundle)])
    # the job in progress completes and is accepted first …
    assert r.run_job(job)["accepted"]
    # … then the verified update is installed side by side
    assert r.maybe_update() and r.updated_to == "0.3.1"
    assert (home / "current").resolve() == (home / "versions" / "0.3.1")
    assert json.loads((home / "update-pending.json").read_text())["version"] == "0.3.1"
    # a tampered offer is refused and reported, and the worker keeps running its version
    info = client.get("/v1/worker/update", headers=H(w["worker_token"])).json()["update"]
    info["signature"] = TestKey().sign(base64.b64decode(info["manifest"]))
    with pytest.raises(updater.UpdateError, match="signature"):
        updater.apply(info, tmp_path / "other-home", r.client.download_file)
    # a new version that fails to start three times is reverted automatically
    (home / "update-pending.json").write_text(json.dumps({"version": "0.3.1", "from": "0.3.0", "attempts": 3}))
    (home / "previous").unlink(missing_ok=True)
    reverted = updater.startup_guard(home, log=lambda m: None)
    assert reverted["reverted"] and not (home / "current").exists()


def test_stdlib_verifier_copies_are_identical_and_correct():
    """The agent and the worker carry their own copy of the ed25519 verifier (stdlib only)."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    copies = [root / "server/moth_server/ed25519_verify.py", root / "deploy/agent/ed25519_verify.py",
              root / "worker/moth_worker/ed25519_verify.py"]
    assert len({p.read_bytes() for p in copies}) == 1
    from moth_server.ed25519_verify import verify_b64

    key = TestKey()
    msg = b"manifest bytes"
    assert verify_b64(key.public_b64, msg, key.sign(msg))
    assert not verify_b64(key.public_b64, msg + b"!", key.sign(msg))
    assert not verify_b64(TestKey().public_b64, msg, key.sign(msg))
    pubs = {(root / p).read_text().strip() for p in ("deploy/agent/release-signing.pub",
                                                     "worker/moth_worker/release-signing.pub")}
    assert len(pubs) == 1 and len(base64.b64decode(pubs.pop())) == 32
