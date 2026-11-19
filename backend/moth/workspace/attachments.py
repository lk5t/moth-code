"""2.0: files and folders dropped into chat.

Dropping something is the user choosing to share it, so any path may be read, but only text files, never files
that look like credentials (keys, .env, cloud credentials), and within size limits so a dropped folder cannot
flood the prompt.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from moth.security.permissions import is_secret_path

MAX_FILES = 30
MAX_FILE_BYTES = 120_000
MAX_TOTAL_BYTES = 300_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "target", ".next", ".cache",
             ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".tox", "coverage"}


def _is_text(raw: bytes) -> bool:
    if b"\x00" in raw[:8192]:
        return False
    try:
        raw[:8192].decode("utf-8")
        return True
    except UnicodeDecodeError as e:
        return e.start > 8180  # cut in the middle of a character at the boundary


def _walk(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            yield Path(dirpath) / f


def read(paths: list[str]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    total = 0

    def add(p: Path, shown: str) -> bool:
        nonlocal total
        if len(files) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
            skipped.append({"path": shown, "reason": "limit reached"})
            return False
        if is_secret_path(p):
            skipped.append({"path": shown, "reason": "looks like a secret (key, .env or credentials)"})
            return True
        try:
            size = p.stat().st_size
            with open(p, "rb") as fh:
                raw = fh.read(min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total) + 1)
        except OSError as e:
            skipped.append({"path": shown, "reason": f"cannot be read ({e.strerror or e})"})
            return True
        if not _is_text(raw):
            skipped.append({"path": shown, "reason": "not a text file"})
            return True
        limit = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
        truncated = len(raw) > limit
        text = raw[:limit].decode("utf-8", errors="ignore")
        total += len(text.encode("utf-8"))
        files.append({"path": shown, "name": p.name, "size": size, "content": text, "truncated": truncated})
        return True

    for raw_path in paths[:50]:
        p = Path(raw_path).expanduser()
        if p.is_dir():
            for f in _walk(p):
                if not add(f, str(Path(p.name) / f.relative_to(p))):
                    break
        elif p.is_file():
            add(p, p.name)
        else:
            skipped.append({"path": raw_path, "reason": "not found"})
    return {"files": files, "skipped": skipped, "total_bytes": total}
