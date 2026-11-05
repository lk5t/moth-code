"""Build real, signed MOTH releases for tests (test signing key, never the production key)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import shutil
import tarfile
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]


class TestKey:
    def __init__(self):
        self.sk = Ed25519PrivateKey.generate()
        self.public_b64 = base64.b64encode(self.sk.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        self.private_b64 = base64.b64encode(self.sk.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())).decode()

    def sign(self, raw: bytes) -> str:
        return base64.b64encode(self.sk.sign(raw)).decode()


def entry(path: Path, **extra) -> dict:
    data = path.read_bytes()
    return {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), **extra}


def _tree(tar: tarfile.TarFile, src: Path, arc: str) -> None:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(x in ("__pycache__", "tests", ".pytest_cache") or x.endswith(".egg-info") for x in rel.parts):
            continue
        tar.add(p, f"{arc}/{rel.as_posix()}", recursive=False)


def worker_bundle(out: Path, version: str) -> Path:
    """A real worker bundle whose code reports ``version`` (copied from this repository)."""
    stage = out / f"src-worker-{version}"
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(ROOT / "worker", stage / "worker", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    shutil.copytree(ROOT / "backend", stage / "backend", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info",
                                                                                    "tests"))
    init = stage / "worker/moth_worker/__init__.py"
    init.write_text("\n".join(f'__version__ = "{version}"' if l.startswith("__version__") else l
                              for l in init.read_text().splitlines()) + "\n")
    path = out / f"moth-worker-{version}.tar.gz"
    with tarfile.open(path, "w:gz") as tar:
        _tree(tar, stage / "worker", f"moth-worker-{version}/worker")
        _tree(tar, stage / "backend", f"moth-worker-{version}/backend")
    return path


def release(out: Path, key: TestKey, version: str, *, worker: Path | None = None, desktop: bool = False,
            server: Path | None = None, channel: str = "stable", rollout: dict | None = None,
            extra: dict | None = None) -> tuple[bytes, str]:
    """Write moth-release-<v>.json(+.sig) next to the given component files; returns (raw, signature)."""
    comps: dict = {}
    if server:
        comps["server"] = entry(server)
    if worker:
        comps["worker"] = entry(worker, version=version)
    if desktop:
        exe = out / f"MOTH.Code_{version}_x64-setup.exe"
        exe.write_bytes(b"MZ fake installer for tests " + version.encode() * 1000)
        comps["desktop"] = {"windows-x86_64": entry(exe, signature=f"untrusted comment: test\nSIG{version}", version=version)}
    m = {"format": 1, "version": version, "channel": channel, "created": int(time.time()), "api_version": 3,
         "schema_version": 2, "destructive_migrations": [], "min_upgrade_from": "0.2.0", "components": comps,
         "rollout": rollout or {}, "notes": f"test release {version}", **(extra or {})}
    raw = json.dumps(m, indent=2, sort_keys=True).encode()
    sig = key.sign(raw)
    (out / f"moth-release-{version}.json").write_bytes(raw)
    (out / f"moth-release-{version}.json.sig").write_text(sig + "\n")
    return raw, sig


def tar_dir_bytes(d: Path, arc: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(d, arc)
    return buf.getvalue()
