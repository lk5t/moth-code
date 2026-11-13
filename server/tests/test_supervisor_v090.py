"""0.9.0: the self-healing supervisor repairs known bad states and reports what it did."""
import logging
import shutil
import time
from collections import namedtuple

from conftest import H
from moth_server.db import library_builds, now
from moth_server.evolution import memory as MEM, supervisor as SV
from test_serving_v053 import _two_releases


def test_serving_is_restored_and_recorded(client, owner, tmp_path):
    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    ctx.extras.pop("inference_engine")
    r = SV._check_serving(ctx)
    assert r and r["ok"] and ctx.extras["inference_engine"] is not None
    assert SV._check_serving(ctx) is None  # nothing to repair now
    assert any(e["kind"] == "supervisor.repaired" for e in MEM.events(ctx, 5))


def test_a_problem_that_keeps_coming_back_is_escalated(client, owner):
    ctx = client.app.state.ctx
    for _ in range(3):
        SV._record(ctx, "the model pipeline had stopped", "started it again", True)
    ev = [e for e in MEM.events(ctx, 10) if e["kind"] == "supervisor.attention"]
    assert len(ev) == 1 and "keeps having the same problem" in ev[0]["message"]
    SV._record(ctx, "the model pipeline had stopped", "started it again", True)
    assert len([e for e in MEM.events(ctx, 10) if e["kind"] == "supervisor.attention"]) == 1  # reported once


def test_a_stalled_data_preparation_is_retried(client, owner):
    ctx = client.app.state.ctx
    with ctx.db.tx() as c:
        bid = c.execute(library_builds.insert().values(status="running", manifest="{}", created_at=now() - 10_000)
                        ).inserted_primary_key[0]
    ctx.db.set_config(f"library_progress_{bid}", {"message": "tokenizing", "updated_at": time.time() - 3 * 3600})
    assert SV._check_build(ctx)["ok"]
    assert ctx.db.one(library_builds.select().where(library_builds.c.id == bid))["status"] == "failed"


def test_low_disk_cleans_only_removable_items(client, owner, monkeypatch):
    from moth_server.evolution import storage

    ctx = client.app.state.ctx
    usage = namedtuple("u", "total used free")
    state = {"free": 0}
    monkeypatch.setattr(shutil, "disk_usage", lambda p: usage(100, 100, state["free"]))
    monkeypatch.setattr(storage, "items", lambda ctx: [
        {"id": "run:1", "category": "runs", "protected": False, "bytes": 5},
        {"id": "model:3", "category": "models", "protected": True, "bytes": 9},
        {"id": "cache:x", "category": "cache", "protected": False, "bytes": 7}])
    removed = []

    def cleanup(ctx, ids, actor):
        removed.extend(ids)
        state["free"] = 10 ** 13  # enough after the first round
        return {"freed_bytes": 5 * 1024 ** 3}

    monkeypatch.setattr(storage, "cleanup", cleanup)
    r = SV._check_disk(ctx)
    assert r["ok"] and removed == ["run:1"]  # protected never, the download cache only if still short


def test_diagnostics_page_shows_loops_repairs_and_redacted_errors(client, owner):
    ctx = client.app.state.ctx
    SV.ring(ctx)
    logging.getLogger("moth_server.test").error("upload failed with token ghp_abcdefghijklmnopqrstuvwxyz0123456789AB")
    SV._record(ctx, "no model was serving although one is deployed", "loaded v2", True)
    assert client.get("/v1/admin/evolution/diagnostics").status_code == 401
    d = client.get("/v1/admin/evolution/diagnostics", headers=H(owner["token"])).json()
    assert {l["name"] for l in d["loops"]} >= {"evolution", "pipeline", "cloud-worker", "supervisor"}
    assert d["repairs"][0]["action"] == "loaded v2"
    err = next(e for e in d["errors"] if "upload failed" in e["message"])
    assert "abcdefghijklmnop" not in err["message"]  # credentials are redacted before they are kept
    assert "Recent self-repairs" in d["report"] and "loaded v2" in d["report"] and "abcdefghijklmnop" not in d["report"]
    assert client.post("/v1/admin/evolution/diagnostics/check", headers=H(owner["token"])).status_code == 200
