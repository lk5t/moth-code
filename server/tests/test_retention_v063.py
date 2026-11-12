"""0.6.3 model retention: after a promotion, the active and previous working models stay, older
versions are removed (records kept), and nothing in use or in progress is ever removed."""
from pathlib import Path

from moth_server import models as M
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S
from moth_server.evolution import storage as ST
from test_serving_v053 import _two_releases


def test_keeps_active_and_previous_removes_older(client, owner, tmp_path):
    from conftest import make_tiny_model

    ctx, active, prev = _two_releases(client, owner, tmp_path)
    old = M._register(ctx, make_tiny_model(tmp_path, 2, "older"), "older", {"type": "upload"}, None)
    assert M.evaluate(ctx, old["version"])["status"] == "published"
    old_path = M.release(ctx, old["version"])["path"]
    r = ST.apply_retention(ctx, prev)
    assert r["removed"] == [old["version"]] and set(r["kept"]) >= {active, prev}
    assert Path(M.deployed(ctx)["path"]).exists() and Path(M.release(ctx, prev)["path"]).exists()
    rel = M.release(ctx, old["version"])
    assert rel["status"] == "failed" and "retention" in rel["error"] and not Path(old_path).exists()
    assert any(e["kind"] == "storage.retention" for e in MEM.events(ctx, limit=10))
    assert ST.apply_retention(ctx, prev)["removed"] == []  # idempotent
    # the kept previous working model is a real rollback target
    from moth_server.evolution import engine as EN
    M._set(ctx, prev, "published")
    assert EN.rollback_to(ctx, prev, owner["user"]["id"])["version"] == prev and M.deployed(ctx)["version"] == prev


def test_retention_off_keeps_everything_and_deployed_is_never_removed(client, owner, tmp_path):
    ctx, old, new = _two_releases(client, owner, tmp_path)
    S.update(ctx, {"retention": {"models": 0}})
    assert ST.apply_retention(ctx, None)["removed"] == []
    S.update(ctx, {"retention": {"models": 1}})  # only the active model
    r = ST.apply_retention(ctx, None)
    dep = M.deployed(ctx)
    assert dep["version"] in r["kept"] and Path(dep["path"]).exists()
