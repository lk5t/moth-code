"""Explicit, recoverable initialization of an empty native MOTH lineage.

This creates random weights, not a trained or deployment-approved model. Existing
registry entries or checkpoint files always take precedence over initialization.
"""
from pathlib import Path

from moth_server import models as M
from moth_server.context import Ctx


# Sizes a fresh lineage can start from. "seed" is the original GENESIS start (kept as the default so
# existing behaviour and old clients are unchanged); larger sizes need more memory and far more training.
SIZES = {
    "seed": {"preset": "moth-tiny", "overrides": {"ffn_hidden": 128}, "label": "Seed",
             "note": "Trains in minutes on any CPU. Learns very little; useful to verify the pipeline."},
    "small": {"preset": "moth-small", "overrides": {}, "label": "Small",
              "note": "CPU-trainable in hours to days. Can learn simple language and code patterns."},
    "foundation": {"preset": "moth-50m", "overrides": {}, "label": "Foundation",
                   "note": "Needs a GPU worker or many CPU-days to train usefully."},
}
TOKENIZERS = ("byte", "library")


def _library_tokenizer(ctx: Ctx) -> Path | None:
    """The tokenizer trained by the newest ready dataset-library build (only when no model exists)."""
    from moth_server.intelligence import library

    b = library.latest_ready(ctx)
    p = Path(b["path"]) / "tokenizer.json" if b and b.get("path") else None
    return p if p and p.is_file() else None


def _config(size: str, vocab: int):
    from moth.model.config import preset

    if size not in SIZES:
        raise ValueError(f"Unknown model size {size!r}; choose one of: {', '.join(SIZES)}")
    spec = SIZES[size]
    cfg = preset(spec["preset"], vocab_size=vocab, **spec["overrides"])
    cfg.name = "moth-0.01"
    return cfg


def options(ctx: Ctx) -> dict:
    """What a fresh lineage can start from: real parameter counts per size and tokenizer, with the memory
    estimate and whether this deployment has a backend that can train it. Nothing is created."""
    from moth.model.tokenizer import Tokenizer
    from moth_server.evolution import compute as C, settings as S

    settings = S.get(ctx)
    tr = settings["training"]
    lib = _library_tokenizer(ctx)
    vocabs = {"byte": Tokenizer([]).vocab_size}
    if lib is not None:
        vocabs["library"] = Tokenizer.load(lib).vocab_size
    sizes = []
    for key, spec in SIZES.items():
        row = {"id": key, "label": spec["label"], "note": spec["note"], "tokenizers": {}}
        for tok, vocab in vocabs.items():
            cfg = _config(key, vocab)
            need = C.estimate_training_memory(cfg.num_params(), tr["batch_size"], min(tr["seq_len"], cfg.max_seq_len),
                                              cfg.d_model, cfg.n_layers)
            backend, reasons = C.choose_backend(ctx, settings, need)
            row["tokenizers"][tok] = {"params": cfg.num_params(), "layers": cfg.n_layers, "d_model": cfg.d_model,
                                      "context": cfg.max_seq_len, "vocab": vocab, "training_memory_bytes": need,
                                      "trainable_here": backend is not None, "blockers": reasons if backend is None else []}
        sizes.append(row)
    existing = M.deployed(ctx) or next(iter(M.list_releases(ctx)), None)
    return {"sizes": sizes, "tokenizers": [
        {"id": "byte", "label": "Byte-level", "available": True,
         "note": "Lossless, needs no data. Every character costs one or more tokens, so context is short."},
        {"id": "library", "label": "Trained on the dataset library", "available": lib is not None,
         "note": "A BPE vocabulary learned from the prepared library: several characters per token."
                 if lib is not None else "Prepare the dataset library first (Data); its build trains this tokenizer."}],
        "can_initialize": existing is None, "existing": existing["name"] if existing else None}


