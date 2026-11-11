"""Genesis Reset entry (RESET GENESIS), fresh genesis with a chosen size and tokenizer, and the
Owner-requested growth experiment. Destructive tests use ONLY temporary fixture deployments."""

import json

from conftest import H, register_verified
from moth_server import models as M
from moth_server.evolution import engine as EN
from moth_server.evolution import memory as MEM
from moth_server.evolution import native_reset as R
from moth_server.evolution import settings as S
from test_evolution import FAST, drive
from test_evolution_v053 import _library, _world
from test_serving_v053 import _two_releases

BASE = "/v1/admin/evolution"


def test_reset_genesis_phrase_legacy_phrase_and_ready_state(client, owner, settings, tmp_path):
    ctx, old, _ = _two_releases(client, owner, tmp_path)
    o = H(owner["token"])
    st = client.get(f"{BASE}/native-reset", headers=o).json()
    assert st["confirmation"] == "RESET GENESIS" and st["ready_for_genesis"] is False  # models exist
    plan = client.post(f"{BASE}/native-reset/preview", headers=o, json={}).json()
    for wrong in ("reset genesis", "RESET", ""):
        r = client.post(f"{BASE}/native-reset/execute", headers=o, json={"reset_id": plan["id"], "confirmation": wrong})
        assert r.status_code == 422 and "RESET GENESIS" in r.text and M.deployed(ctx)["version"] == old
    done = client.post(f"{BASE}/native-reset/execute", headers=o, json={"reset_id": plan["id"], "confirmation": "RESET GENESIS"})
    assert done.status_code == 200 and done.json()["status"] == "completed" and done.json()["ready_for_genesis"] is True
    assert M.deployed(ctx) is None and not M.list_releases(ctx)
    # an ordinary user can neither inspect nor run it
    user = register_verified(client, settings, "notowner")["token"]
    assert client.get(f"{BASE}/native-reset", headers=H(user)).status_code == 403
    assert client.post(f"{BASE}/native-reset/preview", headers=H(user), json={}).status_code == 403
    # the progress every client reads reports the empty state
    p = client.get("/v1/intelligence/progress", headers=H(user)).json()
    assert p["current"] is None


def test_published_060_desktop_phrase_still_works(client, owner, tmp_path):
    ctx, _, _ = _two_releases(client, owner, tmp_path)
    o = H(owner["token"])
    plan = client.post(f"{BASE}/native-reset/preview", headers=o, json={}).json()
    r = client.post(f"{BASE}/native-reset/execute", headers=o, json={"reset_id": plan["id"], "confirmation": R.LEGACY_CONFIRM})
    assert r.status_code == 200 and r.json()["status"] == "completed"


def test_fresh_genesis_with_chosen_size_after_reset(client, owner, tmp_path):
    ctx, _, _ = _two_releases(client, owner, tmp_path)
    o = H(owner["token"])
    assert client.get(f"{BASE}/initialize/options", headers=o).json()["can_initialize"] is False  # a lineage exists
    plan = client.post(f"{BASE}/native-reset/preview", headers=o, json={}).json()
    assert client.post(f"{BASE}/native-reset/execute", headers=o, json={"reset_id": plan["id"], "confirmation": "RESET GENESIS"}).status_code == 200
    opts = client.get(f"{BASE}/initialize/options", headers=o).json()
    assert opts["can_initialize"] is True
    sizes = {s["id"]: s for s in opts["sizes"]}
    assert set(sizes) == {"seed", "small", "foundation"}
    assert sizes["seed"]["tokenizers"]["byte"]["params"] == 99_648  # the original GENESIS seed, unchanged
    small = sizes["small"]["tokenizers"]["byte"]
    assert small["params"] > 4_000_000 and sizes["foundation"]["tokenizers"]["byte"]["params"] > 40_000_000
    lib = next(t for t in opts["tokenizers"] if t["id"] == "library")
    assert lib["available"] is False  # nothing prepared after the reset
    r = client.post(f"{BASE}/initialize", headers=o, json={"size": "small", "tokenizer": "library"})
    assert r.status_code == 409 and "prepare data" in r.text
    assert client.post(f"{BASE}/initialize", headers=o, json={"size": "huge"}).status_code == 409
    r = client.post(f"{BASE}/initialize/activate", headers=o, json={"size": "small", "tokenizer": "byte"})
    assert r.status_code == 200, r.text
    rel = M.deployed(ctx)
    assert rel["info"]["params"] == small["params"] and rel["info"]["genesis"] == {"size": "small", "tokenizer": "byte"}
    # the count the app shows is the count of the weights actually deployed
    import torch

    state = torch.load(f"{rel['path']}/model.pt", map_location="cpu", weights_only=True)
    seen, total = set(), 0
    for t in state.values():  # tied embeddings share storage: count each tensor once
        if t.data_ptr() not in seen:
            seen.add(t.data_ptr())
            total += t.numel()
    cfg = json.loads(open(f"{rel['path']}/config.json").read())
    assert total - (cfg["vocab_size"] * cfg["d_model"] if cfg.get("tie_embeddings", True) and total > rel["info"]["params"] else 0) == rel["info"]["params"]
    p = client.get("/v1/intelligence/progress", headers=o).json()
    assert p["current"]["params"] == small["params"] and p["current"]["initialization"] == "random-untrained"


