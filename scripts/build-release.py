#!/usr/bin/env python3
"""Build one signed MOTH release. Server and desktop releases are separate:

    python scripts/build-release.py --kind server --out dist                 # cloud + worker bundles
    python scripts/build-release.py --kind desktop --out dist --desktop "MOTH Code_0.3.1_x64-setup.exe"

The signing key comes from the environment (``MOTH_RELEASE_SIGNING_KEY``: base64 of the 32-byte
ed25519 private key, a GitHub Actions secret). It is never written to disk. Without it the script
refuses to produce a manifest, so an unsigned release can never be published by CI.

Outputs in --out:

* ``moth-cloud-<v>.tar.gz``     server + backend source, update agent, deployment files, requirements
* ``moth-worker-<v>.tar.gz``    MOTH Worker bundle (+ ``.sha256`` for one-command enrollment)
* ``moth-release-<v>.json``     manifest: versions, SHA-256 of every file, schema/API versions, rollout
* ``moth-release-<v>.json.sig`` ed25519 signature of the manifest's exact bytes
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {"__pycache__", ".pytest_cache", "tests", "build", "dist", "node_modules"}
sys.path.insert(0, str(ROOT / "server"))
sys.path.insert(0, str(ROOT / "backend"))


def version_of(path: Path) -> str:
    return next(l.split('"')[1] for l in path.read_text().splitlines() if l.startswith("__version__"))


def add_tree(tar: tarfile.TarFile, src: Path, arc: str) -> None:
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(part in SKIP or part.endswith(".egg-info") for part in rel.parts) or p.suffix == ".pyc":
            continue
        add_file(tar, p, f"{arc}/{rel.as_posix()}")


def add_file(tar: tarfile.TarFile, p: Path, arc: str, data: bytes | None = None, mode: int | None = None) -> None:
    info = tar.gettarinfo(str(p), arc) if data is None else tarfile.TarInfo(arc)
    info.uid = info.gid = 0
    info.uname = info.gname = "root"
    info.mtime = 0  # reproducible
    if data is not None:
        info.size, info.mode = len(data), mode or 0o644
        tar.addfile(info, io.BytesIO(data))
    elif p.is_file():
        if mode:
            info.mode = mode
        with open(p, "rb") as f:
            tar.addfile(info, f)
    else:
        tar.addfile(info)


def requirements() -> str:
    import tomllib

    deps: list[str] = []
    for proj in ("backend", "server"):
        data = tomllib.loads((ROOT / proj / "pyproject.toml").read_text())
        deps += [d for d in data["project"]["dependencies"] if not d.startswith("moth-")]
        deps += data["project"].get("optional-dependencies", {}).get("postgres", [])
    seen, out = set(), []
    for d in deps:
        key = d.split(">")[0].split("=")[0].split("[")[0].strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(d)
    return "\n".join(out) + "\n"


def tar_gz(build) -> bytes:
    """A reproducible .tar.gz: entry mtimes are 0 and the gzip header carries no timestamp, so the
    same source always gives the same bytes (and the same SHA-256)."""
    import gzip

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        build(tar)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def entry(path: Path, **extra) -> dict:
    data = path.read_bytes()
    return {"file": path.name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data), **extra}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kind", default="server", choices=["server", "desktop"],
                    help="server: cloud + worker bundles; desktop: the signed Windows installer only")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--channel", default="stable", choices=["stable", "beta"])
    ap.add_argument("--desktop", help="Windows NSIS installer (its .sig must exist next to it); --kind desktop")
    ap.add_argument("--desktop-stages", default="10,50,100", help="staged rollout percentages for desktops")
    ap.add_argument("--notes", default="")
    ap.add_argument("--allow-unsigned", action="store_true", help="tests only: write the manifest without signing")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from moth_server import compat
    from moth_server.db import MIGRATIONS, SCHEMA_VERSION

    components: dict = {}
    if args.kind == "server":
        v = version_of(ROOT / "server/moth_server/__init__.py")
        for other in ("backend/moth/__init__.py", "worker/moth_worker/__init__.py"):
            if version_of(ROOT / other) != v:
                sys.exit(f"version mismatch: {other} is {version_of(ROOT / other)}, server is {v}")
        components = build_server_bundles(out, v)
    else:
        v = json.loads((ROOT / "app/src-tauri/tauri.conf.json").read_text())["version"]
        if not args.desktop:
            sys.exit("--kind desktop needs --desktop <installer>")
        exe = Path(args.desktop)
        sig = exe.with_name(exe.name + ".sig")
        if not sig.exists():
            sys.exit(f"{sig} is missing: desktop updates must be signed with the Tauri updater key")
        if f"_{v}_" not in exe.name:
            sys.exit(f"{exe.name} is not the {v} installer")
        published = exe.name.replace(" ", ".")  # GitHub renames spaces in asset names to dots
        target = out / published
        if target.resolve() != exe.resolve():
            target.write_bytes(exe.read_bytes())
        (out / f"{published}.sig").write_text(sig.read_text())
        components["desktop"] = {"windows-x86_64": entry(target, signature=sig.read_text().strip(), version=v)}

    git_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    stages = [int(x) for x in args.desktop_stages.split(",") if x.strip()]
    manifest = {
        "format": 1, "kind": args.kind, "version": v, "channel": args.channel, "created": int(time.time()),
        "git_sha": git_sha, "api_version": compat.API_VERSION, "schema_version": SCHEMA_VERSION,
        "destructive_migrations": [m[0] for m in MIGRATIONS if m[2]], "min_upgrade_from": "0.2.0",
        "min_client_versions": dict(compat.FLOOR), "components": components,
        "rollout": {"desktop": {"stages": stages, "interval_hours": 6, "max_failure_rate": 0.2, "min_reports": 5},
                    # 0.7.1: every worker moves to a new release at once (an outdated worker cannot
                    # take current jobs); failures above the limit still halt the rollout
                    "worker": {"stages": [100], "interval_hours": 2, "max_failure_rate": 0.3, "min_reports": 3}},
        "notes": args.notes or f"MOTH {'Code' if args.kind == 'desktop' else 'Cloud'} {v}",
    }
    raw = json.dumps(manifest, indent=2, sort_keys=True).encode()
    mname = f"moth-release-{v}.json" if args.kind == "server" else f"moth-release-desktop-{v}.json"
    (out / mname).write_bytes(raw)
    key = os.environ.get("MOTH_RELEASE_SIGNING_KEY", "").strip()
    if not key:
        if not args.allow_unsigned:
            sys.exit("MOTH_RELEASE_SIGNING_KEY is not set: refusing to build an unsigned release")
        print("WARNING: release manifest is NOT signed (tests only)")
    else:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key))
        (out / f"{mname}.sig").write_text(base64.b64encode(sk.sign(raw)).decode() + "\n")
    for p in sorted(out.iterdir()):
        print(f"{p.name}  {p.stat().st_size}")


def build_server_bundles(out: Path, v: str) -> dict:
    name = f"moth-cloud-{v}"

    def cloud(tar):
        add_tree(tar, ROOT / "server", f"{name}/server")
        add_tree(tar, ROOT / "backend", f"{name}/backend")
        add_tree(tar, ROOT / "worker", f"{name}/worker")  # 0.7.2: MOTH Cloud's built-in worker
        add_tree(tar, ROOT / "deploy" / "agent", f"{name}/agent")
        for f in ("install-server.sh",):
            add_file(tar, ROOT / "deploy" / f, f"{name}/deploy/{f}", mode=0o755)
        add_tree(tar, ROOT / "deploy" / "templates", f"{name}/deploy/templates")
        add_file(tar, ROOT / "scripts/backup-server.sh", f"{name}/deploy/backup-server.sh", mode=0o755)
        add_file(tar, ROOT / "deploy/moth-server.env.example", f"{name}/deploy/moth-server.env.example")
        add_file(tar, ROOT / "docs/SERVER.md", f"{name}/INSTALL.md")
        add_file(tar, ROOT, f"{name}/requirements.txt", data=requirements().encode())
        add_file(tar, ROOT, f"{name}/VERSION", data=(v + "\n").encode())

    (out / f"{name}.tar.gz").write_bytes(tar_gz(cloud))
    wname = f"moth-worker-{v}"

    def worker(tar):
        add_tree(tar, ROOT / "worker", f"{wname}/worker")
        add_tree(tar, ROOT / "backend", f"{wname}/backend")
        add_file(tar, ROOT / "worker/install.sh", f"{wname}/install.sh", mode=0o755)
        add_file(tar, ROOT / "worker/install.ps1", f"{wname}/install.ps1", mode=0o755)

    wpath = out / f"{wname}.tar.gz"
    wpath.write_bytes(tar_gz(worker))
    (out / f"{wname}.tar.gz.sha256").write_text(f"{hashlib.sha256(wpath.read_bytes()).hexdigest()}  {wpath.name}\n")
    return {"server": entry(out / f"{name}.tar.gz"), "worker": entry(wpath, version=v)}


if __name__ == "__main__":
    main()
