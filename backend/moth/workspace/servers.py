"""Servers (1.0.18): saved SSH profiles MOTH's agent can run commands on, with the user's approval.

Profiles hold only a name, host, port, user and an optional key file path. No passwords are stored:
connections use the system's ``ssh`` with the user's own keys or SSH agent (``BatchMode``, so it never
waits for a password prompt). New host keys are accepted once and pinned (``accept-new``); a changed key
is refused by ssh.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

_lock = threading.Lock()
_home: Path | None = None
_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_HOST = re.compile(r"^[A-Za-z0-9_.:-]{1,253}$")
_USER = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class ServerError(RuntimeError):
    pass


def configure(home: Path) -> None:
    global _home
    _home = Path(home)


def _file() -> Path:
    if _home is None:
        raise RuntimeError("servers are not configured")
    return _home / "servers.json"


def all_() -> list[dict[str, Any]]:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save(rows: list[dict[str, Any]]) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    tmp.replace(f)


def add(name: str, host: str, user: str, port: int = 22, key_path: str | None = None) -> dict[str, Any]:
    if not _NAME.match(name or ""):
        raise ServerError("Name: letters, digits, dot, dash or underscore (up to 40).")
    if not _HOST.match(host or "") or host.startswith("-"):
        raise ServerError("Not a valid host name or IP address.")
    if not _USER.match(user or "") or user.startswith("-"):
        raise ServerError("Not a valid user name.")
    if not 1 <= int(port) <= 65535:
        raise ServerError("Port must be 1-65535.")
    if key_path and not Path(key_path).expanduser().is_file():
        raise ServerError(f"Key file not found: {key_path}")
    row = {"name": name, "host": host, "user": user, "port": int(port),
           "key_path": str(Path(key_path).expanduser()) if key_path else None, "added_at": time.time()}
    with _lock:
        rows = [r for r in all_() if r["name"] != name] + [row]
        _save(rows)
    return row


def remove(name: str) -> None:
    with _lock:
        _save([r for r in all_() if r["name"] != name])


def get(name: str) -> dict[str, Any]:
    row = next((r for r in all_() if r["name"] == name), None)
    if row is None:
        raise ServerError(f"No saved server named {name!r}. Add it in Settings → Servers & engagements.")
    return row


def ssh_argv(row: dict[str, Any], command: str) -> list[str]:
    exe = shutil.which("ssh")
    if not exe:
        raise ServerError("ssh is not installed (Windows: Settings → Apps → Optional features → OpenSSH Client).")
    argv = [exe, "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=15",
            "-p", str(row["port"])]
    if row.get("key_path"):
        argv += ["-i", row["key_path"]]
    return argv + [f"{row['user']}@{row['host']}", "--", command]


def run(row: dict[str, Any], command: str, timeout: float = 600.0,
        on_output: Callable[[str], None] | None = None, cancel: threading.Event | None = None) -> dict[str, Any]:
    """Run ``command`` on the server; returns exit code, combined output and duration."""
    start = time.time()
    kwargs: dict[str, Any] = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(ssh_argv(row, command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace", **kwargs)
    out: list[str] = []
    timed_out = cancelled = False

    def pump() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            out.append(line)
            if on_output:
                on_output(line)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    while proc.poll() is None:
        if cancel is not None and cancel.is_set():
            cancelled = True
            proc.kill()
            break
        if time.time() - start > timeout:
            timed_out = True
            proc.kill()
            break
        time.sleep(0.1)
    proc.wait()
    t.join(timeout=2)
    return {"exit_code": proc.returncode, "output": "".join(out)[-200_000:], "duration": time.time() - start,
            "timed_out": timed_out, "cancelled": cancelled}
