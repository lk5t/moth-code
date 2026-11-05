#!/usr/bin/env python3
"""Build a versioned MOTH Worker release tarball (+ SHA-256) for one-command enrollment.

    python scripts/build-worker-release.py --out dist/
    moth-server worker-release dist/moth-worker-0.2.0.tar.gz --version 0.2.0   # on the MOTH Server

The tarball contains the worker package, the MOTH backend package it trains with, and
install.sh. Enrollment commands pin the tarball's SHA-256, so a modified download fails
``sha256sum -c`` before anything runs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"__pycache__", ".pytest_cache", "tests", "build", "dist"}


def add_tree(tar: tarfile.TarFile, src: Path, arc: str) -> None:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(part in SKIP or part.endswith(".egg-info") for part in rel.parts) or p.suffix in (".pyc",):
            continue
        info = tar.gettarinfo(str(p), f"{arc}/{rel.as_posix()}")
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        info.mtime = 0  # reproducible
        if p.is_file():
            with open(p, "rb") as f:
                tar.addfile(info, f)
        else:
            tar.addfile(info)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    args = ap.parse_args()
    version = next(l.split('"')[1] for l in (ROOT / "worker/moth_worker/__init__.py").read_text().splitlines()
                   if l.startswith("__version__"))
    name = f"moth-worker-{version}"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT) as tar:
        add_tree(tar, ROOT / "worker", f"{name}/worker")
        add_tree(tar, ROOT / "backend", f"{name}/backend")
        info = tar.gettarinfo(str(ROOT / "worker/install.sh"), f"{name}/install.sh")
        info.mtime = 0
        with open(ROOT / "worker/install.sh", "rb") as f:
            tar.addfile(info, f)
    path = out / f"{name}.tar.gz"
    path.write_bytes(buf.getvalue())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (out / f"{name}.tar.gz.sha256").write_text(f"{digest}  {path.name}\n")
    print(f"{path}  sha256={digest}")


if __name__ == "__main__":
    main()
