"""MOTH Worker self-update.

The server offers a newer worker (``GET /v1/worker/update``) together with the **signed release
manifest**. The worker verifies the manifest signature with the release public key pinned in this
package, downloads the bundle, checks its SHA-256 against the manifest, test-imports the new code,
and only then switches ``<home>/current`` to it (the previous version is kept). Updates are applied
between training jobs, never during one, so no training progress is discarded.

After switching, the worker restarts itself into the new version. If the new version fails to
start three times, the previous version is restored automatically.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Callable

from moth_worker import __version__
from moth_worker import ed25519_verify

PUBKEY_FILE = Path(__file__).with_name("release-signing.pub")
MAX_START_ATTEMPTS = 3


class UpdateError(RuntimeError):
    pass


def pubkey() -> str:
    return os.environ.get("MOTH_RELEASE_PUBKEY") or (PUBKEY_FILE.read_text().strip() if PUBKEY_FILE.exists() else "")


def _vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("-")[0].split("+")[0].split("."))


def code_dirs(home: Path) -> Path | None:
    cur = home / "current"
    return cur.resolve() if cur.is_symlink() and (cur.resolve() / "worker" / "moth_worker").is_dir() else None


def running_version_dir(home: Path) -> str | None:
    d = code_dirs(home)
    if not d:
        return None
    init = d / "worker" / "moth_worker" / "__init__.py"
    for line in init.read_text().splitlines():
        if line.startswith("__version__"):
            return line.split('"')[1]
    return None


def reexec_into_current(home: Path, argv: list[str]) -> None:
    """Called first thing by the CLI: run the newest installed version instead of this one."""
    if os.environ.get("MOTH_WORKER_REEXEC") == "1":
        return
    d, v = code_dirs(home), running_version_dir(home)
    if not d or not v or _vt(v) <= _vt(__version__):
        return
    env = {**os.environ, "MOTH_WORKER_REEXEC": "1",
           # remembered so a later restart can choose the newest version again (see restart)
           "MOTH_WORKER_BASE_PYTHONPATH": os.environ.get("MOTH_WORKER_BASE_PYTHONPATH", os.environ.get("PYTHONPATH", "")),
           "PYTHONPATH": os.pathsep.join([str(d / "worker"), str(d / "backend"), os.environ.get("PYTHONPATH", "")])}
    os.execve(sys.executable, [sys.executable, "-m", "moth_worker.cli", *argv], env)


def _safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as tar:
        for m in tar.getmembers():
            if m.issym() or m.islnk() or m.isdev() or m.name.startswith("/") or ".." in Path(m.name).parts:
                raise UpdateError("update bundle contains unsafe paths")
        if hasattr(tarfile, "data_filter"):  # also refuse unsafe modes/devices where Python supports it
            tar.extractall(dest, filter="data")
        else:
            tar.extractall(dest)


def apply(info: dict, home: Path, download: Callable[[str, Path], None], log: Callable[[str], None] = print) -> str:
    """Verify and install an offered update. Returns the new version (not yet running)."""
    key = pubkey()
    if not key:
        raise UpdateError("no release public key is pinned in this worker; reinstall it from MOTH Code")
    raw = base64.b64decode(info["manifest"])
    if not ed25519_verify.verify_b64(key, raw, info["signature"]):
        raise UpdateError("the update's release manifest signature is invalid — update refused")
    manifest = json.loads(raw)
    entry = (manifest.get("components") or {}).get("worker") or {}
    v = manifest.get("version")
    if not entry or v != info["version"] or entry.get("sha256") != info["sha256"] or entry.get("file") != info["file"]:
        raise UpdateError("the offered update does not match its signed manifest")
    if _vt(v) <= _vt(__version__):
        raise UpdateError(f"refusing to 'update' to {v}, which is not newer than {__version__}")
    updates = home / "updates"
    updates.mkdir(parents=True, exist_ok=True)
    bundle = updates / entry["file"]
    download(info["url"], bundle)
    h = hashlib.sha256()
    with open(bundle, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != entry["sha256"]:
        bundle.unlink(missing_ok=True)
        raise UpdateError("the downloaded update is corrupted (SHA-256 mismatch)")
    versions = home / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{v}-", dir=versions))
    try:
        _safe_extract(bundle, staging)
        roots = [p for p in staging.iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "worker" / "moth_worker").is_dir():
            raise UpdateError("the update bundle layout is not recognised")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(roots[0] / "worker"), str(roots[0] / "backend")])}
        out = subprocess.run([sys.executable, "-c", "import moth_worker, moth; print(moth_worker.__version__)"],
                             capture_output=True, text=True, env=env, timeout=300)
        if out.returncode != 0 or out.stdout.strip() != v:
            raise UpdateError(f"the new version failed its start test: {(out.stderr or out.stdout).strip()[-300:]}")
        target = versions / v
        shutil.rmtree(target, ignore_errors=True)
        os.replace(roots[0], target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        bundle.unlink(missing_ok=True)
    cur = home / "current"
    if cur.is_symlink():
        _relink(home / "previous", cur.resolve())
    _relink(cur, target)
    (home / "update-pending.json").write_text(json.dumps({"version": v, "from": __version__, "attempts": 0}))
    log(f"MOTH Worker {v} installed (from {__version__}); restarting into it")
    return v


def _relink(link: Path, target: Path) -> None:
    tmp = link.with_name(f".{link.name}.tmp")
    tmp.unlink(missing_ok=True)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def startup_guard(home: Path, log: Callable[[str], None] = print) -> dict | None:
    """Count start attempts of a freshly installed version; restore the previous one if it keeps failing."""
    p = home / "update-pending.json"
    if not p.exists():
        return None
    pending = json.loads(p.read_text())
    pending["attempts"] = int(pending.get("attempts", 0)) + 1
    if pending["attempts"] > MAX_START_ATTEMPTS:
        prev = home / "previous"
        if prev.is_symlink():
            _relink(home / "current", prev.resolve())
        else:
            (home / "current").unlink(missing_ok=True)
        p.unlink()
        log(f"MOTH Worker {pending['version']} failed to start {MAX_START_ATTEMPTS} times; restored the previous version")
        return {**pending, "reverted": True}
    p.write_text(json.dumps(pending))
    return pending


def confirm_healthy(home: Path) -> dict | None:
    """The new version reached the server: the update is complete."""
    p = home / "update-pending.json"
    if not p.exists():
        return None
    pending = json.loads(p.read_text())
    if pending.get("version") != __version__:
        return None
    p.unlink()
    return pending


def restart_env() -> dict[str, str]:
    """The environment for a restart: as before the first re-exec, so the newest installed version is
    chosen again. Inheriting MOTH_WORKER_REEXEC and the previous version's PYTHONPATH made a second update
    start the old version again, which re-installed the same update and restarted — in a loop."""
    env = dict(os.environ)
    if env.pop("MOTH_WORKER_REEXEC", None) is not None:
        base = env.pop("MOTH_WORKER_BASE_PYTHONPATH", "")
        if base:
            env["PYTHONPATH"] = base
        else:
            env.pop("PYTHONPATH", None)
    return env


def restart(argv: list[str]) -> None:
    os.execve(sys.executable, [sys.executable, "-m", "moth_worker.cli", *argv], restart_env())
