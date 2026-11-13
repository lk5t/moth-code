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
    assert r.paused is True  # never two trainings on the server at once


def test_owner_choice_turns_it_off(client, owner):
    ctx = client.app.state.ctx
    assert CW.allowed(ctx)
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True}})
    assert not CW.allowed(ctx)
    S.update(ctx, {"backends": {"local_cpu": True, "local_gpu": True, "workers": True},
                   "distributed": {"cloud_participates": False}})
    assert not CW.allowed(ctx)
    S.update(ctx, {"distributed": {"cloud_participates": True}})
    ctx.db.set_config("cloud_worker_revoked", True)  # revoked by the Owner in Network
    assert not CW.allowed(ctx)
