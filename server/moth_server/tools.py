"""2.2.3: tools MOTH Cloud installs for itself, without administrator rights.

Node.js runs the JavaScript exam (``moth.model.exams.js_suite``). Without it that exam is "not measurable" and
JavaScript skill never counts towards promotion. The official Linux build is downloaded from nodejs.org into the
server's data directory, checked against the published SHA-256 list, unpacked and put on this process's PATH
(the benchmark subprocesses inherit it). Nothing outside the data directory is touched.
"""

from __future__ import annotations

import hashlib
import os
import platform
import posixpath
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

from moth_server.context import Ctx

NODE_VERSION = "v22.11.0"            # an LTS release
NODE_BASE = "https://nodejs.org/dist"
RETRY_AFTER_S = 6 * 3600             # a failed download is tried again after six hours
ATTEMPT_KEY = "tools_node_attempt"



def check_members(members: list[tarfile.TarInfo]) -> None:
    """Refuse an archive with absolute paths, '..' escapes, devices, or links pointing outside it."""
    for m in members:
        name = posixpath.normpath(m.name)
        if name.startswith(("/", "../")) or name == ".." or m.isdev():
            raise RuntimeError(f"unsafe path in archive: {m.name}")
        if m.issym() or m.islnk():
            link = m.linkname
            target = posixpath.normpath(posixpath.join(posixpath.dirname(name), link) if m.issym() else link)
            if posixpath.isabs(link) or target.startswith("../") or target == "..":
                raise RuntimeError(f"unsafe link in archive: {m.name} -> {link}")

def _arch() -> str | None:
    m = platform.machine().lower()
    return {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(m)


def node_home(ctx: Ctx) -> Path | None:
    arch = _arch()
    if platform.system() != "Linux" or not arch:
        return None
    return Path(ctx.settings.data_dir) / "tools" / f"node-{NODE_VERSION}-linux-{arch}"


def activate(ctx: Ctx) -> str | None:
    """Put an installed Node.js on PATH; returns the node binary in use (or None)."""
    home = node_home(ctx)
    if home and (home / "bin" / "node").is_file():
        bin_dir = str(home / "bin")
        if bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
    return shutil.which("node")


def _expected_sha(sums: str, name: str) -> str | None:
    for line in sums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == name:
            return parts[0].lower()
    return None


def ensure_node(ctx: Ctx, http_get=None) -> dict[str, Any]:
    """Install Node.js if it is missing. Returns {"status": "present"|"installed"|"skipped"|"failed", ...}."""
    found = activate(ctx)
    if found:
        return {"status": "present", "node": found}
    if ctx.extras.get("disable_background") and http_get is None:  # tests never download
        return {"status": "skipped", "reason": "background work is off"}
    home = node_home(ctx)
    if home is None:
        return {"status": "skipped", "reason": f"no official build for {platform.system()} {platform.machine()}"}
    last = float(ctx.db.get_config(ATTEMPT_KEY, 0) or 0)
    if time.time() - last < RETRY_AFTER_S and http_get is None:
        return {"status": "skipped", "reason": "a recent attempt failed; retrying later"}
    ctx.db.set_config(ATTEMPT_KEY, time.time())
    if http_get is None:
        import httpx

        def http_get(url: str) -> bytes:
            with httpx.Client(timeout=300, follow_redirects=True) as c:
                r = c.get(url)
                r.raise_for_status()
                return r.content
    name = f"{home.name}.tar.xz"
    try:
        sums = http_get(f"{NODE_BASE}/{NODE_VERSION}/SHASUMS256.txt").decode()
        want = _expected_sha(sums, name)
        if not want:
            raise RuntimeError(f"{name} is not in the published checksum list")
        blob = http_get(f"{NODE_BASE}/{NODE_VERSION}/{name}")
        got = hashlib.sha256(blob).hexdigest()
        if got != want:
            raise RuntimeError(f"checksum mismatch for {name}")
        tools = home.parent
        tools.mkdir(parents=True, exist_ok=True)
        archive = tools / name
        archive.write_bytes(blob)
        staging = tools / f".{home.name}.partial"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        with tarfile.open(archive) as tf:
            check_members(tf.getmembers())  # every path and link stays inside the archive's own folder
            try:
                tf.extractall(staging, filter="fully_trusted")  # checked above (2.5: the "data" filter refused
            except TypeError:  # Node's own relative links, e.g. bin/corepack -> ../lib/..., on some servers)
                tf.extractall(staging)
        archive.unlink(missing_ok=True)
        shutil.rmtree(home, ignore_errors=True)
        (staging / home.name).rename(home)
        shutil.rmtree(staging, ignore_errors=True)
    except Exception as e:  # noqa: BLE001 — retried later; the exam stays "not measurable" meanwhile
        return {"status": "failed", "reason": f"{type(e).__name__}: {e}"[:300]}
    ctx.db.set_config(ATTEMPT_KEY, 0)
    return {"status": "installed", "node": activate(ctx), "version": NODE_VERSION}
