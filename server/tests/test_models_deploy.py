import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import H, make_tiny_model, register_verified
from moth_server import models as M
from moth_server.app import create_app
from moth_server.db import model_releases
from moth_worker.client import WorkerClient
from moth_worker.runner import WorkerRunner


def complete_round(client, token, tmp_path):
    for name in ("a", "b"):
        e = client.post("/v1/training/enrollments", json={"name": name}, headers=H(token)).json()
        w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": []}}).json()
        r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / name, allow_cpu=True,
                         log=lambda m: None, heartbeat_seconds=3600)
        r.beat()
        assert r.run_job(client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json())["accepted"]


def tarball(model_dir) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(model_dir, arcname="model")
    return buf.getvalue()


CHAT = {"model": None, "messages": [{"role": "user", "content": "def add("}], "params": {"max_new_tokens": 6, "temperature": 0}}


def test_network_checkpoint_to_deployed_cloud_model(client, settings, training_world, tmp_path):
    ctx = client.app.state.ctx
    o = H(training_world["owner"]["token"])
    user = register_verified(client, settings, "cloud_user")["token"]
    # nothing deployed yet: cloud inference reports unavailable instead of failing obscurely
    assert client.get("/v1/models/current").json() == {"available": False, "release": None}
    assert client.post("/cloud/v1/chat", json={**CHAT, "model": "x"}, headers=H(user)).status_code == 503
    complete_round(client, user, tmp_path)
    result = client.post("/v1/admin/models/sync", headers=o).json()
    rel = M.release(ctx, 1)
    assert result["created"] == [1] and result["passed"] == [1] and result["deployed"] is None, rel["error"]  # auto-deploy off
    rel = M.release(ctx, 1)
    assert rel["status"] == "published" and rel["evaluation"]["checks"]["finite_score"]
    assert rel["evaluation"]["dataset"]["source"] in ("coordinator", "builtin")
    assert rel["info"]["source"] == {"type": "training-network", "checkpoint_version": 1, "round": 0}
    assert client.post("/v1/admin/models/1/deploy", headers=H(user)).status_code == 403
    d = client.post("/v1/admin/models/1/deploy", headers=o)
    assert d.status_code == 200 and d.json()["status"] == "deployed"
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=o)
    cur = client.get("/v1/models/current").json()
    assert cur["available"] and cur["release"]["version"] == 1
    name = client.get("/cloud/v1/health").json()["models"][0]["name"]
    r = client.post("/cloud/v1/chat", json={**CHAT, "model": name}, headers=H(user))
    stats = json.loads(r.text.splitlines()[-1])["stats"]
    used = client.get("/v1/billing/summary", headers=H(user)).json()["period"]["used"]
    assert used == stats["prompt_tokens"] + stats["generated_tokens"] > 0  # metered
    owner_r = client.post("/cloud/v1/chat", json={**CHAT, "model": name}, headers=o)
    assert owner_r.status_code == 200
    assert client.get("/v1/billing/summary", headers=o).json()["period"]["used"] == 0  # owner exempt


