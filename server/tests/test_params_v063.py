"""0.6.3: every parameter count MOTH displays is counted from the saved weights.

Independent check used throughout: load the release's model.pt into the architecture its config.json
describes and count ``model.parameters()`` (tied weights once, buffers excluded) — then compare with
what each API the app reads returns for that version.
"""
import json
from pathlib import Path

import pytest
import torch

from conftest import H, make_tiny_model
from moth_server import models as M
from moth_server.evolution import engine as EN
from moth_server.evolution import memory as MEM


def counted_from_weights(path: str | Path) -> tuple[int, int]:
    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    d = Path(path)
    cfg = MothConfig.from_dict(json.loads((d / "config.json").read_text()))
    model = MothModel(cfg)
    model.load_state_dict(torch.load(d / "model.pt", map_location="cpu", weights_only=True), strict=True)
    return (sum(p.numel() for p in model.parameters()),
            sum(p.numel() for p in model.parameters() if p.requires_grad))


def _model(tmp_path, seed, **overrides):
    """A real exported model; ``overrides`` change the architecture (a different size)."""
    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import Tokenizer, train_bpe
    from moth.model.transformer import MothModel

    tok_path = tmp_path / "tok.json"
    if not tok_path.exists():
        train_bpe(["def add(a, b):\n    return a + b\n"] * 20, vocab_size=300).save(tok_path)
    tok = Tokenizer.load(tok_path)
    torch.manual_seed(seed)
    cfg = preset("moth-tiny", vocab_size=320, **overrides)
    ck = tmp_path / f"ck-{seed}.pt"
    torch.save({"model": MothModel(cfg).state_dict(), "model_config": cfg.to_dict(), "tokenizer_path": str(tok_path),
                "tokenizer_fingerprint": tok.fingerprint(), "step": 1}, ck)
    info = export_model(ck, tmp_path / "models", f"m{seed}", dtype="float32")
    return tmp_path / "models" / info["id"]


def _deploy(client, owner, ctx, version):
    assert M.evaluate(ctx, version)["status"] == "published"
    M.deploy(ctx, version)


def test_displayed_count_equals_the_saved_weights_on_every_api(client, owner, tmp_path):
    ctx = client.app.state.ctx
    rel = M._register(ctx, make_tiny_model(tmp_path, 0, "real"), "real", {"type": "upload"}, None)
    total, trainable = counted_from_weights(M.release(ctx, rel["version"])["path"])
    info = M.release(ctx, rel["version"])["info"]
    assert info["params_measured"]["total"] == total and info["params_measured"]["trainable"] == trainable
    assert info["params_measured"]["source"] == "weights" and info["params"] == total
    _deploy(client, owner, ctx, rel["version"])
    o = H(owner["token"])
    overview = client.get("/v1/admin/model-overview", headers=o).json()["model"]
    assert overview["params"] == total and overview["params_verified"] is True
    progress = client.get("/v1/intelligence/progress", headers=o).json()["current"]
    assert progress["params"] == total and progress["params_verified"] is True
    versions = client.get("/v1/admin/evolution/versions", headers=o).json()
    rows = versions["versions"] if isinstance(versions, dict) else versions
    row = next(r for r in rows if r["version"] == rel["version"])
    assert row["params"] == total and row["params_verified"] is True


def test_each_version_reports_its_own_architecture(client, owner, tmp_path):
    ctx = client.app.state.ctx
    small = M._register(ctx, _model(tmp_path, 1, ffn_hidden=128), "small", {"type": "upload"}, None)
    larger = M._register(ctx, _model(tmp_path, 2, n_layers=3), "larger", {"type": "upload"}, None)
    counts = {r["version"]: counted_from_weights(M.release(ctx, r["version"])["path"])[0] for r in (small, larger)}
    assert counts[small["version"]] != counts[larger["version"]]
    for v, n in counts.items():
        assert M.release(ctx, v)["info"]["params"] == n
        assert M.release(ctx, v)["info"]["params_measured"]["total"] == n
    rows = client.get("/v1/admin/evolution/versions", headers=H(owner["token"])).json()
    rows = rows["versions"] if isinstance(rows, dict) else rows
    for r in rows:
        if r["version"] in counts:
            assert r["params"] == counts[r["version"]]


