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
    """Exclusive lock on a run directory (stale locks of dead processes are taken over)."""

    def __init__(self, run_dir: Path, owner: str = ""):
        self.path = Path(run_dir) / "run.lock"
        self.owner = owner or f"pid {os.getpid()}"

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as f:
                    json.dump({"pid": os.getpid(), "owner": self.owner, "since": time.time()}, f)
                return self
            except FileExistsError:
                try:
                    info = json.loads(self.path.read_text())
                    pid = int(info.get("pid", 0))
                except (OSError, ValueError):
                    info, pid = {}, 0
                if pid and pid != os.getpid() and _pid_alive(pid):
                    raise CheckpointError(f"run is already being trained by {info.get('owner') or pid}")
                self.path.unlink(missing_ok=True)
        raise CheckpointError("could not lock the run directory")

    def __exit__(self, *exc) -> None:
        self.path.unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def save_checkpoint(run_dir: Path, step: int, payload: dict[str, Any], keep: int = 3) -> Path:
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
    for old in existing[:-keep]:
        try:
            old.unlink()
            old.with_name(old.name + ".sha256").unlink(missing_ok=True)
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