def test_upload_evaluate_deploy_rollback_and_restore(client, settings, training_world, tmp_path):
    ctx = client.app.state.ctx
    o = H(training_world["owner"]["token"])

    def upload(seed, name):
        files = {"file": ("m.tar.gz", tarball(make_tiny_model(tmp_path, seed)), "application/gzip")}
        r = client.post("/v1/admin/models/upload", data={"name": name}, files=files, headers=o)
        assert r.status_code == 200, r.text
        return r.json()["version"]

    v1, v2 = upload(1, "first"), upload(2, "second")
    # uploads are validated and evaluated automatically; passing publishes (eligible, not active)
    for v in (v1, v2):
        rel = M.release(ctx, v)
        assert rel["status"] == "published", (rel["status"], rel["error"])
        assert rel["evaluation"]["passed"] and rel["evaluation"]["samples"]
    assert ctx.extras.get("inference_engine") is None  # publishing never activates a model
    # identical weights are detected as a duplicate instead of creating another release
    files = {"file": ("m.tar.gz", tarball(make_tiny_model(tmp_path, 1, "again")), "application/gzip")}
    dup = client.post("/v1/admin/models/upload", data={"name": "again"}, files=files, headers=o)
    assert dup.status_code == 422 and "already registered" in dup.json()["detail"]
    assert client.post(f"/v1/admin/models/{v1}/deploy", headers=o).json()["status"] == "deployed"
    assert client.post(f"/v1/admin/models/{v2}/deploy", headers=o).json()["status"] == "deployed"
    assert ctx.extras["deployed_version"] == v2
    old = M.release(ctx, v1)
    assert old["status"] == "published" and old["previously_deployed"]
    # failed deployment (corrupted weights) keeps the current model serving
    from pathlib import Path
    with open(Path(M.release(ctx, v1)["path"]) / "model.pt", "r+b") as f:
        f.seek(100)
        f.write(b"\x00\x01\x02")
    engine_before = ctx.extras["inference_engine"]
    r = client.post(f"/v1/admin/models/{v1}/deploy", headers=o)
    assert r.status_code == 409 and "previous model still serving" in r.json()["detail"]
    assert ctx.extras["inference_engine"] is engine_before and ctx.extras["deployed_version"] == v2
    assert M.release(ctx, v1)["status"] == "failed"  # corruption is a permanent failure
    # rollback needs a healthy previous release: deploy a third, then roll back to v2
    v3 = upload(3, "third")
    if M.release(ctx, v3)["status"] == "evaluated":  # scored worse than v2: explicit Owner override
        assert M.release(ctx, v3)["evaluation"]["reason"] == "regression"
        assert client.post(f"/v1/admin/models/{v3}/publish", json={}, headers=o).status_code == 409
        client.post(f"/v1/admin/models/{v3}/publish", json={"override_regression": True}, headers=o)
    assert client.post(f"/v1/admin/models/{v3}/deploy", headers=o).status_code == 200
    back = client.post("/v1/admin/models/rollback", headers=o)
    assert back.status_code == 200 and back.json()["version"] == v2
    # a restarted server restores the deployed release
    with TestClient(create_app(settings, extras={"disable_background": True})) as c2:
        assert c2.app.state.ctx.extras["deployed_version"] == v2


def test_upload_rejects_unsafe_archives(client, training_world):
    o = H(training_world["owner"]["token"])
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = b"x"
        info = tarfile.TarInfo("../../escape.txt")
        info.size = 1
        tar.addfile(info, io.BytesIO(data))
    r = client.post("/v1/admin/models/upload", data={"name": "evil"},
                    files={"file": ("e.tar.gz", buf.getvalue(), "application/gzip")}, headers=o)
    assert r.status_code == 422


def test_server_policy_is_owner_only_and_enforced(client, settings, training_world, tiny_model_dir):
    ctx = client.app.state.ctx
    o = H(training_world["owner"]["token"])
    user = register_verified(client, settings, "pol_user")["token"]
    files = {"file": ("m.tar.gz", tarball(tiny_model_dir), "application/gzip")}
    v = client.post("/v1/admin/models/upload", data={"name": "p"}, files=files, headers=o).json()["version"]
    client.post(f"/v1/admin/models/{v}/evaluate", headers=o)
    client.post(f"/v1/admin/models/{v}/deploy", headers=o)
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=o)
    assert client.get("/v1/admin/policy", headers=o).json()["content_rules"] == []
    rule = {"id": "b", "action": "block", "applies_to": "input", "match": {"type": "keywords", "patterns": ["zzz"]},
            "message": "Blocked by owner policy."}
    assert client.put("/v1/admin/policy", json={"content_rules": [rule]}, headers=H(user)).status_code == 403
    assert client.put("/v1/admin/policy", json={"content_rules": [{"id": "x", "action": "nope"}]}, headers=o).status_code == 422
    assert client.put("/v1/admin/policy", json={"content_rules": [rule]}, headers=o).status_code == 200
    name = client.get("/cloud/v1/health").json()["models"][0]["name"]
    r = client.post("/cloud/v1/chat", json={**CHAT, "model": name, "messages": [{"role": "user", "content": "zzz now"}]},
                    headers=H(user))
    assert r.status_code == 422 and r.json()["detail"] == "Blocked by owner policy."
    assert client.get("/v1/billing/summary", headers=H(user)).json()["period"]["used"] == 0  # blocked before metering