def initialize(ctx: Ctx, actor_id: int | None = None, size: str = "seed", tokenizer: str = "byte") -> dict:
    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import Tokenizer
    from moth.model.transformer import MothModel
    from moth.training.checkpoint import RunLock, atomic_torch_save, file_sha256, verify
    from moth_server.evolution import v2

    root = Path(ctx.settings.data_dir) / "lineage" / "initial"
    with RunLock(root, "MOTH lineage initialization"):
        existing = M.deployed(ctx) or next(iter(M.list_releases(ctx)), None)
        recovering = bool(existing and existing['status'] == 'uploading' and
                          existing['info'].get('source', {}).get('type') == 'native-initialization')
        if existing and not recovering:
            return {"created": False, "model": existing}
        checkpoint = root / "seed.pt"
        if recovering and not checkpoint.exists():
            raise ValueError('The initial checkpoint is missing; refusing to reset interrupted initialization')
        # Do not silently replace unregistered training progress either.
        allowed = {checkpoint, root / "packages" / "moth-0.01" / "model.pt"} if checkpoint.exists() else {checkpoint}
        if recovering:
            allowed.add(M.releases_dir(ctx) / f"v{existing['version']:05d}" / 'model.pt')
        from moth_server.evolution.native_reset import state as reset_state, ROOTS
        reset_completed=reset_state(ctx).get('status')=='completed'
        owned_roots=[Path(ctx.settings.data_dir)/relative for relative in ROOTS]
        def preserved_copy(path):
            # The reviewed reset deliberately preserved external/project/backup copies.
            # They must not block explicit initialization in the now-empty owned roots.
            return reset_completed and not any(root in path.parents for root in owned_roots)
        if any(p not in allowed and not preserved_copy(p) for p in Path(ctx.settings.data_dir).rglob("*.pt")):
            raise ValueError("Existing unregistered weights found; import that checkpoint before initializing a lineage")
        tok_path = root / "tokenizer.json"
        if not checkpoint.exists():
            if tokenizer not in TOKENIZERS:
                raise ValueError(f"Unknown tokenizer {tokenizer!r}; choose one of: {', '.join(TOKENIZERS)}")
            if tokenizer == "library":
                src = _library_tokenizer(ctx)
                if src is None:
                    raise ValueError("No prepared dataset library with a trained tokenizer exists yet; prepare data first "
                                     "or choose the byte-level tokenizer")
                tok = Tokenizer.load(src)
            else:
                # Byte vocabulary is lossless and needs no external training material.
                tok = Tokenizer([])
            tok.save(tok_path)
            cfg = _config(size, tok.vocab_size)
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
        rel = M.finalize(ctx, existing['version'], package, actor_id) if recovering else M._register(
            ctx, package, "MOTH 0.01 (untrained)", {"type": "native-initialization"}, actor_id)
        dev = v2.store_dev_checkpoint(ctx, rel["version"], str(checkpoint), file_sha256(checkpoint))
        import json

        M._set(ctx, rel["version"], info=json.dumps({**rel["info"], "initialization": "random-untrained",
                                                   "genesis": {"size": size, "tokenizer": tokenizer},
                                                   "lineage_totals": {"steps": 0, "tokens": 0, "cycles": 0},
                                                   "dev_checkpoint": dev}))
        return {"created": True, "recovered": recovering, "model": M.release(ctx, rel["version"])}


def activate_initial(ctx: Ctx, actor_id: int, size: str = "seed", tokenizer: str = "byte") -> dict:
    """Explicit owner activation of an evaluated *untrained* baseline, never an upgrade shortcut."""
    current = M.deployed(ctx)
    if current:
        return current
    rel = initialize(ctx, actor_id, size, tokenizer)['model']
    if rel['info'].get('source', {}).get('type') != 'native-initialization':
        raise ValueError('An existing lineage is registered; evaluate and deploy it in Model registry')
    rel = M.evaluate(ctx, rel['version'], actor_id=actor_id)
    if rel['status'] != 'published':
        raise ValueError(rel.get('error') or 'Initial checkpoint failed evaluation')
    from moth_server import serving
    from moth_server.evolution import engine as EN, memory as MEM

    serving.sign_release(ctx, rel['version'])
    rel = M.deploy(ctx, rel['version'], actor_id)
    EN._set_state(ctx, stable_version=rel['version'])
    MEM.event(ctx, 'model.initial_baseline', 'Untrained MOTH 0.01 baseline evaluated and activated by Owner; quality training is not complete', actor=actor_id)
    EN.wake(ctx)
    return rel