def test_default_initialization_is_unchanged_for_old_clients(client, owner):
    o = H(owner["token"])
    r = client.post(f"{BASE}/initialize/activate", headers=o)  # no body: what a 0.6.0 desktop sends
    assert r.status_code == 200, r.text
    assert M.deployed(client.app.state.ctx)["info"]["params"] == 99_648


def test_library_tokenizer_genesis(client, owner, monkeypatch):
    """Prepare data first (the build trains a tokenizer), then start the lineage with that tokenizer."""
    ctx = client.app.state.ctx
    o = H(owner["token"])
    _library(ctx, owner, monkeypatch)
    opts = client.get(f"{BASE}/initialize/options", headers=o).json()
    lib = next(t for t in opts["tokenizers"] if t["id"] == "library")
    assert lib["available"] is True
    seed = {s["id"]: s for s in opts["sizes"]}["seed"]["tokenizers"]
    assert seed["library"]["vocab"] > seed["byte"]["vocab"] and seed["library"]["params"] > seed["byte"]["params"]
    r = client.post(f"{BASE}/initialize/activate", headers=o, json={"size": "seed", "tokenizer": "library"})
    assert r.status_code == 200, r.text
    rel = M.deployed(ctx)
    from moth_server.intelligence import library

    assert rel["info"]["tokenizer_fingerprint"] == library.latest_ready(ctx)["tokenizer_fingerprint"]
    assert rel["info"]["params"] == seed["library"]["params"]


def test_owner_requested_growth_is_a_gated_candidate(client, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    o = H(owner["token"])
    S.update(ctx, {**FAST, "max_experiments_per_cycle": 1, "paused": True})  # nothing runs until asked
    d = client.get(f"{BASE}/growth-diagnostics", headers=o).json()
    assert d["options"] and d["request"] is None and d["decision"]["grow"] is False  # no plateau evidence
    before = d["architecture_params"]
    assert client.post(f"{BASE}/growth-request", headers=o, json={"add_layers": 7, "ffn_hidden": 64}).status_code == 409
    opt = d["options"][0]
    r = client.post(f"{BASE}/growth-request", headers=o, json={"add_layers": opt["add_layers"], "ffn_hidden": opt["ffn_hidden"]})
    assert r.status_code == 200 and r.json()["request"]["params"] == opt["params"]
    S.update(ctx, {"paused": False})
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=900)
    grow = next(e for e in MEM.experiments(ctx, cyc["id"]) if e["config"].get("method") == "expansion")
    assert "Owner-requested" in grow["rationale"] and grow["status"] in ("passed", "rejected"), grow["error"]
    cand = M.release(ctx, grow["candidate_version"])
    assert cand["info"]["params"] == opt["params"] > before  # the candidate really is larger
    assert ctx.db.get_config("growth_request") is None  # one request, one experiment
    deployed = M.deployed(ctx)
    if grow["status"] == "rejected":  # a failed expansion never touches the deployed model
        assert deployed["info"]["params"] == before
    else:
        assert any(g["gate"] == "target_improvement" and g["passed"] for g in grow["metrics"]["gates"])
    # the base weights were not modified either way
    assert M.release(ctx, base_v)["info"]["params"] == before
