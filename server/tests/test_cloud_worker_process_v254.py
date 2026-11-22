"""2.5.4: MOTH Cloud's built-in worker trains in its own process, so a large training job can no longer make
the server stop answering (or take it down when memory runs out). Pausing comes from the heartbeat."""
import json
import socket
import threading
import time

from sqlalchemy import select

from moth_server.db import evolution_experiments, now, workers
from moth_server.evolution import cloud_worker as CW, settings as S


def _plain_runner(ctx, client, cred):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    return WorkerRunner(WorkerClient("http://t", cred, http=client), ctx.settings.data_dir / "cw-test", allow_cpu=True,
                        log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None, dedicated=False)


def test_the_server_pauses_its_own_worker_through_the_heartbeat(client, owner):
    ctx = client.app.state.ctx
    cred = CW.credential(ctx)
    r = _plain_runner(ctx, client, cred)  # no in-process overrides: what the separate process runs
    r.beat()
    assert r.paused is False
    with ctx.db.tx() as c:  # MOTH Cloud trains locally: no new work
        c.execute(evolution_experiments.insert().values(cycle_id=1, status="running", backend="local", dataset_id=1,
                  base_version=1, base_sha256="0" * 64, config="{}", config_hash="x", created_at=now(), updated_at=now()))
    r.beat()
    assert r.paused is True
    with ctx.db.tx() as c:
        c.execute(evolution_experiments.update().values(status="done"))
    r.beat()
    assert r.paused is False
    S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True}})
    r.beat()
    assert r.paused is True  # turned off in AI Settings


def test_a_personal_worker_is_not_paused_by_local_training(client, owner):
    from test_network_v063 import _enroll

    ctx = client.app.state.ctx
    w = _enroll(client, owner)
    with ctx.db.tx() as c:
        c.execute(evolution_experiments.insert().values(cycle_id=1, status="running", backend="local", dataset_id=1,
                  base_version=1, base_sha256="0" * 64, config="{}", config_hash="x", created_at=now(), updated_at=now()))
    r = _plain_runner(ctx, client, w["worker_token"])
    r.beat()
    assert r.paused is False


def test_the_worker_runs_as_its_own_process_and_stops_when_turned_off(client, owner):
    import uvicorn

    ctx = client.app.state.ctx
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        deadline = time.time() + 20
        while not server.started and time.time() < deadline:
            time.sleep(0.1)
        cred = CW.credential(ctx)
        with ctx.db.tx() as c:  # enrollment counts as contact: clear it so only the process can set it
            c.execute(workers.update().values(last_heartbeat_at=None))
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("rc", CW._run_child(ctx, f"http://127.0.0.1:{port}", cred)),
                             daemon=True)
        t.start()
        w = None
        deadline = time.time() + 120
        while time.time() < deadline:  # the separate process connects and reports in
            w = ctx.db.one(select(workers).where(workers.c.name == CW.NAME))
            if w and w["last_heartbeat_at"] and w["version"] and "cloud_worker_proc" in ctx.extras:
                break
            time.sleep(0.5)
        assert w and w["last_heartbeat_at"] and w["version"], (ctx.settings.data_dir / "cloud-worker" / "worker.log").read_text()
        proc = ctx.extras["cloud_worker_proc"]
        assert proc.pid and proc.poll() is None
        assert not json.loads(w["hardware"]).get("machine_id") and not w["machine_id"]
        S.update(ctx, {"backends": {"local_cpu": False, "local_gpu": False, "workers": True}})
        t.join(60)
        assert not t.is_alive() and proc.poll() is not None  # turned off: the process is stopped
    finally:
        server.should_exit = True


def test_serve_tells_the_worker_where_the_server_listens(monkeypatch):
    import os
    import types

    from moth_server import cli

    seen = {}
    monkeypatch.delenv("MOTH_SERVER_LOCAL_URL", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: seen.update(kw))
    monkeypatch.setattr("moth_server.app.create_app", lambda: object())
    cli.cmd_serve(types.SimpleNamespace(host="0.0.0.0", port=8900))
    assert os.environ["MOTH_SERVER_LOCAL_URL"] == "http://127.0.0.1:8900" and seen["port"] == 8900
    monkeypatch.delenv("MOTH_SERVER_LOCAL_URL", raising=False)
