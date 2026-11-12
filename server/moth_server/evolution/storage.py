"""MOTH Control System: storage on MOTH Cloud — what uses space, what must be kept, safe cleanup.

Every item is classified at the moment it is listed *and again* at the moment it is deleted, so a
cleanup confirmed a while ago can never remove something that has since become needed. Protected:
the deployed model and every version currently serving users, versions with a rollback role, the
base and candidates of active work, the latest prepared data and data in use, running experiments'
checkpoints, and anything during a Genesis Reset. Removable: downloaded source caches (fetched again
when needed), superseded or failed data preparations, finished experiments' run folders (their
measurements stay in the database) and rejected candidate models (their records stay as history).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from moth_server.context import Ctx
from moth_server.db import now
from moth_server.evolution import memory as MEM

LABELS = {
    "models": ("Model versions", "Rejected candidates can be removed; the deployed model, versions serving users and rollback versions are kept."),
    "data": ("Prepared training data", "The latest preparation and any data in use are kept; older and failed preparations can be removed."),
    "cache": ("Download cache", "Original downloads of trusted datasets. Removing them frees space; they are downloaded again when data is next prepared."),
    "runs": ("Training run folders", "Checkpoints and logs of finished experiments. Their measurements stay in the history."),
}


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file() and not f.is_symlink():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _active(ctx: Ctx) -> dict[str, set]:
    """What active work depends on right now."""
    from moth_server import serving

    cyc = MEM.active_cycle(ctx)
    exps = [e for e in MEM.experiments(ctx, limit=200) if e["status"] not in MEM.TERMINAL_EXPERIMENT]
    builds = {((e["config"] or {}).get("mixture") or {}).get("build_id") for e in exps}
    datasets = {e["dataset_id"] for e in exps}
    versions = {e.get("candidate_version") for e in exps} | {e["base_version"] for e in exps}
    if cyc:
        versions |= {cyc.get("base_version"), cyc.get("candidate_version")}
    try:
        versions |= {r.get("version") for r in serving.loaded_versions(ctx)}
    except Exception:  # noqa: BLE001
        pass
    return {"experiments": {e["id"] for e in exps}, "builds": builds - {None}, "datasets": datasets, "versions": versions - {None}}


def items(ctx: Ctx) -> list[dict[str, Any]]:
    from moth_server import models as M
    from moth_server.evolution import backends as B
    from moth_server.evolution.native_reset import fenced
    from moth_server.intelligence import library

    act = _active(ctx)
    reset = fenced(ctx)
    out: list[dict[str, Any]] = []

    def add(kind: str, iid: str, label: str, path: Path | None, protected: str | None):
        if path is not None and not path.exists():
            return
        out.append({"id": iid, "category": kind, "label": label, "bytes": _size(path) if path else 0,
                    "protected": bool(protected or reset), "reason": "A Genesis Reset is in progress" if reset else protected})

    deployed = M.deployed(ctx)
    for r in M.list_releases(ctx):
        path = Path(r["path"]) if r.get("path") else None
        if path is None:
            continue
        name = (r.get("info") or {}).get("display_name") or r["name"]
        why = ("Deployed — serving MOTH" if r["status"] == "deployed" else
               "Serving users or needed by active training" if r["version"] in act["versions"] else
               "Available to deploy or roll back to" if r["status"] in ("published",) else
               "Being uploaded, evaluated or deployed" if r["status"] in ("uploading", "uploaded", "evaluating", "deploying") else None)
        if deployed and r["version"] == deployed["version"]:
            why = "Deployed — serving MOTH"
        add("models", f"model:{r['version']}", f"v{r['version']} · {name} · {r['status']}", path, why)

    st = library.status(ctx)
    ready = [b for b in st["builds"] if b["status"] == "ready"]
    latest = max((b["id"] for b in ready), default=None)
    for b in st["builds"]:
        path = library.root(ctx) / "builds" / f"build-{b['id']}"
        why = ("The latest prepared data" if b["id"] == latest else
               "Being prepared" if b["status"] in ("queued", "running") else
               "In use by active training" if b["id"] in act["builds"] else None)
        add("data", f"build:{b['id']}", f"Preparation #{b['id']} · {b['status']}", path, why)
    cache = library.root(ctx) / "cache"
    building = any(b["status"] in ("queued", "running") for b in st["builds"])
    if cache.exists():
        for d in sorted(p for p in cache.iterdir() if p.is_dir()):
            add("cache", f"cache:{d.name}", d.name.replace("__", "/"), d, "Data is being prepared from it now" if building else None)

    runs = B.runs_root(ctx)
    for d in sorted(p for p in runs.iterdir() if p.is_dir() and p.name.startswith("exp-")):
        try:
            eid = int(d.name.split("-")[1])
        except ValueError:
            continue
        add("runs", f"run:{eid}", f"Experiment #{eid}", d, "Experiment still running or resumable" if eid in act["experiments"] else None)
    return out


def summary(ctx: Ctx) -> dict[str, Any]:
    du = shutil.disk_usage(ctx.settings.data_dir)
    all_items = items(ctx)
    cats = []
    for key, (label, explanation) in LABELS.items():
        its = [i for i in all_items if i["category"] == key]
        cats.append({"id": key, "label": label, "explanation": explanation, "bytes": sum(i["bytes"] for i in its),
                     "removable_bytes": sum(i["bytes"] for i in its if not i["protected"]), "items": its})
    return {"disk": {"total": du.total, "free": du.free, "used": du.used}, "categories": cats,
            "removable_bytes": sum(c["removable_bytes"] for c in cats)}


def cleanup(ctx: Ctx, ids: list[str], actor_id: int | None) -> dict[str, Any]:
    """Delete the requested items that are still removable now; report the rest with the reason."""
    from moth_server import models as M
    from moth_server.intelligence import library

    current = {i["id"]: i for i in items(ctx)}  # re-check at deletion time
    removed, skipped, freed = [], [], 0
    for iid in dict.fromkeys(ids):
        it = current.get(iid)
        if it is None:
            skipped.append({"id": iid, "reason": "no longer exists"}); continue
        if it["protected"]:
            skipped.append({"id": iid, "reason": it["reason"]}); continue
        kind, key = iid.split(":", 1)
        try:
            if kind == "model":
                rel = M.release(ctx, int(key))
                shutil.rmtree(rel["path"], ignore_errors=True)
                M._set(ctx, int(key), "failed", path="",
                       error=f"Files removed by storage cleanup; the record is kept as history ({rel['status']} before).")
            elif kind == "build":
                shutil.rmtree(library.root(ctx) / "builds" / f"build-{int(key)}", ignore_errors=True)
            elif kind == "cache":
                target = (library.root(ctx) / "cache" / key).resolve()
                if target.parent != (library.root(ctx) / "cache").resolve():
                    raise ValueError("invalid cache entry")
                shutil.rmtree(target, ignore_errors=True)
            elif kind == "run":
                from moth_server.evolution import backends as B

                shutil.rmtree(B.runs_root(ctx) / f"exp-{int(key):05d}", ignore_errors=True)
            else:
                raise ValueError("unknown item")
            removed.append(iid); freed += it["bytes"]
        except Exception as e:  # noqa: BLE001 — report and continue with the others
            skipped.append({"id": iid, "reason": str(e)[:200]})
    if removed:
        MEM.event(ctx, "storage.cleaned", f"Storage cleanup freed {freed / 1024**2:.1f} MB ({len(removed)} items).",
                  removed=removed, bytes=freed, actor=actor_id)
    return {"removed": removed, "skipped": skipped, "freed_bytes": freed, "at": now()}


def apply_retention(ctx: Ctx, previous_version: int | None) -> dict[str, Any]:
    """After a promotion passed monitoring: keep the active model and the previous working one.

    Removed: files of older versions and of candidates that were not promoted. Never removed: the
    deployed model, the previous working model (the rollback target), any version serving users or
    used by active work, and versions still being uploaded, evaluated or deployed. Records stay as
    history. ``retention.models`` 0 keeps everything.
    """
    from moth_server import models as M
    from moth_server.evolution import settings as S

    keep_n = int((S.get(ctx).get("retention") or {}).get("models", 2))
    if keep_n <= 0:
        return {"removed": [], "freed_bytes": 0, "kept": "all"}
    deployed = M.deployed(ctx)
    if deployed is None:
        return {"removed": [], "freed_bytes": 0, "kept": "nothing deployed"}
    keep = {deployed["version"]}
    if keep_n >= 2 and previous_version is not None:
        prev = M.release(ctx, previous_version)
        if prev and prev.get("path") and Path(prev["path"]).exists():
            keep.add(previous_version)
    keep |= _active(ctx)["versions"]
    removable = [i["id"] for i in items(ctx) if i["category"] == "models"
                 and int(i["id"].split(":")[1]) not in keep
                 and M.release(ctx, int(i["id"].split(":")[1]))["status"] in ("published", "evaluated", "failed")]
    if not removable:
        return {"removed": [], "freed_bytes": 0, "kept": sorted(keep)}
    # The cleanup refuses anything 'protected' for ordinary storage reasons; retention decides for
    # published (rollback-eligible) versions itself, so remove them directly with the same safety.
    removed, freed = [], 0
    for iid in removable:
        v = int(iid.split(":")[1])
        rel = M.release(ctx, v)
        if v in keep or rel["status"] in ("deployed", "deploying", "uploading", "evaluating", "uploaded"):
            continue
        path = Path(rel["path"]) if rel.get("path") else None
        size = _size(path) if path and path.exists() else 0
        if path:
            shutil.rmtree(path, ignore_errors=True)
        M._set(ctx, v, "failed", path="", error=f"Removed by model retention after v{deployed['version']} was promoted "
               f"(kept: active and previous working model). The record is kept as history ({rel['status']} before).")
        removed.append(v)
        freed += size
    if removed:
        MEM.event(ctx, "storage.retention", f"Kept the active model (v{deployed['version']})"
                  + (f" and the previous working model (v{previous_version})" if previous_version in keep else "")
                  + f"; removed {len(removed)} older version(s), freeing {freed / 1024**2:.1f} MB.",
                  removed=removed, bytes=freed)
    return {"removed": removed, "freed_bytes": freed, "kept": sorted(keep)}
