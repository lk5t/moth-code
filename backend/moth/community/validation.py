"""Validation of contributed weight deltas (run by the coordinator)."""

from __future__ import annotations

import hashlib
import io
import math
from dataclasses import dataclass, field

import torch

MAX_RELATIVE_NORM = 0.5  # ‖Δ‖ / ‖W‖ per tensor


@dataclass
class ValidationReport:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    stats: dict[str, float] = field(default_factory=dict)


def tensor_bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def serialize_state(state: dict[str, torch.Tensor]) -> bytes:
    buf = io.BytesIO()
    torch.save({k: v.detach().cpu() for k, v in state.items()}, buf)
    return buf.getvalue()


def deserialize_state(data: bytes) -> dict[str, torch.Tensor]:
    return torch.load(io.BytesIO(data), map_location="cpu", weights_only=True)


def validate_delta(base: dict[str, torch.Tensor], delta: dict[str, torch.Tensor],
                   max_relative_norm: float = MAX_RELATIVE_NORM) -> ValidationReport:
    reasons: list[str] = []
    if set(base) != set(delta):
        missing, extra = set(base) - set(delta), set(delta) - set(base)
        reasons.append(f"tensor keys differ (missing {sorted(missing)[:3]}, unexpected {sorted(extra)[:3]})")
        return ValidationReport(False, reasons)
    worst = 0.0
    total_sq = 0.0
    for k, w in base.items():
        d = delta[k]
        if d.shape != w.shape:
            reasons.append(f"{k}: shape {tuple(d.shape)} != {tuple(w.shape)}")
            continue
        if not d.is_floating_point() or not torch.isfinite(d).all():
            reasons.append(f"{k}: contains non-finite values")
            continue
        wn = w.float().norm().item()
        dn = d.float().norm().item()
        total_sq += dn * dn
        rel = dn / (wn + 1e-8)
        worst = max(worst, rel)
        if rel > max_relative_norm:
            reasons.append(f"{k}: update too large (relative norm {rel:.3f} > {max_relative_norm})")
    stats = {"max_relative_norm": worst, "delta_norm": math.sqrt(total_sq)}
    if stats["delta_norm"] == 0.0:
        reasons.append("empty update (all zeros)")
    return ValidationReport(not reasons, reasons, stats)
