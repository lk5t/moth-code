#!/usr/bin/env python3
"""Helpers for the Windows desktop auto-update test (.github/workflows/desktop-update-test.yml).

    python scripts/desktop-update-harness.py bump 0.3.99
    python scripts/desktop-update-harness.py register --server http://127.0.0.1:8900 --data-dir D --agent-token F --dir R
    python scripts/desktop-update-harness.py wait-report --data-dir D --version 0.3.99 [--timeout 300]

``register`` does exactly what the MOTH Cloud update agent does with a verified desktop release: it
registers the signed manifest and hands the installer to the server (which re-checks the signature
and SHA-256). ``wait-report`` waits until the updated app has reported a successful update to the
server — proof that the new version actually started after installing itself.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import shutil
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def bump(version: str) -> None:
    for path, pattern, repl in (
        ("app/src-tauri/tauri.conf.json", r'"version": "[^"]+"', f'"version": "{version}"'),
        ("app/package.json", r'"version": "[^"]+"', f'"version": "{version}"'),
        ("app/src-tauri/Cargo.toml", r'^version = "[^"]+"', f'version = "{version}"'),
        ("backend/moth/__init__.py", r'__version__ = "[^"]+"', f'__version__ = "{version}"'),
    ):
        p = ROOT / path
        s = p.read_text()
        s2 = re.sub(pattern, repl, s, count=1, flags=re.M)
        assert s2 != s or version in s, f"could not set the version in {path}"
        p.write_text(s2)
    print(f"version set to {version}")


def post(server: str, path: str, body: dict, token: str) -> dict:
    req = urllib.request.Request(server.rstrip("/") + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Moth-Agent-Token": token})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"{}")


def register(server: str, data_dir: Path, token_file: Path, rel_dir: Path) -> None:
    token = token_file.read_text().strip()
    mf = next(rel_dir.glob("moth-release-desktop-*.json"))
    raw = mf.read_bytes()
    sig = mf.with_name(mf.name + ".sig").read_text().strip()
    m = json.loads(raw)
    print("register:", post(server, "/v1/agent/releases", {"manifest": base64.b64encode(raw).decode(), "signature": sig},
                            token))
    for entry in m["components"]["desktop"].values():
        incoming = data_dir / "storage" / "software" / "incoming" / entry["file"]
        incoming.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(rel_dir / entry["file"], incoming)
        print("file:", post(server, "/v1/agent/files", {"component": "desktop", "version": m["version"],
                                                        "path": str(incoming)}, token))


def wait_report(data_dir: Path, version: str, timeout: float) -> int:
    db = data_dir / "moth-server.db"
    end = time.time() + timeout
    while time.time() < end:
        with sqlite3.connect(db) as c:
            rows = c.execute("SELECT from_version, to_version, ok, error FROM update_reports WHERE component='desktop'"
                             ).fetchall()
        for frm, to, ok, err in rows:
            if to == version:
                print(f"update report from the app: {frm} -> {to}, ok={bool(ok)}, error={err}")
                return 0 if ok else 1
        time.sleep(3)
    print(f"no update report for {version} within {timeout:.0f}s")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bump")
    b.add_argument("version")
    r = sub.add_parser("register")
    r.add_argument("--server", required=True)
    r.add_argument("--data-dir", required=True, type=Path)
    r.add_argument("--agent-token", required=True, type=Path)
    r.add_argument("--dir", required=True, type=Path)
    w = sub.add_parser("wait-report")
    w.add_argument("--data-dir", required=True, type=Path)
    w.add_argument("--version", required=True)
    w.add_argument("--timeout", type=float, default=300)
    a = ap.parse_args()
    if a.cmd == "bump":
        bump(a.version)
        return 0
    if a.cmd == "register":
        register(a.server, a.data_dir, a.agent_token, a.dir)
        return 0
    return wait_report(a.data_dir, a.version, a.timeout)


if __name__ == "__main__":
    sys.exit(main())
