"""Wire types for the community training protocol."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

PROTOCOL = "moth-community/1"


@dataclass
class TrainSpec:
    steps: int = 50
    lr: float = 3e-4
    batch_size: int = 8
    seq_len: int = 256
    weight_decay: float = 0.0


@dataclass
class JobSpec:
    job_id: str
    round: int
    model_version: int
    base_sha256: str
    model_config: dict[str, Any]
    tokenizer_fingerprint: str
    shard_id: str
    shard_sha256: str
    shard_license: str
    train: TrainSpec = field(default_factory=TrainSpec)
    protocol: str = PROTOCOL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "JobSpec":
        d = dict(d)
        d["train"] = TrainSpec(**d.get("train", {}))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ContributionMeta:
    job_id: str
    round: int
    client_id: str
    base_sha256: str
    delta_sha256: str
    tokens: int
    steps: int
    loss_before: float
    loss_after: float
    protocol: str = PROTOCOL

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
