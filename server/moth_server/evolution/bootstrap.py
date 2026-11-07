"""Explicit, recoverable initialization of an empty native MOTH lineage.

This creates random weights, not a trained or deployment-approved model. Existing
registry entries or checkpoint files always take precedence over initialization.
"""
from pathlib import Path

from moth_server import models as M
from moth_server.context import Ctx


def initialize(ctx: Ctx, actor_id: int | None = None) -> dict:
    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import Tokenizer
    from moth.model.transformer import MothModel
    from moth.training.checkpoint import RunLock, atomic_torch_save, file_sha256, verify
    from moth_server.evolution import v2

    root = Path(ctx.settings.data_dir) / "lineage" / "initial"
    with RunLock(root, "MOTH lineage initialization"):
        existing = M.deployed(ctx) or next(iter(M.list_releases(ctx)), None)
        if existing:
            return {"created": False, "model": existing}
        checkpoint = root / "seed.pt"
        # Do not silently replace unregistered training progress either.
        allowed = {checkpoint, root / "packages" / "moth-0.01" / "model.pt"} if checkpoint.exists() else {checkpoint}
        if any(p not in allowed for p in Path(ctx.settings.data_dir).rglob("*.pt")):
            raise ValueError("Existing unregistered weights found; import that checkpoint before initializing a lineage")
        tok_path = root / "tokenizer.json"
        if not checkpoint.exists():
            # Byte vocabulary is lossless and needs no external training material.
            tok = Tokenizer([])
            tok.save(tok_path)
            cfg = preset("moth-tiny", vocab_size=tok.vocab_size, ffn_hidden=128)
            cfg.name = "moth-0.01"
            model = MothModel(cfg)
            atomic_torch_save({"model": model.state_dict(), "model_config": cfg.to_dict(),
                               "tokenizer_path": str(tok_path), "tokenizer_fingerprint": tok.fingerprint(),
                               "step": 0, "tokens_seen": 0, "train_config": {}}, checkpoint)
        if not verify(checkpoint):
            raise ValueError("Initial checkpoint integrity failed; refusing to reset it")
        package = root / "packages" / "moth-0.01"
        if not package.exists():
            export_model(checkpoint, package.parent, package.name, dtype="float32", extra={
                "model_version": "0.01", "display_name": "MOTH 0.01", "family": "MOTH",
                "lineage_id": "native-moth", "initialization": "random-untrained"})
        rel = M._register(ctx, package, "MOTH 0.01 (untrained)", {"type": "native-initialization"}, actor_id)
        dev = v2.store_dev_checkpoint(ctx, rel["version"], str(checkpoint), file_sha256(checkpoint))
        import json

        M._set(ctx, rel["version"], info=json.dumps({**rel["info"], "initialization": "random-untrained",
                                                   "lineage_totals": {"steps": 0, "tokens": 0, "cycles": 0},
                                                   "dev_checkpoint": dev}))
        return {"created": True, "model": M.release(ctx, rel["version"])}
