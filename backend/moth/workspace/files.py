"""Boundary-checked file operations inside an authorised workspace."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from moth.security.permissions import Workspace

MAX_READ_BYTES = 2 * 1024 * 1024


class FileTooLarge(ValueError):
    pass


def is_binary(data: bytes) -> bool:
    return b"\x00" in data[:8192]


@dataclass
class FileOps:
    workspace: Workspace

    def read(self, rel: str, max_bytes: int = MAX_READ_BYTES) -> str:
        path = self.workspace.resolve(rel)
        size = path.stat().st_size
        if size > max_bytes:
            raise FileTooLarge(f"{rel} is {size} bytes (limit {max_bytes})")
        data = path.read_bytes()
        if is_binary(data):
            raise ValueError(f"{rel} appears to be a binary file")
        return data.decode("utf-8", errors="replace")

    def write(self, rel: str, content: str) -> dict:
        path = self.workspace.resolve(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        tmp = path.with_name(path.name + ".moth-tmp")
        tmp.write_text(content, encoding="utf-8", newline="")
        os.replace(tmp, path)  # atomic on the same volume
        return {"path": self.workspace.relative(path), "created": not existed, "bytes": len(content.encode())}

    def edit(self, rel: str, old: str, new: str, count: int = 1) -> dict:
        """Replace exactly ``count`` occurrences of ``old`` (fails if ambiguous)."""
        text = self.read(rel)
        found = text.count(old)
        if found == 0:
            raise ValueError(f"text to replace was not found in {rel}")
        if count and found != count:
            raise ValueError(f"expected {count} occurrence(s) in {rel}, found {found}")
        self.write(rel, text.replace(old, new))
        return {"path": rel, "replacements": found}

    def delete(self, rel: str) -> dict:
        path = self.workspace.resolve(rel)
        if path == self.workspace.root:
            raise PermissionError("refusing to delete the workspace root")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return {"path": rel, "deleted": True}

    def rename(self, src: str, dst: str) -> dict:
        a, b = self.workspace.resolve(src), self.workspace.resolve(dst)
        b.parent.mkdir(parents=True, exist_ok=True)
        os.replace(a, b)
        return {"from": src, "to": dst}

    def mkdir(self, rel: str) -> dict:
        path = self.workspace.resolve(rel)
        path.mkdir(parents=True, exist_ok=True)
        return {"path": rel}

    def list_dir(self, rel: str = ".") -> list[dict]:
        path = self.workspace.resolve(rel)
        out = []
        for entry in sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            try:
                st = entry.stat()
            except OSError:
                continue
            out.append({
                "name": entry.name,
                "path": self.workspace.relative(entry) if self.workspace.contains(entry) else entry.name,
                "dir": entry.is_dir(),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        return out
