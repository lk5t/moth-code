"""Build a signed official MOTH model release (``kind: model``).

    MOTH_RELEASE_SIGNING_KEY=... python scripts/build-model-release.py --package DIR --evaluation report.json \
        --version 0.1 --out dist

* ``moth-model-<v>.tar.gz`` — the exported model package (weights, config, tokenizer, manifest, attribution)
* ``moth-release-model-<v>.json`` + ``.sig`` — the manifest, signed with the MOTH release key: model
  identity, parameters, tokenizer, weights SHA-256, the evaluation report and release-criteria result

A stable release is refused unless the evaluation passed the release criteria. MOTH Cloud's update agent
verifies the signature and the archive's SHA-256, and the server re-checks both before importing it.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--evaluation", required=True, type=Path, help="evaluation report with release criteria")
    ap.add_argument("--version", required=True, help="model version, e.g. 0.1")
    ap.add_argument("--channel", default="stable", choices=["stable", "beta"])
    ap.add_argument("--out", default="dist", type=Path)
    ap.add_argument("--allow-unsigned", action="store_true", help="tests only")
    a = ap.parse_args()
    pkg = a.package
    man = json.loads((pkg / "manifest.json").read_text())
    if sha256(pkg / "model.pt") != man["sha256"]:
        sys.exit("model.pt does not match its manifest")
    if str(man.get("model_version")) != a.version:
        sys.exit(f"the package is model version {man.get('model_version')}, not {a.version}")
    ev = json.loads(a.evaluation.read_text())
    if a.channel == "stable" and not (ev.get("criteria") or {}).get("passed"):
        sys.exit("the evaluation did not pass the release criteria: refusing to publish a stable model release")
    a.out.mkdir(parents=True, exist_ok=True)
    name = f"moth-model-{a.version}.tar.gz"
    with tarfile.open(a.out / name, "w:gz") as tar:
        for f in ("manifest.json", "config.json", "tokenizer.json", "model.pt", "ATTRIBUTION.md"):
            if (pkg / f).exists():
                info = tar.gettarinfo(str(pkg / f), arcname=f"moth-{a.version}/{f}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with open(pkg / f, "rb") as fh:
                    tar.addfile(info, fh)
    git_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {
        # release versions are X.Y.Z; the model's own version (MOTH 0.1) is model.model_version
        "format": 1, "kind": "model", "version": a.version if a.version.count(".") == 2 else f"{a.version}.0",
        "channel": a.channel, "created": int(time.time()),
        "git_sha": git_sha,
        "model": {k: man.get(k) for k in ("display_name", "family", "lineage_id", "params", "architecture",
                                          "context_length", "tokenizer_fingerprint", "dtype")}
        | {"weights_sha256": man["sha256"], "model_version": a.version, "method": man.get("method", "foundation"),
           "training": man.get("training"), "evaluation": ev},
        "components": {"model": {"file": name, "sha256": sha256(a.out / name), "size": (a.out / name).stat().st_size}},
        "notes": f"{man.get('display_name') or 'MOTH ' + a.version}",
    }
    raw = json.dumps(manifest, indent=2, sort_keys=True).encode()
    mname = f"moth-release-model-{a.version}.json"
    (a.out / mname).write_bytes(raw)
    key = os.environ.get("MOTH_RELEASE_SIGNING_KEY", "").strip()
    if key:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(key))
        (a.out / f"{mname}.sig").write_text(base64.b64encode(sk.sign(raw)).decode() + "\n")
    elif not a.allow_unsigned:
        sys.exit("MOTH_RELEASE_SIGNING_KEY is not set: refusing to build an unsigned release")
    for p in sorted(a.out.iterdir()):
        print(f"{p.name}  {p.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
