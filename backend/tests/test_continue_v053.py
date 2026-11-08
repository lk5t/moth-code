"""Evolution 2.0 training runs: curriculum mixtures, continuing from the lineage's development checkpoint
(weights + optimizer), and growing the model before training — all real training, on tiny data."""

import json

import torch

from moth.model.config import preset
from moth.model.registry import export_model
from moth.model.tokenizer import train_bpe
from moth.model.transformer import MothModel
from moth.training.continue_run import run
from moth.training.data import prepare_dataset

TEXT = {"language": "The cat sat on the mat. The dog ran to the park and played with a ball. " * 60,
        "code": "def add(a, b):\n    return a + b\n\ndef mul(a, b):\n    return a * b\n" * 60}


def _mixture(tmp_path):
    tok = train_bpe(list(TEXT.values()), 400)
    tok.save(tmp_path / "tok.json")
    mix = {"format": 1, "tokenizer_fingerprint": tok.fingerprint(), "tokenizer_path": str(tmp_path / "tok.json"),
           "build_sha256": "x", "domains": {}}
    for d, t in TEXT.items():
        (tmp_path / "src").mkdir(exist_ok=True)
        (tmp_path / "src" / f"{d}.jsonl").write_text("\n".join(json.dumps({"text": t[i:i + 400]})
                                                               for i in range(0, len(t), 400)))
        meta = prepare_dataset([{"spec": f"jsonl:{tmp_path / 'src' / f'{d}.jsonl'}", "license": "MIT"}], tok,
                               tmp_path / "tok.json", tmp_path / "mix" / d, val_fraction=0.1)
        mix["domains"][d] = {"dir": d, "tokens": meta["tokens"]}
    (tmp_path / "mix" / "mixture.json").write_text(json.dumps(mix))
    torch.manual_seed(0)
    cfg = preset("moth-tiny", vocab_size=448)
    torch.save({"model": MothModel(cfg).state_dict(), "model_config": cfg.to_dict(),
                "tokenizer_path": str(tmp_path / "tok.json"), "tokenizer_fingerprint": tok.fingerprint(), "step": 1},
               tmp_path / "ck.pt")
    pkg = export_model(tmp_path / "ck.pt", tmp_path / "models", "base", dtype="float32",
                       extra={"family": "MOTH", "lineage_id": "moth-t"})
    return tmp_path / "mix", pkg["path"]


def _spec(tmp_path, name, mix, base, **kw):
    return {"name": name, "base_package": base, "dataset": str(mix), "run_dir": str(tmp_path / name), "steps": 12,
            "lr": 3e-3, "batch_size": 4, "seq_len": 32, "eval_interval": 6, "eval_iters": 2, "checkpoint_interval": 6,
            "device": "cpu", "mixture": {"language": 0.7, "code": 0.3}, **kw}


def test_mixture_dev_checkpoint_and_growth(tmp_path):
    mix, base = _mixture(tmp_path)
    first = run(_spec(tmp_path, "c1", mix, base))
    assert first["reason"] == "completed" and first["dev_checkpoint"] and first["package"]
    ck = torch.load(first["dev_checkpoint"], weights_only=False)
    assert ck["optimizer"]["state"] and ck["lineage"]["total_steps"] == 12  # optimizer state kept for the lineage
    # the next cycle continues from that development checkpoint (weights *and* AdamW moments)
    second = run(_spec(tmp_path, "c2", mix, first["package"], init_checkpoint=first["dev_checkpoint"],
                       init_checkpoint_sha256=first["dev_checkpoint_sha256"]))
    assert second["reason"] == "completed"
    m2 = json.loads((tmp_path / "c2" / "events.jsonl").read_text().splitlines()[0])
    assert m2["kind"] == "start" and m2["resumed_from"] is None
    # growth: the same lineage gets more layers and keeps training
    grown = run(_spec(tmp_path, "g1", mix, first["package"], init_checkpoint=first["dev_checkpoint"],
                      grow={"add_layers": 1, "ffn_hidden": 256 + 64}))
    assert grown["reason"] == "completed" and grown["params"] > first["params"]
    man = json.loads((tmp_path / "g1" / "export").glob("*/manifest.json").__next__().read_text())
    assert man["lineage"]["method"] == "expansion" and man["lineage_id"] == "moth-t"
    # Corruption must not silently discard optimizer/RNG progress and fall back to package weights.
    import pytest
    with pytest.raises(ValueError, match='missing or corrupted'):
        run(_spec(tmp_path, "c3", mix, first["package"], init_checkpoint=first["dev_checkpoint"],
                  init_checkpoint_sha256="0" * 64))


def test_continued_training_without_unix_priority_api(tmp_path, monkeypatch):
    """The real CPU optimizer must run when os.nice is absent (native Windows)."""
    import os
    monkeypatch.delattr(os, 'nice', raising=False)
    mix, base = _mixture(tmp_path)
    result = run(_spec(tmp_path, 'windows-priority', mix, base, nice=10, threads=2,
                       steps=2, checkpoint_interval=1, eval_interval=1))
    assert result['reason'] == 'completed' and result['step'] == 2 and result['tokens'] > 0
    checkpoint = torch.load(result['dev_checkpoint'], weights_only=False)
    assert checkpoint['optimizer']['state'] and checkpoint['step'] == 2
