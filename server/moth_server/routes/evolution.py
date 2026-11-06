"""Owner API for model evolution (``/v1/admin/evolution``), used by the Evolution dashboard.

Reading requires the Owner; actions that change training data permissions, settings, or the serving
model also require a recent sign-in (HTTP 428 asks for the password again).
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from moth_server import models as M
from moth_server.context import Ctx, get_ctx
from moth_server.deps import Auth, owner_reauthed, require_owner
from moth_server.evolution import backends as B
from moth_server.evolution import compute as C
from moth_server.evolution import datasets as DS
from moth_server.evolution import engine as EN
from moth_server.evolution import evaluation as EV
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S

router = APIRouter(prefix="/v1/admin/evolution", tags=["evolution"])


def setup(ctx: Ctx) -> None:
    if not ctx.extras.get("disable_background"):
        EN.start_background(ctx)


def _bad(e: Exception) -> HTTPException:
    return HTTPException(422, str(e))


def _exp_summary(ctx: Ctx, e: dict) -> dict[str, Any]:
    m = e.get("metrics") or {}
    prog = m.get("progress") or {}
    if e["status"] == "running" and e.get("backend") == "local":
        prog = B.progress(ctx, e)
    ds = DS.get(ctx, e["dataset_id"])
    return {"id": e["id"], "cycle_id": e["cycle_id"], "status": e["status"], "backend": e.get("backend"),
            "rationale": e.get("rationale"), "dataset": {"id": e["dataset_id"], "name": ds["name"] if ds else None},
            "config": {k: (e["config"] or {}).get(k) for k in ("lr", "steps", "batch_size", "seq_len", "seed", "method")},
            "progress": prog, "candidate_version": e.get("candidate_version"),
            "primary_improvement": m.get("primary_improvement"), "error": e.get("error"),
            "compute_seconds": e.get("compute_seconds"), "worker_id": e.get("worker_id"), "job_id": e.get("job_id"),
            "created_at": e["created_at"], "started_at": e.get("started_at"), "finished_at": e.get("finished_at")}


def _cycle_summary(ctx: Ctx, c: dict | None) -> dict | None:
    if not c:
        return None
    exps = sorted(MEM.experiments(ctx, c["id"]), key=lambda e: e["id"])
    return {**{k: c[k] for k in ("id", "status", "trigger", "base_version", "candidate_version", "error", "created_at",
                                 "started_at", "updated_at", "finished_at")},
            "result": c.get("result") or {}, "plan": {k: (c.get("plan") or {}).get(k) for k in ("notes", "weaknesses",
                                                                                                  "skipped")},
            "experiments": [_exp_summary(ctx, e) for e in exps]}


def _model(ctx: Ctx, version: int | None) -> dict | None:
    if not version:
        return None
    try:
        r = M.release(ctx, version)
    except M.ReleaseError:
        return None
    lin = next((x for x in MEM.lineage(ctx) if x["version"] == version), None)
    return {"version": r["version"], "name": r["name"], "status": r["status"], "params": r["info"].get("params"),
            "deployed_at": r.get("deployed_at"), "method": lin["method"] if lin else None,
            "parent_version": lin["parent_version"] if lin else None}


@router.get("/status")
def status(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    st = EN.state(ctx)
    settings = S.get(ctx)
    deployed = M.deployed(ctx)
    active = MEM.active_cycle(ctx)
    last = active or (MEM.cycles(ctx, 1) or [None])[0]
    latest_eval = next((e for e in MEM.experiments(ctx, limit=20) if (e.get("metrics") or {}).get("gates")), None)
    return {
        "settings": settings,
        "state": {"enabled": settings["enabled"], "paused": settings["paused"],
                  "next_cycle_at": st.get("next_cycle_at") or None, "idle_reason": st.get("idle_reason"),
                  "consecutive_failures": st.get("consecutive_failures"), "last_tick": st.get("last_tick")},
        "active_model": _model(ctx, deployed["version"] if deployed else None),
        "stable_model": _model(ctx, st.get("stable_version") or (deployed["version"] if deployed else None)),
        "cycle": _cycle_summary(ctx, last),
        "comparison": {"experiment_id": latest_eval["id"], "candidate_version": latest_eval.get("candidate_version"),
                       "base_version": latest_eval["base_version"], "status": latest_eval["status"],
                       "gates": latest_eval["metrics"]["gates"],
                       "primary_improvement": latest_eval["metrics"].get("primary_improvement")} if latest_eval else None,
        "warnings": MEM.events(ctx, limit=10, level="error") + MEM.events(ctx, limit=10, level="warning"),
        "recent": MEM.events(ctx, limit=15),
        "datasets": {"approved": len(DS.approved(ctx)), "pending": sum(1 for d in DS.all_(ctx) if d["status"] == "pending")},
    }


@router.get("/resources")
def resources(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.routes.admin import flags
    from moth_server.routes.system import cpu_percent

    act = C.activity(ctx)
    hw = C.local(ctx)
    hw["cpu_percent"] = cpu_percent(0.2)
    running = [e for e in MEM.experiments(ctx, limit=20) if e["status"] == "running"]
    return {"local": hw, "workers": C.worker_capacity(ctx, bool(flags(ctx).get("allow_cpu_workers"))),
            "inference": {"active_requests": act.active, "requests_per_minute": round(act.per_minute(), 2)},
            "training": {"running": [_exp_summary(ctx, e) for e in running],
                         # finished/paused work plus the time the running experiments have been training so far
                         "compute_hours_24h": round((MEM.compute_seconds_since(ctx, time.time() - 86400) + sum(
                             max(0.0, time.time() - float((e["resources"] or {}).get("started") or time.time()))
                             for e in running if e.get("backend") == "local")) / 3600, 3)}}


class SettingsIn(BaseModel):
    changes: dict[str, Any]


@router.put("/settings")
def put_settings(body: SettingsIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        s = S.update(ctx, body.changes)
    except S.SettingsError as e:
        raise _bad(e) from None
    MEM.event(ctx, "settings.changed", "Evolution settings changed: " + ", ".join(sorted(body.changes)), actor=auth.uid)
    EN.kick(ctx)
    return s


@router.post("/pause")
def pause(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    S.update(ctx, {"paused": True})
    MEM.event(ctx, "engine.paused", "Evolution paused by the Owner", actor=auth.uid)
    EN.kick(ctx)
    return {"paused": True}


@router.post("/resume")
def resume(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    S.update(ctx, {"paused": False})
    EN._set_state(ctx, consecutive_failures=0)
    MEM.event(ctx, "engine.resumed", "Evolution resumed by the Owner", actor=auth.uid)
    EN.kick(ctx)
    return {"paused": False}


@router.post("/run")
def run_now(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        cyc = EN.start_cycle(ctx, "manual", auth.uid)
    except EN.EvolutionError as e:
        raise HTTPException(409, str(e)) from None
    EN.kick(ctx)
    return _cycle_summary(ctx, cyc)


@router.post("/cancel")
def cancel(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return _cycle_summary(ctx, EN.cancel_cycle(ctx, auth.uid))
    except EN.EvolutionError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/cycles")
def cycles(limit: int = 30, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return [_cycle_summary(ctx, c) for c in MEM.cycles(ctx, min(limit, 200))]


@router.get("/cycles/{cid}")
def cycle(cid: int, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    c = MEM.cycle(ctx, cid)
    if not c:
        raise HTTPException(404, "unknown cycle")
    return {**_cycle_summary(ctx, c), "events": MEM.events(ctx, 200, cycle_id=cid)}


@router.get("/experiments/{eid}")
def experiment(eid: int, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    e = MEM.experiment(ctx, eid)
    if not e:
        raise HTTPException(404, "unknown experiment")
    return {**_exp_summary(ctx, e), "config": e["config"], "config_hash": e["config_hash"], "metrics": e["metrics"],
            "resources": {k: v for k, v in (e["resources"] or {}).items() if k != "spec"},
            "events": MEM.events(ctx, 100, experiment_id=eid)}


@router.get("/experiments/{eid}/log")
def experiment_log(eid: int, lines: int = 300, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    e = MEM.experiment(ctx, eid)
    if not e:
        raise HTTPException(404, "unknown experiment")
    return {"lines": B.log_tail(ctx, e, min(lines, 2000))}


@router.get("/events")
def events(limit: int = 100, level: str | None = None, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return MEM.events(ctx, min(limit, 1000), level=level)


@router.get("/versions")
def versions(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    """Model version history with lineage, scores and rollback eligibility."""
    deployed = M.deployed(ctx)
    fp = deployed["info"].get("tokenizer_fingerprint") if deployed else None
    lin = {x["version"]: x for x in MEM.lineage(ctx)}
    out = []
    for r in M.list_releases(ctx):
        reps = {x["suite"]: x["metrics"] for x in MEM.reports_for(ctx, r["version"])}
        out.append({"version": r["version"], "name": r["name"], "status": r["status"], "created_at": r["created_at"],
                    "deployed_at": r.get("deployed_at"), "params": r["info"].get("params"),
                    "method": (lin.get(r["version"]) or {}).get("method"),
                    "parent_version": (lin.get(r["version"]) or {}).get("parent_version"),
                    "cycle_id": (lin.get(r["version"]) or {}).get("cycle_id"),
                    "score": ((r.get("evaluation") or {}).get("score") or {}).get("value"),
                    "suites": {k: {"value": v.get("value"), "ok": v.get("ok")} for k, v in reps.items()
                               if k != "performance"},
                    "error": r.get("error"),
                    "can_rollback": r["status"] == "published" and (not fp or r["info"].get("tokenizer_fingerprint") == fp)
                    and (not deployed or r["version"] != deployed["version"])})
    return {"deployed": deployed["version"] if deployed else None, "versions": out}


class RollbackIn(BaseModel):
    version: int


@router.post("/rollback")
def rollback(body: RollbackIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        rel = EN.rollback_to(ctx, body.version, auth.uid)
    except (EN.EvolutionError, M.ReleaseError) as e:
        raise HTTPException(409, str(e)) from None
    return {"deployed": rel["version"]}


# ---- training data -----------------------------------------------------------------------------------
@router.get("/datasets")
def list_datasets(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    deployed = M.deployed(ctx)
    fp = deployed["info"].get("tokenizer_fingerprint") if deployed else None
    return [{**DS.public(d), "compatible": fp is None or d["tokenizer_fingerprint"] == fp} for d in DS.all_(ctx)]


@router.post("/datasets")
async def upload_dataset(name: str = Form(..., max_length=128), license: str = Form(..., max_length=500),
                         tags: str = Form(""), contains_user_data: bool = Form(False), file: UploadFile = File(...),
                         auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    deployed = M.deployed(ctx)
    if not deployed:
        raise HTTPException(409, "deploy a model first: training data is tokenized with the deployed model's tokenizer")
    with tempfile.NamedTemporaryFile(delete=False, dir=DS.root(ctx)) as tmp:
        size = 0
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > DS.MAX_UPLOAD:
                raise HTTPException(413, f"uploads are limited to {DS.MAX_UPLOAD // 1024**2} MB")
            tmp.write(chunk)
    try:
        d = DS.create_from_files(ctx, Path(tmp.name), file.filename or "data.txt", name, license,
                                 [t for t in tags.split(",")], contains_user_data, Path(deployed["path"]), auth.uid)
    except DS.DatasetError as e:
        raise _bad(e) from None
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    return DS.public(d)


class RegisterIn(BaseModel):
    path: str
    name: str
    tags: list[str] = []
    contains_user_data: bool = False


@router.post("/datasets/register")
def register_dataset(body: RegisterIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    """A dataset prepared on the server (``moth prepare``); the path must be inside MOTH's data folder."""
    p = Path(body.path).resolve()
    data = ctx.settings.data_dir.resolve()
    if data not in p.parents:
        raise HTTPException(422, "the dataset must be inside MOTH Cloud's data folder")
    try:
        return DS.public(DS.register_prepared(ctx, p, body.name, body.tags, body.contains_user_data, auth.uid))
    except DS.DatasetError as e:
        raise _bad(e) from None


