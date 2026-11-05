#!/usr/bin/env python3
"""Create a small licensed dataset + base MOTH model for a development training coordinator.

    python scripts/dev-bootstrap-training.py OUT_DIR
    moth-server training-init --model OUT_DIR/models/moth-dev-base --dataset OUT_DIR/dataset

Uses the Python standard library source (PSF-2.0) when available, else synthetic code.
For production, initialise from a real exported MOTH checkpoint and a properly licensed dataset.
"""

import sys
from pathlib import Path

import torch

from moth.model.config import preset
from moth.model.registry import export_model
from moth.model.tokenizer import train_bpe
from moth.model.transformer import MothModel
from moth.training.data import prepare_dataset
from moth.training.sources import SourceSpec, iter_source

out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=True)
src = SourceSpec("stdlib", license="PSF-2.0", max_bytes=400_000)
texts = [d.text for d in iter_source(src)]
tok = train_bpe(texts, vocab_size=512)
tok.save(out / "tokenizer.json")
prepare_dataset([src], tok, out / "tokenizer.json", out / "dataset", val_fraction=0.05)
torch.manual_seed(0)
cfg = preset("moth-tiny", vocab_size=512)
torch.save({"model": MothModel(cfg).state_dict(), "model_config": cfg.to_dict(),
            "tokenizer_path": str(out / "tokenizer.json"), "tokenizer_fingerprint": tok.fingerprint(), "step": 0},
           out / "base.pt")
info = export_model(out / "base.pt", out / "models", "moth-dev-base", dtype="float32")
print(info["path"])
