"""Filesystem locations used by the backend.

The data directory defaults to ``%APPDATA%/MOTH Code`` on Windows and
``~/.moth`` elsewhere. ``MOTH_HOME`` overrides it (used by tests and portable
installs).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_home() -> Path:
    env = os.environ.get("MOTH_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "MOTH Code"
    return Path.home() / ".moth"


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def db(self) -> Path:
        return self.home / "moth.db"

    @property
    def models(self) -> Path:
        return self.home / "models"

    @property
    def runs(self) -> Path:
        return self.home / "runs"

    @property
    def datasets(self) -> Path:
        return self.home / "datasets"

    @property
    def tokenizers(self) -> Path:
        return self.home / "tokenizers"

    @property
    def policy(self) -> Path:
        return self.home / "policy.json"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def community(self) -> Path:
        return self.home / "community"

    def ensure(self) -> "Paths":
        for p in (self.home, self.models, self.runs, self.datasets, self.tokenizers, self.logs, self.community):
            p.mkdir(parents=True, exist_ok=True)
        return self


def get_paths(home: Path | str | None = None) -> Paths:
    return Paths(Path(home).resolve() if home else default_home()).ensure()
