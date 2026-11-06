"""Worker configuration and state directory (credential file is created with 0600 permissions)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


def default_dir() -> Path:
    env = os.environ.get("MOTH_WORKER_HOME")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "MOTH" / "worker"
    if os.geteuid() == 0:
        return Path("/var/lib/moth-worker")
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "moth-worker"


@dataclass
class WorkerConfig:
    server: str
    worker_id: int
    token: str
    name: str = ""
    allow_cpu: bool = False
    limits: dict = field(default_factory=dict)

    @classmethod
    def load(cls, home: Path) -> "WorkerConfig":
        data = json.loads((home / "config.json").read_text())
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def save(self, home: Path) -> None:
        home.mkdir(parents=True, exist_ok=True)
        path = home / "config.json"
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(self), f, indent=2)
        os.replace(tmp, path)
