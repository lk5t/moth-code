#!/usr/bin/env python3
"""Verify a MOTH release directory before it is published (or after downloading it).

    python3 scripts/verify-release.py DIR [--pubkey-file deploy/agent/release-signing.pub]

Checks, using only the Python standard library (works on the server too):

1. ``moth-release-<v>.json.sig`` is a valid ed25519 signature of the manifest by the release key;
2. every file listed in the manifest is present and matches its SHA-256 and size;
3. the cloud bundle contains everything an installation needs, its VERSION matches, it unpacks
   without unsafe paths, and the release key inside it is the same key that signed the manifest;
4. the worker ``.sha256`` file agrees with the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REQUIRED = ["VERSION", "requirements.txt", "INSTALL.md", "agent/moth_agent.py", "agent/ed25519_verify.py",
            "agent/release-signing.pub", "deploy/install-server.sh", "deploy/backup-server.sh",
            "deploy/templates/Caddyfile.in", "deploy/templates/moth-server-run.in", "deploy/templates/moth-agent-run.in",
            "deploy/templates/moth.in", "deploy/templates/moth-server.service.in", "deploy/templates/moth-agent.service.in",
            "server/pyproject.toml", "server/moth_server/__init__.py", "server/moth_server/app.py",
            "server/moth_server/cli.py", "backend/pyproject.toml", "backend/moth/__init__.py",
            "backend/moth/model/evaluate.py"]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir")
    ap.add_argument("--pubkey-file", default=str(ROOT / "deploy/agent/release-signing.pub"))
    a = ap.parse_args()
    d = Path(a.dir)
    sys.path.insert(0, str(ROOT / "deploy/agent"))
    import ed25519_verify  # noqa: E402

    problems: list[str] = []

    def check(ok: bool, msg: str) -> None:
        print(("  OK    " if ok else "  FAIL  ") + msg)
        if not ok:
            problems.append(msg)

    manifests = sorted(d.glob("moth-release-*.json"))
    if len(manifests) != 1:
        print("FAIL: expected exactly one moth-release-<version>.json")
        return 1
    mf = manifests[0]
    raw = mf.read_bytes()
    pub = Path(a.pubkey_file).read_text().strip()
    sig_file = mf.with_name(mf.name + ".sig")
    check(sig_file.exists(), f"{sig_file.name} present")
    check(sig_file.exists() and ed25519_verify.verify_b64(pub, raw, sig_file.read_text().strip()),
          f"manifest signature verifies with release key {pub[:12]}…")
    m = json.loads(raw)
    v = m["version"]
    print(f"release {v} · channel {m['channel']} · schema {m['schema_version']} · api {m['api_version']} · "
          f"commit {m.get('git_sha', '?')[:12]}")
    comps = m["components"]
    entries = [("server", comps.get("server")), ("worker", comps.get("worker"))]
    entries += [(f"desktop/{k}", e) for k, e in (comps.get("desktop") or {}).items()]
    for comp, e in entries:
        if not e:
            continue
        p = d / e["file"]
        check(p.exists() and sha256(p) == e["sha256"] and p.stat().st_size == e["size"],
              f"{comp}: {e['file']} matches SHA-256 {e['sha256'][:16]}… and size {e['size']}")
    kind = m.get("kind") or ("desktop" if set(comps) == {"desktop"} else "server")
    print(f"kind: {kind} release")
    if kind == "desktop":
        check(set(comps) == {"desktop"}, "desktop release contains only the desktop app")
        for plat, e in comps["desktop"].items():
            check(bool(e.get("signature")), f"desktop/{plat}: carries the updater signature")
            sigf = d / f"{e['file']}.sig"
            check(sigf.exists() and sigf.read_text().strip() == e["signature"].strip(),
                  f"desktop/{plat}: {sigf.name} matches the signature in the manifest")
            check(e.get("version") == v and f"_{v}_" in e["file"], f"desktop/{plat}: installer is version {v}")
        print("PASS" if not problems else f"FAILED: {len(problems)} problem(s)")
        return 0 if not problems else 1
    check("server" in comps, "manifest contains the cloud server bundle")
    bundle = d / comps["server"]["file"]
    if bundle.exists():
        with tarfile.open(bundle) as t:
            names = t.getnames()
            unsafe = [n for n in names if n.startswith("/") or ".." in Path(n).parts]
            links = [m.name for m in t.getmembers() if m.issym() or m.islnk()]
            root = f"moth-cloud-{v}/"
            check(not unsafe and not links, "bundle has no absolute paths, '..' or links")
            missing = [r for r in REQUIRED if root + r not in names]
            check(not missing, "bundle contains every required file" + (f" (missing: {missing})" if missing else ""))
            ver = t.extractfile(root + "VERSION").read().decode().strip()
            check(ver == v, f"bundle VERSION is {ver}")
            inner_pub = t.extractfile(root + "agent/release-signing.pub").read().decode().strip()
            check(inner_pub == pub, "release key inside the bundle is the key that signed this release")
            inst = t.getmember(root + "deploy/install-server.sh")
            check(bool(inst.mode & 0o111), "install-server.sh is executable")
    wsum = d / f"{comps['worker']['file']}.sha256" if comps.get("worker") else None
    if wsum and wsum.exists():
        check(wsum.read_text().split()[0] == comps["worker"]["sha256"], f"{wsum.name} agrees with the manifest")
    print("PASS" if not problems else f"FAILED: {len(problems)} problem(s)")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
