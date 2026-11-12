"""0.7.0 model identity: MOTH 0.0.1 → 0.0.2 … on verified upgrades only; older labels migrate once."""
import json
from pathlib import Path

from conftest import make_tiny_model
from moth_server import models as M
from moth_server.evolution import identity
from moth_server.evolution import memory as MEM


def test_versions_count_verified_upgrades():
    assert identity.next_version(None) == "0.0.1"
    assert identity.next_version("0.0.9") == "0.0.10"
    assert identity.next_version("0.01") == "0.0.1"  # legacy labels never continue as-is
    assert identity.is_current("0.0.3") and not identity.is_current("0.02")


def test_pre_070_versions_are_renumbered_once_per_lineage_without_touching_weights(client, tmp_path):
    from moth_server import serving

    ctx = client.app.state.ctx
    ctx.db.set_config(identity.FLAG, None)
    rels = []
    for i, legacy in enumerate(["0.01", "0.01", "0.02"]):
        r = M._register(ctx, make_tiny_model(tmp_path, i, f"m{i}"), f"m{i}", {"type": "upload"}, None)
        info = {**M.release(ctx, r["version"])["info"], "model_version": legacy, "display_name": f"MOTH {legacy}",
                "lineage_id": "L1"}
        M._set(ctx, r["version"], info=json.dumps(info))
        serving.sign_release(ctx, r["version"])
        rels.append(M.release(ctx, r["version"]))
    other = M._register(ctx, make_tiny_model(tmp_path, 9, "other"), "other", {"type": "upload"}, None)
    M._set(ctx, other["version"], info=json.dumps({**M.release(ctx, other["version"])["info"], "model_version": "0.05",
                                                    "lineage_id": "L2"}))
    weights = {r["version"]: Path(r["path"], "model.pt").read_bytes() for r in rels}
    out = identity.migrate(ctx)
    got = [M.release(ctx, r["version"])["info"] for r in rels]
    assert [g["model_version"] for g in got] == ["0.0.1", "0.0.2", "0.0.3"]
    assert [g["model_version_legacy"] for g in got] == ["0.01", "0.01", "0.02"]
    assert got[-1]["display_name"] == "MOTH 0.0.3"
    assert M.release(ctx, other["version"])["info"]["model_version"] == "0.0.1"  # its own lineage starts at 0.0.1
    for r in rels:
        assert Path(r["path"], "model.pt").read_bytes() == weights[r["version"]]  # weights untouched
        signed = json.loads(Path(r["path"], "model-manifest.json").read_text())
        assert signed["model_version"] == M.release(ctx, r["version"])["info"]["model_version"]  # re-signed
    assert out["migrated"] == 4 and identity.migrate(ctx)["already"]
    assert any(e["kind"] == "model.identity_migrated" for e in MEM.events(ctx, 20))
