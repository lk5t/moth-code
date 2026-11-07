"""Growth evidence and distributed starts must belong to verified model state."""
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from moth_server import models as M
from moth_server.db import evolution_cycles, evolution_experiments, now, training_jobs
from moth_server.evolution import distributed, memory as MEM, v2


def test_growth_memory_admission_uses_expanded_candidate(client, tiny_model_dir):
    from moth.model.config import MothConfig
    from moth.model.growth import grown_config
    from moth_server.evolution import compute, engine

    ctx = client.app.state.ctx
    rel = M._register(ctx, tiny_model_dir, "memory-test", {"type": "upload"}, None)
    cfg = MothConfig.from_dict(json.loads((tiny_model_dir / "config.json").read_text()))
    grown = grown_config(cfg, 1, cfg.ffn_hidden + 64)
    exp = {"base_version": rel["version"], "config": {"batch_size": 4, "seq_len": 32}}
    before = engine._need_bytes(ctx, exp)
    exp["config"]["grow"] = {"params_after": grown.num_params(), "add_layers": 1}
    after = engine._need_bytes(ctx, exp)
    assert after > before
    assert after == compute.estimate_training_memory(grown.num_params(), 4, 32, grown.d_model, grown.n_layers)


def test_growth_evidence_excludes_unrelated_model_lineages(client):
    ctx = client.app.state.ctx
    MEM.record_lineage(ctx, 1, None, "foundation")
    MEM.record_lineage(ctx, 2, 1, "continued")
    MEM.record_lineage(ctx, 3, None, "foundation")
    for base, improvement in ((1, 0.1), (3, 0.0), (2, 0.002)):
        with ctx.db.tx() as c:
            cid = c.execute(evolution_cycles.insert().values(
                status="completed", trigger="manual", base_version=base, result='{"measured": true}',
                created_at=now(), updated_at=now())).inserted_primary_key[0]
            c.execute(evolution_experiments.insert().values(
                cycle_id=cid, status="passed", config="{}", config_hash=str(cid), dataset_id=1,
                base_version=base, base_sha256="a" * 64,
                metrics=json.dumps({"primary_improvement": improvement}), created_at=now(), updated_at=now()))
    evidence = v2.growth_evidence(ctx, {"version": 2, "info": {}})
    assert evidence["recent_improvements"] == [0.1, 0.002]


@pytest.mark.parametrize("source", ["weights", "dev_checkpoint", "missing_dev_checkpoint"])
def test_distributed_start_refuses_corrupted_or_missing_base(client, tiny_model_dir, tmp_path, source):
    ctx = client.app.state.ctx
    rel = M._register(ctx, tiny_model_dir, "integrity-test", {"type": "upload"}, None)
    if source == "weights":
        (Path(rel["path"]) / "model.pt").write_bytes(b"damaged weights")
    else:
        dev = tmp_path / "development.pt"
        if source == "dev_checkpoint":
            dev.write_bytes(b"damaged checkpoint")
        M._set(ctx, rel["version"], None, info=json.dumps({**rel["info"],
               "dev_checkpoint": {"path": str(dev), "sha256": "a" * 64}}))
    exp = {"id": 1, "base_version": rel["version"], "config": {"steps": 2}}
    with pytest.raises(ValueError, match="checksum-verified"):
        distributed.start(ctx, exp, {}, need_bytes=1)
    assert not ctx.db.all(select(training_jobs))
