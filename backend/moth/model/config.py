"""Model hyper-parameters and named presets.

Presets are designed to scale: the same code path builds the 50M model and
larger future models; only the numbers change.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass
class MothConfig:
    name: str = "moth-50m"
    vocab_size: int = 16384
    d_model: int = 512
    n_layers: int = 12
    n_heads: int = 8
    n_kv_heads: int = 8  # < n_heads enables grouped-query attention for larger models
    ffn_hidden: int = 1536
    max_seq_len: int = 2048
    rope_theta: float = 10000.0
    norm_eps: float = 1e-5
    dropout: float = 0.0
    tie_embeddings: bool = True

    def __post_init__(self) -> None:
        if self.d_model % self.n_heads:
            raise ValueError("d_model must be divisible by n_heads")
        if self.n_heads % self.n_kv_heads:
            raise ValueError("n_heads must be divisible by n_kv_heads")
        if (self.d_model // self.n_heads) % 2:
            raise ValueError("head dimension must be even for rotary embeddings")

    @property
    def head_dim(self) -> int:
        return self.d_model // self.n_heads

    def num_params(self) -> int:
        """Analytic parameter count (matches ``sum(p.numel())`` of the model)."""
        d, h = self.d_model, self.head_dim
        attn = d * (self.n_heads * h) + 2 * d * (self.n_kv_heads * h) + (self.n_heads * h) * d
        mlp = 3 * d * self.ffn_hidden
        per_layer = attn + mlp + 2 * d
        emb = self.vocab_size * d
        head = 0 if self.tie_embeddings else self.vocab_size * d
        return self.n_layers * per_layer + emb + head + d

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MothConfig":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in known})

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def compatibility_key(self) -> str:
        """Fields that must match for checkpoints/contributions to be interchangeable."""
        d = self.to_dict()
        d.pop("name", None)
        d.pop("dropout", None)
        return json.dumps(d, sort_keys=True)


PRESETS: dict[str, MothConfig] = {
    # Unit tests and quick smoke runs (~0.14M params).
    "moth-tiny": MothConfig(name="moth-tiny", vocab_size=512, d_model=64, n_layers=2, n_heads=4, n_kv_heads=4,
                            ffn_hidden=192, max_seq_len=256),
    # CPU-friendly experiments (~7.2M params, 8K vocabulary).
    "moth-small": MothConfig(name="moth-small", vocab_size=8192, d_model=256, n_layers=6, n_heads=4, n_kv_heads=4,
                             ffn_hidden=768, max_seq_len=1024),
    # MOTH Model v0.1 (~49M params).
    "moth-50m": MothConfig(),
    # Future scaling targets (same architecture; grouped-query attention, longer context).
    "moth-150m": MothConfig(name="moth-150m", vocab_size=32768, d_model=768, n_layers=18, n_heads=12, n_kv_heads=4,
                            ffn_hidden=2304, max_seq_len=4096),
    "moth-400m": MothConfig(name="moth-400m", vocab_size=32768, d_model=1024, n_layers=30, n_heads=16, n_kv_heads=4,
                            ffn_hidden=3072, max_seq_len=4096),
}


def preset(name: str, **overrides: Any) -> MothConfig:
    if name not in PRESETS:
        raise KeyError(f"unknown preset {name!r}; available: {', '.join(PRESETS)}")
    return MothConfig.from_dict({**PRESETS[name].to_dict(), **overrides})
