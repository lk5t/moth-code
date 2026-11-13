"""0.7.1: one active model and one rollback model, as the Model tab shows them."""
from pathlib import Path

from conftest import H, make_tiny_model
from moth_server import models as M
from moth_server.evolution import storage as ST
from test_serving_v053 import _two_releases


def test_rollback_target_is_previous_working_model_and_progress_reports_it(client, owner, tmp_path):
    ctx, first, second = _two_releases(client, owner, tmp_path)
    older = M._register(ctx, make_tiny_model(tmp_path, 2, "older"), "older", {"type": "upload"}, None)
    assert M.evaluate(ctx, older["version"])["status"] == "published"
    M.deploy(ctx, second)  # a promotion: `first`… is no longer active
    # the rollback model is the newest verified version before the active one whose files exist
    assert ST.rollback_target(ctx) == first
    removed = ST.apply_retention(ctx, ST.rollback_target(ctx))["removed"]
    assert removed == [older["version"]]
    assert ST.rollback_target(ctx) == first and Path(M.release(ctx, first)["path"]).exists()
    p = client.get("/v1/intelligence/progress", headers=H(owner["token"])).json()
    assert p["lifecycle"]["active"] == second and p["lifecycle"]["rollback"] == first


def test_without_a_working_previous_model_there_is_no_rollback(client, owner, tmp_path):
    ctx, first, second = _two_releases(client, owner, tmp_path)
    assert ST.rollback_target(ctx) is None  # the active model is the oldest one
    M.deploy(ctx, second)
    M._set(ctx, first, "failed", path="")  # its files were removed earlier
    assert ST.rollback_target(ctx) is None
