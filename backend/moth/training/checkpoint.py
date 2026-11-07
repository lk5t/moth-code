"""Checkpoint save/load: atomic writes, integrity hashes, verified resume, rotation and run locks.

Every ``step_*.pt`` has a ``.sha256`` sidecar written after the file is complete and fsynced. Resuming
verifies the hash and falls back to the newest checkpoint that verifies, so a crash or a corrupted
disk block never silently resumes from damaged weights. ``RunLock`` makes one run directory writable
by one trainer at a time: concurrent workers can never overwrite each other's progress.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

import torch


class CheckpointError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def atomic_torch_save(obj: Any, path: Path) -> str:
    """Write ``obj`` atomically and durably; returns the file's SHA-256 (also stored as a sidecar)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        torch.save(obj, f)
        f.flush()
        os.fsync(f.fileno())
    digest = file_sha256(tmp)
    os.replace(tmp, path)
    side = path.with_name(path.name + ".sha256")
    side.with_suffix(".tmp").write_text(digest)
    os.replace(side.with_suffix(".tmp"), side)
    return digest


def verify(path: Path) -> bool:
    side = Path(path).with_name(Path(path).name + ".sha256")
    if not side.exists():
        return True  # checkpoints written before 0.5.2 have no sidecar
    return side.read_text().strip() == file_sha256(Path(path))


class RunLock:
    """Exclusive lock on a run directory, held by the operating system for the trainer's lifetime.

    Uses ``flock`` (Linux, macOS) or ``msvcrt.locking`` (Windows): the lock disappears the moment the
    process ends — also when it is killed — so a crashed trainer never blocks recovery, and two live
    trainers can never write the same run."""

    def __init__(self, run_dir: Path, owner: str = ""):
        self.path = Path(run_dir) / "run.lock"
        self.owner = owner or f"pid {os.getpid()}"
        self._f = None

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                f.seek(1 if os.name == "nt" else 0)  # Windows: byte 0 is locked (mandatory lock)
                info = json.loads(f.read() or "{}")
            except (OSError, ValueError):
                info = {}
            f.close()
            raise CheckpointError(f"run is already being trained by {info.get('owner') or 'another process'}")
        if os.name == "nt":  # the locked byte is 0; owner details live after it
            f.seek(1)
            f.truncate()
            f.write(json.dumps({"pid": os.getpid(), "owner": self.owner, "since": time.time()}))
        else:
            f.seek(0)
            f.truncate()
            f.write(json.dumps({"pid": os.getpid(), "owner": self.owner, "since": time.time()}))
        f.flush()
        self._f = f
        return self

    def __exit__(self, *exc) -> None:
        if self._f is not None:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._f.seek(0)
                    msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            self._f.close()
            self._f = None


def save_checkpoint(run_dir: Path, step: int, payload: dict[str, Any], keep: int = 3, keep_every: int = 0) -> Path:
    """Write a verified checkpoint. Retention: the newest ``keep`` plus every ``keep_every``-th step
    (milestones, never rotated away) and ``best.pt``."""
    ckpt_dir = Path(run_dir) / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    path = ckpt_dir / f"step_{step:08d}.pt"
    digest = atomic_torch_save(payload, path)
    latest = ckpt_dir / "latest.json"
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"step": step, "file": path.name, "sha256": digest}))
    os.replace(tmp, latest)
    # rotation (never delete best.pt)
    existing = sorted(ckpt_dir.glob("step_*.pt"))

    def milestone(p: Path) -> bool:
        try:
            return keep_every > 0 and int(p.stem.split("_")[1]) % keep_every == 0
        except ValueError:
            return False

    for old in [p for p in existing[:-keep] if not milestone(p)]:
        try:
            old.unlink()
            old.with_name(old.name + ".sha256").unlink(missing_ok=True)
        except OSError:
            pass
    return path


def latest_checkpoint(run_dir: Path) -> Path | None:
    ckpt_dir = Path(run_dir) / "checkpoints"
    candidates = sorted(ckpt_dir.glob("step_*.pt")) if ckpt_dir.exists() else []
    pointer = ckpt_dir / "latest.json"
    if pointer.exists():
        try:
            name = json.loads(pointer.read_text())["file"]
            p = ckpt_dir / name
            if p.name == name and p.name.startswith("step_") and p.suffix == ".pt" and p.is_file():
                return max([p, *candidates])
        except (OSError, ValueError, KeyError, TypeError):
            pass  # a damaged pointer must not prevent scanning intact checkpoints
    return candidates[-1] if candidates else None


def load_checkpoint(path: Path, map_location: str | torch.device = "cpu") -> dict[str, Any]:
    return torch.load(path, map_location=map_location, weights_only=False)


def load_latest_verified(run_dir: Path, map_location="cpu", on_event: Callable[..., None] | None = None
                         ) -> tuple[Path | None, dict[str, Any] | None]:
    """The newest checkpoint whose integrity hash verifies and that loads; damaged ones are quarantined."""
    ckpt_dir = Path(run_dir) / "checkpoints"
    if not ckpt_dir.exists():
        return None, None
    first = latest_checkpoint(run_dir)
    candidates = sorted(ckpt_dir.glob("step_*.pt"), reverse=True)
    if first is not None and first in candidates:
        candidates.remove(first)
        candidates.insert(0, first)
    for p in candidates:
        ok = verify(p)
        ck = None
        if ok:
            try:
                ck = load_checkpoint(p, map_location)
            except Exception:
                ok = False
        if ok and ck is not None:
            return p, ck
        bad = p.with_name(p.name + ".corrupt")
        os.replace(p, bad)
        if on_event:
            on_event("warning", message=f"checkpoint {p.name} failed its integrity check; moved to {bad.name}")
    return None, None
