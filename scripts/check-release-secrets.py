#!/usr/bin/env python3
"""Check the release signing secrets without ever printing them.

Run by .github/workflows/check-secrets.yml (secrets arrive as environment variables). For each
secret it reports only "set"/"missing", and whether it matches the public key committed in the
repository:

* MOTH_RELEASE_SIGNING_KEY  — the ed25519 private key must produce deploy/agent/release-signing.pub
  (and worker/moth_worker/release-signing.pub).
* TAURI_SIGNING_PRIVATE_KEY + TAURI_SIGNING_PRIVATE_KEY_PASSWORD — a test file signed with
  `tauri signer sign` (done by the workflow; the signature path is passed as an argument) must verify
  against app/src-tauri/updater.pub (minisign format).

Exit code 0 only if everything is set and matches.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def status(name: str) -> bool:
    ok = bool(os.environ.get(name, "").strip())
    print(f"{name}: {'set' if ok else 'MISSING'}")
    return ok


def check_release_key() -> bool:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    try:
        sk = Ed25519PrivateKey.from_private_bytes(base64.b64decode(os.environ["MOTH_RELEASE_SIGNING_KEY"].strip()))
    except Exception:  # noqa: BLE001 — never echo the value
        print("MOTH_RELEASE_SIGNING_KEY: is not a valid ed25519 private key (expected one line of base64)")
        return False
    pub = base64.b64encode(sk.public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw)).decode()
    good = True
    for f in ("deploy/agent/release-signing.pub", "worker/moth_worker/release-signing.pub"):
        match = (ROOT / f).read_text().strip() == pub
        print(f"MOTH_RELEASE_SIGNING_KEY matches {f}: {'yes' if match else 'NO'}")
        good &= match
    return good


def _minisign_lines(b64_file_text: str) -> list[str]:
    return [l for l in base64.b64decode(b64_file_text.strip()).decode().splitlines() if l.strip()]


def check_updater_signature(message: Path, sig_path: Path) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not sig_path.exists():
        print("TAURI_SIGNING_PRIVATE_KEY + PASSWORD: signing FAILED (wrong password or invalid key)")
        return False
    pub = base64.b64decode(_minisign_lines((ROOT / "app/src-tauri/updater.pub").read_text())[1])
    sig = base64.b64decode(_minisign_lines(sig_path.read_text())[1])
    alg, pub_id, pub_key = pub[:2], pub[2:10], pub[10:42]
    sig_alg, sig_id, signature = sig[:2], sig[2:10], sig[10:74]
    if sig_id != pub_id:
        print("TAURI_SIGNING_PRIVATE_KEY matches app/src-tauri/updater.pub: NO (different key id)")
        return False
    data = message.read_bytes()
    if sig_alg == b"ED":  # prehashed (BLAKE2b-512), what tauri uses
        data = hashlib.blake2b(data, digest_size=64).digest()
    try:
        Ed25519PublicKey.from_public_bytes(pub_key).verify(signature, data)
        print("TAURI_SIGNING_PRIVATE_KEY + PASSWORD sign updates that verify against app/src-tauri/updater.pub: yes")
        return True
    except InvalidSignature:
        print("TAURI_SIGNING_PRIVATE_KEY matches app/src-tauri/updater.pub: NO (signature does not verify)")
        return False
    finally:
        _ = alg


def main() -> int:
    ok = all([status("MOTH_RELEASE_SIGNING_KEY"), status("TAURI_SIGNING_PRIVATE_KEY"),
              status("TAURI_SIGNING_PRIVATE_KEY_PASSWORD")])
    url = os.environ.get("MOTH_CLOUD_URL", "").strip()
    print(f"MOTH_CLOUD_URL (variable): {url if url else 'not set yet (needed once you have a domain)'}")
    if os.environ.get("MOTH_RELEASE_SIGNING_KEY", "").strip():
        ok &= check_release_key()
    if len(sys.argv) == 3 and os.environ.get("TAURI_SIGNING_PRIVATE_KEY", "").strip():
        ok &= check_updater_signature(Path(sys.argv[1]), Path(sys.argv[2]))
    print("RESULT:", "all release secrets are present and correct" if ok else "something needs attention (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
