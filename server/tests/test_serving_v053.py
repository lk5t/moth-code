"""0.5.3 serving: staged rollout by user bucket, version pinning, promotion of the canary, and signed
model manifests verified (and their key pinned) by MOTH Code's on-computer download."""

import json

import pytest
from sqlalchemy import select

from conftest import H, make_tiny_model, register_verified
from moth_server import models as M
from moth_server import serving


def _two_releases(client, owner, tmp_path):
    ctx = client.app.state.ctx
    a = M._register(ctx, make_tiny_model(tmp_path, 0, "stable"), "stable", {"type": "upload"}, None)
    b = M._register(ctx, make_tiny_model(tmp_path, 1, "cand"), "cand", {"type": "upload"}, None)
    for r in (a, b):
        assert M.evaluate(ctx, r["version"])["status"] == "published"
    M.deploy(ctx, a["version"])
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=H(owner["token"]))
    return ctx, a["version"], b["version"]


def _served_version(client, token):
    r = client.post("/v1/chat", json={"message": "hello", "params": {"max_new_tokens": 2}}, headers=H(token))
    assert r.status_code == 200, r.text
    return [json.loads(l) for l in r.text.splitlines()][-1]["model_version"]


def test_staged_rollout_pinning_and_promotion(client, settings, owner, tmp_path):
    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    serving.start_canary(ctx, cand, 50)
    users = []
    for i in range(12):
        ctx.limiter.clear("register:ip:testclient")  # one test client registers many users
        users.append(register_verified(client, settings, f"roll{i}"))
    expect = {u["user"]["id"]: (cand if serving.bucket(u["user"]["id"]) < 50 else stable) for u in users}
    assert set(expect.values()) == {stable, cand}  # both groups exist
    for u in users:
        assert _served_version(client, u["token"]) == expect[u["user"]["id"]]
    # a user pins the stable version: always served by it, whatever their bucket
    canary_user = next(u for u in users if expect[u["user"]["id"]] == cand)
    assert client.put("/v1/me/model-pin", json={"version": stable}, headers=H(canary_user["token"])).status_code == 200
    assert _served_version(client, canary_user["token"]) == stable
    assert client.put("/v1/me/model-pin", json={"version": 9999}, headers=H(canary_user["token"])).status_code == 409
    # promotion: the canary's loaded engine becomes the stable model for everyone
    serving.promote_canary(ctx)
    assert ctx.extras["deployed_version"] == cand and serving.canary(ctx) is None
    client.put("/v1/me/model-pin", json={"version": None}, headers=H(canary_user["token"]))
    assert all(_served_version(client, u["token"]) == cand for u in users[:3])


def test_server_signed_manifest_and_key_pinning(client, settings, owner, tmp_path):
    from moth.inference.ondevice import OnDevice, OnDeviceError

    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    M._set(ctx, stable, None, info=json.dumps({**M.release(ctx, stable)["info"], "model_version": "0.2"}))
    man = serving.sign_release(ctx, stable)
    assert man["weights_sha256"] == M.release(ctx, stable)["sha256"] and man["model_version"] == "0.2"
    key = client.get("/v1/models/signing-key").json()["key"]
    assert key == serving.public_key_b64(ctx)
    t = register_verified(client, settings, "laptop")["token"]

    class Http:
        def __enter__(self):
            return client

        def __exit__(self, *a):
            return False

    od = OnDevice(tmp_path / "od", lambda: {"server_url": "http://testserver", "token": t}, lambda *a: None,
                  http_factory=Http)
    inst = od.download()
    assert inst["signed_by_server"] and not inst["official"]
    pinned = json.loads((tmp_path / "od" / "on-device" / "trusted-server-keys.json").read_text())
    assert pinned["http://testserver"] == key
    # the server's key changes (e.g. a different server at the same address): the download is refused
    (tmp_path / "od" / "on-device" / "current.json").unlink()
    (ctx.settings.data_dir / "keys" / "model-signing.ed25519").unlink()
    serving.sign_release(ctx, stable)
    with pytest.raises(OnDeviceError, match="different model-signing key"):
        od.download()
