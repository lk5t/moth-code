"""Checkpoint save/load with atomic writes and rotation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import torch


def atomic_torch_save(obj: Any, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    torch.save(obj, tmp)
    os.replace(tmp, path)


def save_checkpoint(run_dir: Path, step: int, payload: dict[str, Any], keep: int = 3) -> Path:
    ckpt_dir = Path(run_dir) / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = ckpt_dir / f"step_{step:08d}.pt"
    atomic_torch_save(payload, path)
    latest = ckpt_dir / "latest.json"
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"step": step, "file": path.name}))
    os.replace(tmp, latest)
    # rotation (never delete best.pt)
    existing = sorted(ckpt_dir.glob("step_*.pt"))
    for old in existing[:-keep]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def latest_checkpoint(run_dir: Path) -> Path | None:
    ckpt_dir = Path(run_dir) / "checkpoints"
    pointer = ckpt_dir / "latest.json"
    if pointer.exists():
        p = ckpt_dir / json.loads(pointer.read_text())["file"]
        if p.exists():
            return p
    candidates = sorted(ckpt_dir.glob("step_*.pt")) if ckpt_dir.exists() else []
    return candidates[-1] if candidates else None


def load_checkpoint(path: Path, map_location: str | torch.device = "cpu") -> dict[str, Any]:
    return torch.load(path, map_location=map_location, weights_only=False)
