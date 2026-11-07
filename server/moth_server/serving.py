"""Model serving: staged rollout (canary), version pinning, and signed model manifests (0.5.3).

* **Staged rollout.** A promoted candidate is first served to a fixed share of users (``percent``,
  chosen by a stable hash of the user id) while the stable model keeps serving everyone else. The
  evolution monitor watches the candidate's own traffic; it then becomes stable for everyone, or is
  dropped — the stable model is never interrupted either way.
* **Version pinning.** A user may pin a model version; it is honoured while that version is loaded
  (stable or canary), otherwise the stable model answers and the reply says so.
* **Signed model manifests.** Every model MOTH Cloud promotes gets a manifest (weights SHA-256, model
  version, lineage, evaluation summary) signed with this server's own ed25519 model key, generated on
  first use and kept in the data directory. MOTH Code pins the key the first time it sees it, so a later
  download whose manifest is not signed by the same key is refused. Official releases additionally
  carry the MOTH release signature.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from moth_server.context import Ctx


# ---- canary ----------------------------------------------------------------------------------------------
def canary(ctx: Ctx) -> dict | None:
    return ctx.extras.get("canary")


def bucket(user_id: int | None) -> int:
    return int(hashlib.sha256(f"moth-rollout:{user_id}".encode()).hexdigest()[:8], 16) % 100


def start_canary(ctx: Ctx, version: int, percent: float, actor_id: int | None = None) -> dict:
    from moth_server import models as M

    engine, health = M.load_checked(ctx, version)
    ctx.extras["canary"] = {"version": version, "engine": engine, "percent": float(percent), "started": time.time()}
    rel = M.release(ctx, version)
    M._set(ctx, version, None, info=json.dumps({**rel["info"], "rollout": {"percent": percent,
                                                                          "started": time.time(), **health}}))
    from moth_server.audit import audit

    audit(ctx.db, "models.canary_started", actor_id, f"release:{version}", {"percent": percent})
    return {"version": version, "percent": percent}


def end_canary(ctx: Ctx, reason: str = "") -> None:
    c = ctx.extras.pop("canary", None)
    if c is not None:
        try:
            c["engine"].unload()
        except Exception:  # noqa: BLE001
            pass


def promote_canary(ctx: Ctx, actor_id: int | None = None, expected_parent: int | None = None) -> dict:
    """The canary becomes the stable model for everyone (its loaded engine is swapped in)."""
    from moth_server import models as M

    c = ctx.extras.get("canary")
    if not c:
        raise M.ReleaseError("no staged rollout is running")
    out = M.deploy(ctx, c["version"], actor_id, engine=c["engine"], expected_parent=expected_parent)
    ctx.extras.pop("canary", None)
    return out


def engine_for(ctx: Ctx, user: dict | None) -> tuple[Any, int | None, str]:
    """(engine, model release version, why) that should answer this user."""
    stable = ctx.extras.get("inference_engine")
    stable_v = ctx.extras.get("deployed_version")
    c = canary(ctx)
    pinned = None
    if user:
        try:
            pinned = (json.loads(user.get("settings") or "{}")).get("pinned_model_version")
        except ValueError:
            pinned = None
    if pinned is not None:
        if pinned == stable_v and stable is not None:
            return stable, stable_v, "pinned"
        if c and pinned == c["version"]:
            return c["engine"], c["version"], "pinned"
    if c and user is not None and bucket(user.get("id")) < c["percent"]:
        return c["engine"], c["version"], "staged rollout"
    return stable, stable_v, "stable"


def loaded_versions(ctx: Ctx) -> list[dict[str, Any]]:
    out = []
    if ctx.extras.get("inference_engine") is not None:
        out.append({"version": ctx.extras.get("deployed_version"), "role": "stable"})
    c = canary(ctx)
    if c:
        out.append({"version": c["version"], "role": "canary", "percent": c["percent"]})
    return out


# ---- server model-signing key -------------------------------------------------------------------------------
def _key_path(ctx: Ctx) -> Path:
    return Path(ctx.settings.data_dir) / "keys" / "model-signing.ed25519"


def signing_key(ctx: Ctx):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    p = _key_path(ctx)
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        sk = Ed25519PrivateKey.generate()
        from cryptography.hazmat.primitives import serialization

        raw = sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        tmp = p.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        os.replace(tmp, p)
    return Ed25519PrivateKey.from_private_bytes(p.read_bytes())


def public_key_b64(ctx: Ctx) -> str:
    from cryptography.hazmat.primitives import serialization

    pk = signing_key(ctx).public_key()
    return base64.b64encode(pk.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def sign_release(ctx: Ctx, version: int) -> dict[str, Any]:
    """Write ``model-manifest.json`` + ``.sig`` for a release (signed with this server's model key)."""
    from moth_server import models as M
    from moth_server.evolution import memory as MEM

    rel = M.release(ctx, version)
    info = rel["info"] or {}
    lineage = MEM.ancestors(ctx, version)
    manifest = {"format": 1, "kind": "model", "server_release": version, "name": rel["name"],
                "model_version": info.get("model_version"), "display_name": info.get("display_name"),
                "family": info.get("family"), "lineage_id": info.get("lineage_id"),
                "weights_sha256": rel["sha256"], "params": info.get("params"),
                "tokenizer_fingerprint": info.get("tokenizer_fingerprint"),
                "parents": [a["version"] for a in lineage[1:]], "method": (lineage[0] if lineage else {}).get("method"),
                "lineage_totals": info.get("lineage_totals"), "growth": info.get("growth"), "created": int(time.time())}
    raw = json.dumps(manifest, indent=1, sort_keys=True).encode()
    d = Path(rel["path"])
    (d / "model-manifest.json").write_bytes(raw)
    (d / "model-manifest.json.sig").write_text(base64.b64encode(signing_key(ctx).sign(raw)).decode() + "\n")
    return manifest
