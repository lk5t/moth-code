"""Federated averaging of validated deltas and checkpoint versioning."""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch

from moth.model.registry import sha256_file


def federated_average(deltas: list[tuple[dict[str, torch.Tensor], float]]) -> dict[str, torch.Tensor]:
    """Weighted mean of deltas (weights = tokens trained)."""
    if not deltas:
        raise ValueError("no deltas to aggregate")
    total = sum(w for _, w in deltas)
    if total <= 0:
        raise ValueError("aggregation weights must be positive")
    keys = deltas[0][0].keys()
    return {k: sum(d[k].float() * (w / total) for d, w in deltas) for k in keys}


def apply_delta(base: dict[str, torch.Tensor], delta: dict[str, torch.Tensor], scale: float = 1.0) -> dict[str, torch.Tensor]:
    return {k: (v.float() + scale * delta[k].float()).to(v.dtype) for k, v in base.items()}


def write_version(versions_dir: Path, version: int, state: dict[str, torch.Tensor], parent_sha: str | None,
                  meta: dict) -> dict:
    """Persist a new community checkpoint version with lineage metadata."""
    d = Path(versions_dir) / f"v{version:05d}"
    d.mkdir(parents=True, exist_ok=False)
    torch.save(state, d / "model.pt")
    info = {"version": version, "parent_sha256": parent_sha, "sha256": sha256_file(d / "model.pt"),
            "created": time.time(), **meta}
    (d / "version.json").write_text(json.dumps(info, indent=2))
    return info
