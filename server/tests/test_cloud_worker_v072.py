"""0.7.2: MOTH Cloud enrolls its own worker and does the same verified work as any worker."""
import json

from sqlalchemy import select

from moth_server.db import evolution_experiments, workers, now
from moth_server.evolution import cloud_worker as CW, settings as S


def test_cloud_worker_enrolls_once_and_pauses_for_local_training(client, owner):
    from starlette.testclient import TestClient

    ctx = client.app.state.ctx
    r = CW.make_runner(ctx, TestClient(ctx.extras["app"]))
    assert r is not None
    rows = ctx.db.all(select(workers))
    assert len(rows) == 1 and rows[0]["name"] == CW.NAME and json.loads(rows[0]["hardware"])["worker_kind"] == "cloud"
    assert CW.make_runner(ctx, TestClient(ctx.extras["app"])) is not None
    assert len(ctx.db.all(select(workers))) == 1  # the saved credential is reused: enrolled once
    r.beat()
    assert r.paused is False
    with ctx.db.tx() as c:  # MOTH Cloud starts a local experiment of its own
        c.execute(evolution_experiments.insert().values(cycle_id=1, status="running", backend="local", dataset_id=1, base_version=1, base_sha256="0" * 64,
                  config="{}", config_hash="x", created_at=now(), updated_at=now()))
    r.beat()
    assert r.paused is True  # it does not start new work while MOTH Cloud trains locally
    r.current_job = 99  # but a job already under way is finished, not paused into a stall (0.8.3)
    r.beat()
    assert r.paused is False


def test_owner_choice_turns_it_off(client, owner):
    ctx = client.app.state.ctx
    assert CW.allowed(ctx)
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True}})
    assert not CW.allowed(ctx)
    S.update(ctx, {"backends": {"local_cpu": True, "local_gpu": True, "workers": True},
                   "distributed": {"cloud_participates": False}})
    assert not CW.allowed(ctx)
    S.update(ctx, {"distributed": {"cloud_participates": True}})
    assert CW.status(ctx)["state"] in ("starting", "running", "off", "waiting", "re-enrolling", "error")


def test_lost_registration_enrolls_again_but_an_owner_revoke_stands(client, owner):
    """0.8.3: a registration lost any other way (replaced, invalid credential) no longer keeps MOTH Cloud
    out of shared training for good; only the Owner's revoke in Network does."""
    from starlette.testclient import TestClient

    from conftest import H
    from moth_server.db import now

    ctx = client.app.state.ctx
    r = CW.make_runner(ctx, TestClient(ctx.extras["app"]))
    first = ctx.db.one(select(workers))
    with ctx.db.tx() as c:  # lost without the Owner deciding it (e.g. replaced by a re-enrollment)
        c.execute(workers.update().where(workers.c.id == first["id"]).values(
            revoked_at=now(), status="revoked", token_hash=f"replaced-{first['id']}-1"))
    assert CW.allowed(ctx)
    r2 = CW.make_runner(ctx, TestClient(ctx.extras["app"]))
    assert r2 is not None
    live = ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
    assert len(live) == 1 and live[0]["id"] != first["id"] and live[0]["name"] == CW.NAME
    # the Owner revokes it in Network: it stays revoked and never enrolls again
    assert client.post(f"/v1/training/workers/{live[0]['id']}/revoke", headers=H(owner["token"])).status_code == 200
    assert CW.owner_revoked(ctx) and not CW.allowed(ctx)
    assert CW.make_runner(ctx, TestClient(ctx.extras["app"])) is None
    assert CW.status(ctx)["state"] == "revoked"
    assert len(ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))) == 0


def test_cloud_worker_and_a_real_worker_on_the_same_computer_coexist(client, settings, owner):
    """Same machine, same Owner account: neither registration may replace the other."""
    from starlette.testclient import TestClient

    from conftest import H
    from moth_worker.hardware import detect

    ctx = client.app.state.ctx
    r = CW.make_runner(ctx, TestClient(ctx.extras["app"]))
    r.beat()
    e = client.post("/v1/training/enrollments", json={"name": "owner-pc"}, headers=H(owner["token"])).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": detect(), "version": "0.7.2"}).json()
    assert client.post("/v1/worker/heartbeat", json={"version": "0.7.2", "hardware": detect()},
                       headers=H(w["worker_token"])).status_code == 200
    r.beat()
    live = ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
    assert sorted(x["name"] for x in live) == sorted([CW.NAME, "owner-pc"])
    assert not r.revoked
