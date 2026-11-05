"""Git integration via the ``git`` CLI (change tracking, diff, commit)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitError(RuntimeError):
    pass


def git_available() -> bool:
    return shutil.which("git") is not None


@dataclass
class Git:
    root: Path

    def _run(self, *args: str, check: bool = True, input: str | None = None) -> str:
        if not git_available():
            raise GitError("git is not installed or not on PATH")
        kwargs = {}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(
            ["git", *args], cwd=str(self.root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", input=input, timeout=120, **kwargs,
        )
        if check and proc.returncode != 0:
            raise GitError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
        return proc.stdout

    def is_repo(self) -> bool:
        try:
            return self._run("rev-parse", "--is-inside-work-tree", check=False).strip() == "true"
        except GitError:
            return False

    def init(self) -> str:
        return self._run("init")

    def branch(self) -> str | None:
        out = self._run("rev-parse", "--abbrev-ref", "HEAD", check=False).strip()
        return out or None

    def status(self) -> list[dict]:
        """Parse ``git status --porcelain=v1 -z``."""
        out = self._run("status", "--porcelain=v1", "-z", "--untracked-files=all")
        entries, parts, i = [], out.split("\0"), 0
        while i < len(parts):
            item = parts[i]
            i += 1
            if len(item) < 4:
                continue
            x, y, path = item[0], item[1], item[3:]
            entry = {"path": path, "index": x, "worktree": y, "status": _describe(x, y)}
            if x in "RC":  # rename/copy: next field is the source path
                entry["from"] = parts[i] if i < len(parts) else None
                i += 1
            entries.append(entry)
        return entries

    def diff(self, path: str | None = None, staged: bool = False) -> str:
        args = ["diff", "--no-color"]
        if staged:
            args.append("--cached")
        if path:
            args += ["--", path]
        return self._run(*args)

    def log(self, limit: int = 30) -> list[dict]:
        sep = "\x1f"
        out = self._run("log", f"-n{limit}", f"--pretty=format:%H{sep}%an{sep}%at{sep}%s", check=False)
        logs = []
        for line in out.splitlines():
            parts = line.split(sep)
            if len(parts) == 4:
                logs.append({"hash": parts[0], "author": parts[1], "time": int(parts[2]), "subject": parts[3]})
        return logs

    def add(self, paths: list[str] | None = None) -> None:
        self._run("add", "--", *(paths or ["."]))

    def commit(self, message: str, author: str | None = None) -> str:
        args = ["commit", "-m", message]
        if author:
            args += ["--author", author]
        self._run(*args)
        return self._run("rev-parse", "HEAD").strip()

    def show_file(self, path: str, rev: str = "HEAD") -> str:
        return self._run("show", f"{rev}:{path}")


def _describe(x: str, y: str) -> str:
    if x == "?" and y == "?":
        return "untracked"
    code = x if x != " " else y
    return {"M": "modified", "A": "added", "D": "deleted", "R": "renamed", "C": "copied", "U": "conflict"}.get(code, "changed")
