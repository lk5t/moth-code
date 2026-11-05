"""End to end: the desktop publisher (moth.publish) against a real MOTH Server.

Select (an exported package) → Validate (locally) → Upload (chunked, with injected network
failures and an app restart in the middle) → Evaluate (server, real) → Publish → Deploy → inference.
"""

import json

import httpx
import pytest

from conftest import H, make_tiny_model, register_verified
from moth.publish import PublishError, Publisher
from moth_server import models as M


class MemDB:
    def __init__(self):
        self.data = {}

    def get_setting(self, k, default=None):
        return json.loads(self.data[k]) if k in self.data else default

    def set_setting(self, k, v):
        self.data[k] = json.dumps(v)


class Flaky:
    """Wraps the HTTP client: drops chunk uploads according to a plan (True = fail)."""

    def __init__(self, client, plan):
        self.client, self.plan, self.puts = client, plan, 0

    def request(self, method, url, **kw):
        if method == "PUT" and "/chunks/" in url:
            self.puts += 1
            if self.plan(self.puts):
                raise httpx.ConnectError("network dropped")
        return self.client.request(method, url, **kw)


@pytest.fixture
def world(client, settings, owner, tmp_path):
    client.app.state.ctx.settings.max_upload_chunk = 32 * 1024  # many chunks for a small model
    models = tmp_path / "desktop-models"
    pkg = make_tiny_model(tmp_path, 41, "desktop-publish")
    pkg.rename(models / pkg.name) if models.exists() else (models.mkdir(), pkg.rename(models / pkg.name))
    acct = {"server_url": "http://testserver", "token": owner["token"], "user": {"role": "owner"}}
    return {"models": models, "id": pkg.name, "acct": acct, "cache": tmp_path / "cache"}


def test_publish_with_network_failures_and_app_restart(client, settings, world):
    ctx = client.app.state.ctx
    db = MemDB()
    # first "app session": the network fails permanently after two chunks → paused, state persisted
    flaky = Flaky(client, plan=lambda n: n > 2)
    p1 = Publisher(world["models"], world["cache"], db, lambda: world["acct"], http=flaky, sleep=lambda s: None)
    assert p1.validate(world["id"])["ok"]
    job = p1.start(world["id"])
    p1._threads[world["id"]].join(30) if world["id"] in p1._threads else None
    job = next(j for j in p1.status() if j["model_id"] == world["id"])
    assert job["stage"] == "paused" and "resume" in job["error"]
    assert 0 < job["progress"] < 1
    assert db.get_setting("publish_jobs")[world["id"]]["upload_id"] == job["upload_id"]
    # second "app session" (restart): transient failures only, upload resumes and completes
    flaky2 = Flaky(client, plan=lambda n: n in (1, 3))
    p2 = Publisher(world["models"], world["cache"], db, lambda: world["acct"], http=flaky2, sleep=lambda s: None)
    assert p2.resume_pending() == [world["id"]]
    p2._threads[world["id"]].join(60) if world["id"] in p2._threads else None
    job = next(j for j in p2.status() if j["model_id"] == world["id"])
    assert job["stage"] == "published", job
    assert job["evaluation"]["passed"] and job["evaluation"]["score"]["metric"] == "bits_per_byte"
    rel = M.release(ctx, job["release_version"])
    assert rel["status"] == "published"
    assert db.get_setting("publish_jobs") == {}  # finished jobs are not resumed again
    # deploy (Owner) and serve real inference to a user
    o = H(world["acct"]["token"])
    assert client.post(f"/v1/admin/models/{rel['version']}/deploy", headers=o).json()["status"] == "deployed"
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=o)
    user = register_verified(client, settings, "pub_user")["token"]
    name = client.get("/cloud/v1/health").json()["models"][0]["name"]
    r = client.post("/cloud/v1/chat", headers=H(user), json={
        "model": name, "messages": [{"role": "user", "content": "def add("}],
        "params": {"max_new_tokens": 6, "temperature": 0}})
    assert r.status_code == 200 and json.loads(r.text.splitlines()[-1])["stats"]["generated_tokens"] > 0
    # publishing the same model again is recognised as a duplicate
    again = Publisher(world["models"], world["cache"], MemDB(), lambda: world["acct"], http=client,
                      sleep=lambda s: None).start(world["id"])
    assert again["duplicate"] and again["release_version"] == rel["version"] and again["stage"] == "deployed"


def test_publish_errors_are_clear(client, settings, world):
    ctx = client.app.state.ctx
    db = MemDB()
    p = Publisher(world["models"], world["cache"], db, lambda: world["acct"], http=client, sleep=lambda s: None)
    # an invalid package is stopped locally with the reason, before uploading
    (world["models"] / world["id"] / "tokenizer.json").write_text("{}")
    with pytest.raises(PublishError) as e:
        p.start(world["id"])
    assert e.value.status == 422 and "tokenizer.json could not be loaded" in str(e.value)
    # non-owners are refused
    p2 = Publisher(world["models"], world["cache"], db, lambda: {**world["acct"], "user": {"role": "user"}},
                   http=client, sleep=lambda s: None)
    with pytest.raises(PublishError) as e:
        p2.start(world["id"])
    assert e.value.status == 403
    # stale Owner sign-in → 428 so the desktop asks for the password again
    fresh = make_tiny_model(world["cache"].parent, 42, "reauth")
    fresh.rename(world["models"] / fresh.name)
    from moth_server.db import sessions

    with ctx.db.tx() as c:
        c.execute(sessions.update().values(reauth_at=0))
    with pytest.raises(PublishError) as e:
        p.start(fresh.name)
    assert e.value.status == 428
