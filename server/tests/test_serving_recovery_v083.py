"""0.8.3: MOTH Cloud never stays without a serving model while a verified one exists."""
from pathlib import Path

from moth_server import models as M
from moth_server.evolution import memory as MEM
from test_serving_v053 import _two_releases


def test_deployed_model_is_loaded_again_after_a_restart(client, owner, tmp_path):
    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    ctx.extras.pop("inference_engine")  # as after a restart whose load failed transiently
    rel = M.ensure_serving(ctx)
    assert rel["version"] == stable and ctx.extras["inference_engine"] is not None
    assert M.ensure_serving(ctx) is None  # serving: nothing to do


def test_unloadable_deployed_model_falls_back_and_tells_the_owner(client, owner, tmp_path):
    import json

    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    for v in (stable, cand):  # one lineage
        M._set(ctx, v, info=json.dumps({**M.release(ctx, v)["info"], "lineage_id": "moth"}))
    M.deploy(ctx, cand)  # cand is active, stable is the rollback model
    ctx.extras.pop("inference_engine")
    Path(M.release(ctx, cand)["path"], "model.pt").write_bytes(b"corrupted")  # cannot be loaded any more
    rel = M.ensure_serving(ctx)
    assert rel["version"] == stable and ctx.extras["inference_engine"] is not None  # answering continues
    ev = next(e for e in MEM.events(ctx, 10) if e["kind"] == "deploy.failed")
    assert f"v{cand} could not be loaded" in ev["message"] and f"serves v{stable}" in ev["message"]



def test_never_serves_another_lineage_or_after_a_reset(client, owner, tmp_path):
    import json

    ctx, stable, cand = _two_releases(client, owner, tmp_path)
    for v, lin in ((stable, "old-lineage"), (cand, "new-lineage")):
        M._set(ctx, v, info=json.dumps({**M.release(ctx, v)["info"], "lineage_id": lin}))
    M.deploy(ctx, cand)
    ctx.extras.pop("inference_engine")
    Path(M.release(ctx, cand)["path"], "model.pt").write_bytes(b"corrupted")
    assert M.ensure_serving(ctx) is None  # the only other version belongs to another lineage
    assert ctx.extras.get("inference_engine") is None
    assert any("no serving model" in e["message"] for e in MEM.events(ctx, 10))
    ctx.db.set_config("deployed_release", None)  # what a Genesis Reset leaves: nothing to restore
    assert M.ensure_serving(ctx) is None
