"""Exported model packages and the local model registry.

An exported model is a directory under ``<home>/models/<name>/``:

* ``model.pt`` — fp16/fp32 state dict
* ``config.json`` — :class:`MothConfig`
* ``tokenizer.json`` — the tokenizer it was trained with
* ``manifest.json`` — name, parameter count, sha256, tokenizer fingerprint,
  training provenance (run, step, validation loss, dataset licenses)
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

import torch

from moth.model.config import MothConfig
from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel

FORMAT_VERSION = 1


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_model(checkpoint: Path | str, models_dir: Path | str, name: str, dtype: str = "float16",
                 extra: dict[str, Any] | None = None) -> dict[str, Any]:
    ck = torch.load(checkpoint, map_location="cpu", weights_only=False)
    cfg = MothConfig.from_dict(ck["model_config"])
    cfg.name = name
    tok = Tokenizer.load(ck["tokenizer_path"])
    if tok.fingerprint() != ck["tokenizer_fingerprint"]:
        raise ValueError("tokenizer on disk does not match the checkpoint")
    out = Path(models_dir) / _safe(name)
    if out.exists():
        raise FileExistsError(f"a model named {name!r} already exists")
    tmp = out.with_name(out.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    torch_dtype = {"float16": torch.float16, "bfloat16": torch.bfloat16, "float32": torch.float32}[dtype]
    state = {k: v.to(torch_dtype) if v.is_floating_point() else v for k, v in ck["model"].items()}
    torch.save(state, tmp / "model.pt")
    (tmp / "config.json").write_text(cfg.to_json())
    tok.save(tmp / "tokenizer.json")
    train_cfg = ck.get("train_config", {})
    manifest = {
        "format": FORMAT_VERSION, "name": name, "architecture": "moth-decoder-v1",
        "created": time.time(), "params": cfg.num_params(), "dtype": dtype,
        "context_length": cfg.max_seq_len, "tokenizer_fingerprint": tok.fingerprint(),
        "sha256": sha256_file(tmp / "model.pt"),
        "training": {"run": train_cfg.get("run_name"), "step": ck.get("step"), "val_loss": ck.get("val_loss"),
                     "best_val": ck.get("best_val"), "dataset": train_cfg.get("dataset")},
        **(extra or {}),
    }
    ds_meta = Path(train_cfg.get("dataset", "")) / "meta.json"
    if train_cfg.get("dataset") and ds_meta.exists():
        manifest["training"]["sources"] = json.loads(ds_meta.read_text()).get("sources", [])
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))
    tmp.rename(out)
    return {**manifest, "id": out.name, "path": str(out)}


def _safe(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_." else "-" for c in name).strip("-.")
    if not cleaned:
        raise ValueError("invalid model name")
    return cleaned


def list_models(models_dir: Path | str) -> list[dict[str, Any]]:
    out = []
    root = Path(models_dir)
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        mf = d / "manifest.json"
        if d.is_dir() and mf.exists() and not d.name.endswith(".partial"):
            try:
                out.append({**json.loads(mf.read_text()), "id": d.name, "path": str(d),
                            "size_bytes": (d / "model.pt").stat().st_size})
            except (OSError, json.JSONDecodeError):
                continue
    return out


def load_model(model_dir: Path | str, device: str = "cpu", verify: bool = True) -> tuple[MothModel, Tokenizer, dict]:
    d = Path(model_dir)
    manifest = json.loads((d / "manifest.json").read_text())
    if verify and sha256_file(d / "model.pt") != manifest["sha256"]:
        raise ValueError(f"model file {d / 'model.pt'} is corrupted (checksum mismatch)")
    cfg = MothConfig.from_dict(json.loads((d / "config.json").read_text()))
    tok = Tokenizer.load(d / "tokenizer.json")
    model = MothModel(cfg)
    state = torch.load(d / "model.pt", map_location="cpu", weights_only=True)
    model.load_state_dict({k: v.float() for k, v in state.items()})
    if device.startswith("cuda"):
        model = model.to(device=device, dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
    else:
        model = model.to(device)
    model.eval()
    return model, tok, manifest


def delete_model(models_dir: Path | str, model_id: str) -> None:
    d = Path(models_dir) / _safe(model_id)
    if not (d / "manifest.json").exists():
        raise FileNotFoundError(model_id)
    shutil.rmtree(d)
