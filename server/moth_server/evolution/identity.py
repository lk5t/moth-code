"""One public identity: MOTH 0.0.1, 0.0.2, 0.0.3 … (0.7.0).

Every native model lineage begins at MOTH 0.0.1. The public version advances by one only when a new
model has been deployed and has passed monitoring (a verified upgrade). Experiments, checkpoints and
rejected candidates never change it; internal release numbers (``v52``) and package names stay for
storage and compatibility but are not shown as the model's name. Capability milestones are still
measured and recorded with each version — they no longer decide the number.

Models from before 0.7.0 were labelled ``MOTH 0.01``, ``MOTH 0.02`` (a version advanced only on a
capability milestone, so many verified upgrades shared one label). ``migrate`` renumbers them once,
per lineage, in the order they were verified: weights are untouched, the old label is kept as
``model_version_legacy`` and each signed model manifest is re-signed with the new name.
"""

from __future__ import annotations

import json
import re
from typing import Any

from moth_server.context import Ctx
from moth_server.evolution import memory as MEM

FIRST = "0.0.1"
FLAG = "model_identity_v070"
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def is_current(v: str | None) -> bool:
    return bool(v and _SEMVER.match(str(v)))


def next_version(v: str | None) -> str:
    m = _SEMVER.match(str(v or ""))
    if not m:
        return FIRST
    major, minor, patch = (int(x) for x in m.groups())
    return f"{major}.{minor}.{patch + 1}"


def display(v: str) -> str:
    return f"MOTH {v}"


def migrate(ctx: Ctx) -> dict[str, Any]:
    """Renumber pre-0.7.0 public versions (once). Safe to call on every start."""
    from moth_server import models as M

    if ctx.db.get_config(FLAG, None):
        return {"migrated": 0, "already": True}
    renamed: list[tuple[int, str, str]] = []
    by_lineage: dict[str, list[dict]] = {}
    for r in sorted(M.list_releases(ctx), key=lambda r: r["version"]):
        info = r.get("info") or {}
        if info.get("model_version") and not is_current(info["model_version"]):
            by_lineage.setdefault(str(info.get("lineage_id") or info.get("family") or "MOTH"), []).append(r)
    for releases in by_lineage.values():
        current = None
        for r in releases:  # release numbers grow in the order versions were verified
            current = next_version(current) if current else FIRST
            info = dict(r["info"])
            old = info["model_version"]
            info.update(model_version_legacy=old, model_version=current, display_name=display(current))
            M._set(ctx, r["version"], info=json.dumps(info))
            renamed.append((r["version"], old, current))
            try:
                from pathlib import Path

                from moth_server import serving

                if r.get("path") and (Path(r["path"]) / "model-manifest.json").exists():
                    serving.sign_release(ctx, r["version"])  # the signed name follows the new identity
            except Exception:  # noqa: BLE001 — files may be gone (retention); the record still migrates
                pass
    ctx.db.set_config(FLAG, {"done": True, "renamed": renamed})
    if renamed:
        latest = renamed[-1]
        MEM.event(ctx, "model.identity_migrated",
                  f"Model versions now count verified upgrades: {len(renamed)} earlier versions were renumbered "
                  f"(the latest, v{latest[0]}, is now MOTH {latest[2]}, previously MOTH {latest[1]}). "
                  "No weights changed.", renamed=renamed)
    return {"migrated": len(renamed), "renamed": renamed}
