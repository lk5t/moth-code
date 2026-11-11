"""0.6.2 storage management: protected items stay, removable items are deleted, re-checked at deletion."""
from pathlib import Path

from conftest import H
from moth_server import models as M
from moth_server.evolution import backends as B
from moth_server.evolution import storage as ST
from test_serving_v053 import _two_releases

BASE = "/v1/admin/evolution"


def test_deployed_and_rollback_models_are_protected_rejected_candidates_removable(client, owner, tmp_path):
    ctx, old, new = _two_releases(client, owner, tmp_path)
    o = H(owner["token"])
    # a rejected candidate: evaluated but not promoted
    cand = M.release(ctx, new)
    M._set(ctx, new, "evaluated")
    s = client.get(f"{BASE}/storage", headers=o).json()
    models = {i["id"]: i for c in s["categories"] if c["id"] == "models" for i in c["items"]}
    dep = M.deployed(ctx)["version"]
    assert models[f"model:{dep}"]["protected"] and "Deployed" in models[f"model:{dep}"]["reason"]
    assert not models[f"model:{new}"]["protected"] and models[f"model:{new}"]["bytes"] > 0
    # cleanup refuses protected items and removes the removable one
    r = client.post(f"{BASE}/storage/cleanup", headers=o, json={"items": [f"model:{dep}", f"model:{new}", "model:999"]}).json()
    assert r["removed"] == [f"model:{new}"] and r["freed_bytes"] > 0
    assert {x["id"] for x in r["skipped"]} == {f"model:{dep}", "model:999"}
    assert not Path(cand["path"]).exists() and Path(M.deployed(ctx)["path"]).exists()
    assert M.release(ctx, new)["status"] == "failed" and "storage cleanup" in M.release(ctx, new)["error"]


def test_run_folders_of_active_work_are_kept(client, owner):
    ctx = client.app.state.ctx
    d = B.runs_root(ctx) / "exp-00042"
    d.mkdir(parents=True)
    (d / "events.jsonl").write_text("x" * 1000)
    it = next(i for i in ST.items(ctx) if i["id"] == "run:42")
    assert not it["protected"] and it["bytes"] == 1000  # no experiment 42 is active
    assert client.post(f"{BASE}/storage/cleanup", headers=H(owner["token"]), json={"items": ["run:42"]}).json()["removed"] == ["run:42"]
    assert not d.exists()


def test_only_the_owner_and_never_path_escapes(client, owner, settings):
    from conftest import register_verified

    user = register_verified(client, settings, "storageuser")["token"]
    assert client.get(f"{BASE}/storage", headers=H(user)).status_code == 403
    r = client.post(f"{BASE}/storage/cleanup", headers=H(owner["token"]), json={"items": ["cache:../../keys"]}).json()
    assert r["removed"] == [] and r["skipped"][0]["reason"] == "no longer exists"