def test_weights_that_do_not_match_the_declared_architecture_are_rejected(client, tmp_path):
    from moth.model.package import inspect_package

    d = make_tiny_model(tmp_path, 3, "tampered")
    cfg = json.loads((d / "config.json").read_text())
    manifest = json.loads((d / "manifest.json").read_text())
    from moth.model.config import MothConfig

    bigger = MothConfig.from_dict({**cfg, "n_layers": cfg["n_layers"] + 2})
    # config and manifest both claim a larger model; the weights are the small one
    (d / "config.json").write_text(json.dumps(bigger.to_dict()))
    (d / "manifest.json").write_text(json.dumps({**manifest, "params": bigger.num_params()}))
    check = inspect_package(d, deep=True)
    assert not check["ok"] and any("missing" in p for p in check["problems"]), check["problems"]
    with pytest.raises(M.ReleaseError):
        M._register(client.app.state.ctx, d, "tampered", {"type": "upload"}, None)


def test_a_stale_registry_count_is_corrected_from_the_weights(client, owner, tmp_path):
    ctx = client.app.state.ctx
    rel = M._register(ctx, make_tiny_model(tmp_path, 4, "older"), "older", {"type": "upload"}, None)
    total, _ = counted_from_weights(M.release(ctx, rel["version"])["path"])
    # as a release registered before 0.6.3 with a wrong count would look
    info = dict(M.release(ctx, rel["version"])["info"])
    info.pop("params_measured")
    info["params"] = 5_200_000
    M._set(ctx, rel["version"], info=json.dumps(info))
    assert not M.params_verified(M.release(ctx, rel["version"])["info"])
    assert M.verify_next_unmeasured(ctx) == rel["version"]
    info = M.release(ctx, rel["version"])["info"]
    assert info["params"] == total and info["params_registered"] == 5_200_000 and M.params_verified(info)
    ev = next(e for e in MEM.events(ctx, 20) if e["kind"] == "model.params_corrected")
    assert f"{total:,}" in ev["message"] and "5,200,000" in ev["message"]
    assert M.verify_next_unmeasured(ctx) is None  # nothing left to measure


def test_growth_decisions_appear_in_the_activity_feed(client, owner, tmp_path):
    ctx = client.app.state.ctx
    rel = M._register(ctx, make_tiny_model(tmp_path, 5, "base"), "base", {"type": "upload"}, None)
    base = M.release(ctx, rel["version"])
    cyc = {"id": None}
    settings = {"growth": {"enabled": True}}
    still = {"grow": False, "params_before": base["info"]["params"],
             "reason": "the model is still improving (+28.24% in a recent cycle): no growth"}
    EN._growth_event(ctx, cyc, base, still, settings)
    EN._growth_event(ctx, cyc, base, still, settings)  # same reason: not repeated
    ev = [e for e in MEM.events(ctx, 50) if e["kind"] == "growth.not_proposed"]
    assert len(ev) == 1 and "still improving" in ev[0]["message"] and f"{base['info']['params']:,}" in ev[0]["message"]
    grow = {"grow": True, "params_before": 1000, "params_after": 1200, "ratio": 1.2, "add_layers": 1,
            "ffn_hidden": 128, "requires_approval": False,
            "reason": "held-out improvement below 1% for 3 cycles without overfitting"}
    EN._growth_event(ctx, cyc, base, grow, settings)
    proposed = next(e for e in MEM.events(ctx, 50) if e["kind"] == "growth.proposed")
    assert "1,000 → 1,200" in proposed["message"] and proposed["data"]["params_after"] == 1200
    EN._growth_event(ctx, cyc, base, None, {"growth": {"enabled": False}})
    assert any("turned off" in e["message"] for e in MEM.events(ctx, 50) if e["kind"] == "growth.not_proposed")