class ApproveIn(BaseModel):
    user_data_permission: bool = False


@router.post("/datasets/{did}/approve")
def approve_dataset(did: int, body: ApproveIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        d = DS.approve(ctx, did, auth.uid, body.user_data_permission)
    except DS.DatasetError as e:
        raise _bad(e) from None
    MEM.event(ctx, "data.approved", f"Training dataset #{did} ({d['name']}) was approved for training", actor=auth.uid)
    EN._set_state(ctx, next_cycle_at=0)  # new data: plan a cycle at the next tick
    EN.kick(ctx)
    return DS.public(d)


@router.post("/datasets/{did}/revoke")
def revoke_dataset(did: int, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        d = DS.revoke(ctx, did, auth.uid)
    except DS.DatasetError as e:
        raise _bad(e) from None
    stopped = EN.dataset_revoked(ctx, did)
    MEM.event(ctx, "data.revoked", f"Training dataset #{did} ({d['name']}) will no longer be used"
              + (f"; {stopped} unfinished experiment(s) using it were cancelled" if stopped else ""), actor=auth.uid)
    EN.kick(ctx)
    return {**DS.public(d), "experiments_cancelled": stopped}


@router.get("/suites")
def suites(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return [{k: v for k, v in t.items() if k != "path"} for t in EV.task_suites(ctx)]


@router.post("/suites")
async def upload_suite(name: str = Form(..., max_length=80), capability: str = Form(..., max_length=32),
                       file: UploadFile = File(...), auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    data = await file.read(16 * 1024**2 + 1)
    if len(data) > 16 * 1024**2:
        raise HTTPException(413, "task suites are limited to 16 MB")
    try:
        return EV.add_task_suite(ctx, name, capability, data)
    except (ValueError, UnicodeDecodeError) as e:
        raise _bad(e) from None
