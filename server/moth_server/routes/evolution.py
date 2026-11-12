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
from pydantic import BaseModel, Field

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
from moth_server import models as _M

router = APIRouter(prefix="/v1/admin/evolution", tags=["evolution"])


def setup(ctx: Ctx) -> None:
    if ctx.db.get_config('genesis_state') is None:
        ctx.db.set_config('genesis_state', {'status': 'not_prepared'})
    try:  # 0.7.0: one public identity (MOTH 0.0.x); renumbers older versions once, weights untouched
        from moth_server.evolution import identity

        identity.migrate(ctx)
    except Exception:  # noqa: BLE001 — never blocks start-up; retried on the next start
        import logging

        logging.getLogger("moth_server").exception("model identity migration failed")
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
            "params_verified": _M.params_verified(r["info"]),
            "deployed_at": r.get("deployed_at"), "method": lin["method"] if lin else None,
            "parent_version": lin["parent_version"] if lin else None}


@router.get("/status")
def status(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    st = EN.state(ctx)
    settings = S.get(ctx)
    deployed = M.deployed(ctx)
    active = MEM.active_cycle(ctx)
    last = active or (MEM.cycles(ctx, 1) or [None])[0]
    ids = None
    if deployed and (deployed['info'] or {}).get('lineage_id'):
        lineage_id = deployed['info']['lineage_id']
        ids = {r['version'] for r in M.list_releases(ctx) if r['info'].get('lineage_id') == lineage_id}
        last = next((c for c in MEM.cycles(ctx, 100) if c['base_version'] in ids), None)
    latest_eval = next((e for e in MEM.experiments(ctx, limit=100) if (ids is None or e['base_version'] in ids)
                        and (e.get("metrics") or {}).get("gates")), None)
    return {
        "settings": settings,
        "state": {"enabled": settings["enabled"], "paused": settings["paused"],
                  "next_cycle_at": st.get("next_cycle_at") or None, "idle_reason": st.get("idle_reason"),
                  "consecutive_failures": st.get("consecutive_failures"), "last_tick": st.get("last_tick")},
        "active_model": _model(ctx, deployed["version"] if deployed else None),
        "rollout": [{**v, "model": _model(ctx, v["version"])} for v in __import__("moth_server.serving",
                                                                                 fromlist=["x"]).loaded_versions(ctx)],
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


@router.get("/growth-diagnostics")
def growth_diagnostics(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution.growth_diagnostics import inspect
    try:
        return inspect(ctx)
    except (ValueError, OSError) as e:
        raise HTTPException(409, f"Growth evidence unavailable: {e}") from None


@router.get("/resources")
def resources(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.routes.system import cpu_percent

    act = C.activity(ctx)
    hw = C.local(ctx)
    hw["cpu_percent"] = cpu_percent(0.2)
    running = [e for e in MEM.experiments(ctx, limit=20) if e["status"] == "running"]
    return {"local": hw, "workers": C.worker_capacity(ctx),
            "inference": {"active_requests": act.active, "requests_per_minute": round(act.per_minute(), 2)},
            "training": {"running": [_exp_summary(ctx, e) for e in running],
                         # finished/paused work plus the time the running experiments have been training so far
                         "compute_hours_24h": round((MEM.compute_seconds_since(ctx, time.time() - 86400) + sum(
                             max(0.0, time.time() - float((e["resources"] or {}).get("started") or time.time()))
                             for e in running if e.get("backend") == "local")) / 3600, 3)}}


class SettingsIn(BaseModel):
    changes: dict[str, Any]


class TrainingStartIn(BaseModel):
    worker_id: int | None = None
    server_cpu: bool = False


class GenesisActivationIn(BaseModel):
    reset_id: str
    confirmation: str
    start_training: bool = False


@router.get('/genesis')
def genesis_status(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution import genesis
    return genesis.status(ctx)


@router.post('/genesis/prepare')
def genesis_prepare(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution import genesis
    try:
        return genesis.prepare(ctx, auth.uid)
    except (ValueError, OSError) as e:
        raise HTTPException(409, str(e)) from None


@router.post('/genesis/activate')
def genesis_activate(body: GenesisActivationIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution import genesis
    try:
        return genesis.activate(ctx, body.reset_id, body.confirmation, auth.uid, body.start_training)
    except (ValueError, OSError, M.ReleaseError) as e:
        raise HTTPException(409, str(e)) from None


@router.post('/genesis/{reset_id}/restore')
def genesis_restore(reset_id: str, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution import genesis
    try:
        return genesis.restore(ctx, reset_id, auth.uid)
    except (ValueError, OSError, M.ReleaseError) as e:
        raise HTTPException(409, str(e)) from None


@router.post("/training/start")
def start_training(body: TrainingStartIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    import json
    from sqlalchemy import select
    from moth_server.db import workers, now
    from moth_server import training as T

    if MEM.active_cycle(ctx):
        raise HTTPException(409, "A cycle is already active; use Pause/Resume or finish it before changing participants")
    base = M.deployed(ctx)
    if not base:
        raise HTTPException(409, "Initialize or import MOTH, then evaluate and deploy its first checkpoint")
    settings = S.get(ctx)
    selected = None
    if not body.server_cpu:
        cfg = base['info'].get('config') or {}
        need = C.estimate_training_memory(int(base['info']['params']), settings['training']['batch_size'],
                                         min(settings['training']['seq_len'], cfg.get('max_seq_len', 256)),
                                         cfg.get('d_model', 512), cfg.get('n_layers', 12))
        rows = ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
        selected = [w['id'] for w in rows if (not w["paused"] or w["user_id"] == auth.uid)
                    and (body.worker_id is None or w['id'] == body.worker_id)
                    and (w.get('last_heartbeat_at') or 0) >= now() - 180
                    and T.fits(json.loads(w['hardware'] or '{}'), {'requirements': {'memory_bytes': need}},
                               json.loads(w['limits'] or '{}'))]
        if not selected:
            raise HTTPException(409, "No selected online worker has enough memory for the configured workload")
        with ctx.db.tx() as c:
            c.execute(workers.update().where(workers.c.id.in_(selected)).values(paused=False))
    S.update(ctx, {'enabled': True, 'paused': False, 'worker_ids': selected,
                   'backends': {'local_cpu': body.server_cpu, 'local_gpu': False, 'workers': not body.server_cpu}})
    EN._set_state(ctx, consecutive_failures=0)
    MEM.event(ctx, 'training.start', 'Owner requested training on ' + ('server CPU' if body.server_cpu else str(selected)), actor=auth.uid)
    EN.wake(ctx)
    return {'requested': True, 'worker_ids': selected, 'server_cpu': body.server_cpu}


class GenesisInitIn(BaseModel):
    size: str = "seed"
    tokenizer: str = "byte"


@router.get("/initialize/options")
def initialize_options(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    """Model sizes and tokenizers a fresh lineage can start from, with real parameter counts and whether
    this deployment can train each one (measured memory, configured backends)."""
    from moth_server.evolution.bootstrap import options

    return options(ctx)


@router.post("/initialize")
def initialize(body: GenesisInitIn | None = None, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution.bootstrap import initialize as init

    body = body or GenesisInitIn()
    try:
        return init(ctx, auth.uid, body.size, body.tokenizer)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from None


@router.post("/initialize/activate")
def activate_initial(body: GenesisInitIn | None = None, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution.bootstrap import activate_initial as activate
    body = body or GenesisInitIn()
    try:
        return activate(ctx, auth.uid, body.size, body.tokenizer)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from None


@router.put("/settings")
def put_settings(body: SettingsIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        s = S.update(ctx, body.changes)
    except S.SettingsError as e:
        raise _bad(e) from None
    MEM.event(ctx, "settings.changed", "Evolution settings changed: " + ", ".join(sorted(body.changes)), actor=auth.uid)
    EN.kick(ctx)
    return s


class CleanupIn(BaseModel):
    items: list[str] = Field(min_length=1, max_length=500)


@router.get("/storage")
def storage_summary(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    """What uses space on MOTH Cloud, what is protected (and why) and what can be removed safely."""
    from moth_server.evolution import storage as ST

    return ST.summary(ctx)


@router.post("/storage/cleanup")
def storage_cleanup(body: CleanupIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution import storage as ST

    return ST.cleanup(ctx, body.items, auth.uid)


@router.get("/autopilot")
def autopilot_status(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    """What MOTH is doing now, what it will do next and the reasons for its recent plan changes."""
    from moth_server.evolution import autopilot as AP

    return AP.status(ctx)


@router.post("/autopilot/start")
def autopilot_start(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    """One click: create a first model if there is none, select trusted data, start continuous evolution."""
    from moth_server.evolution import autopilot as AP

    try:
        return AP.start(ctx, auth.uid)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(409, str(e)) from None


@router.post("/autopilot/pause")
def autopilot_pause(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.evolution import autopilot as AP

    return AP.pause(ctx, auth.uid)


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
    EN.wake(ctx)
    return {"paused": False}


@router.post("/run")
def run_now(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    if (ctx.db.get_config('genesis_state', {}) or {}).get('status') in ('preparing', 'prepared'):
        raise HTTPException(409, 'Finish or cancel the prepared GENESIS reset before resuming training')
    if not M.deployed(ctx):
        raise HTTPException(409, 'Activate or deploy a MOTH baseline before requesting training')
    current = MEM.active_cycle(ctx)
    if current:
        # A deliberate Owner action resumes the same checkpointed cycle; no duplicate cycle.
        S.update(ctx, {'enabled': True, 'paused': False})
        EN._set_state(ctx, consecutive_failures=0)
        EN.wake(ctx)
        return _cycle_summary(ctx, MEM.cycle(ctx, current['id']))
    try:
        cyc = EN.start_cycle(ctx, "manual", auth.uid)
    except EN.EvolutionError as e:
        from moth_server.intelligence import discovery
        if MEM.active_cycle(ctx):
            raise HTTPException(409, str(e)) from None
        preparation = discovery.ensure_data(ctx)
        if preparation.get('status') in ('preparing', 'queued', 'running'):
            EN._set_state(ctx, manual_cycle_requested=True)
            S.update(ctx, {'enabled': True, 'paused': False})
            EN.wake(ctx)
            return {'requested': True, 'status': 'preparing_data', 'preparation': preparation}
        raise HTTPException(409, str(e)) from None
    S.update(ctx, {'enabled': True, 'paused': False})
    EN._set_state(ctx, consecutive_failures=0)
    EN._set_state(ctx, manual_cycle_requested=False)
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


@router.post("/experiments/{eid}/approve")
def approve_experiment(eid: int, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    """Approve a parameter expansion that is above the automatic threshold (a major architecture change)."""
    e = MEM.experiment(ctx, eid)
    if not e:
        raise HTTPException(404, "unknown experiment")
    cfg = e["config"] or {}
    if not cfg.get("requires_approval") or e["status"] != "planned":
        raise HTTPException(409, "this experiment does not wait for approval")
    cfg["approved_by"] = auth.uid
    MEM.update_experiment(ctx, eid, config=cfg)
    g = cfg.get("grow") or {}
    MEM.event(ctx, "experiment.approved", f"The Owner approved expansion experiment #{eid} "
              f"({g.get('params_before', 0) / 1e6:.1f}M → {g.get('params_after', 0) / 1e6:.1f}M parameters)",
              cycle_id=e["cycle_id"], experiment_id=eid, actor=auth.uid)
    EN.wake(ctx)
    return {"ok": True}


@router.get("/contributions")
def contributions(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    """Who is training the current (or latest) distributed experiment, and what each participant did."""
    import json as _json

    from sqlalchemy import select

    from moth_server.db import training_jobs, workers

    ws = {w["id"]: w for w in ctx.db.all(select(workers))}

    def who(wid):
        w = ws.get(int(wid)) if wid not in (None, "None") else None
        if not w:
            return {"worker_id": wid, "name": "unknown"}
        hw = _json.loads(w["hardware"] or "{}")
        return {"worker_id": w["id"], "name": w["name"], "compute": hw.get("compute"),
                "this_app": hw.get("client") == "moth-code", "online": w["status"] == "online",
                "gflops": (hw.get("benchmark") or {}).get("gflops")}

    exp = next((e for e in MEM.experiments(ctx, limit=50) if e.get("backend") == "distributed"), None)
    out = {"experiment": None, "workers": [{**who(w["id"]), "verified_jobs": w["verified_jobs"],
                                            "trained_tokens": w["trained_tokens"], "failed_jobs": w["failed_jobs"],
                                            "revoked": w["revoked_at"] is not None} for w in ws.values()]}
    if exp is None:
        return out
    st = (exp["resources"] or {}).get("distributed") or {}
    per: dict[str, dict] = {}
    for h in st.get("history", []):
        for wid, tok in (h.get("contributors") or {}).items():
            p = per.setdefault(str(wid), {**who(wid), "tokens": 0, "rounds": 0})
            p["tokens"] += tok
            p["rounds"] += 1
    jobs = []
    for i, jid in ((st.get("jobs") or {}).get(str(st.get("round")), {}) or {}).items():
        j = ctx.db.one(select(training_jobs).where(training_jobs.c.id == jid))
        if j:
            jobs.append({"shard": int(i), "status": j["status"], "progress": j["progress"],
                         "worker": who(j["worker_id"]) if j["worker_id"] else None})
    out["experiment"] = {"id": exp["id"], "cycle_id": exp["cycle_id"], "status": exp["status"],
                         "round": st.get("round"), "rounds": st.get("rounds"), "shards": st.get("shards"),
                         "local_steps": st.get("local_steps"), "history": st.get("history", []),
                         "contributors": sorted(per.values(), key=lambda p: -p["tokens"]), "current_jobs": jobs}
    return out


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
                    "params_verified": _M.params_verified(r["info"]),
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
    EN.wake(ctx)  # new data: plan a cycle now
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


class GrowthRequestIn(BaseModel):
    add_layers: int = Field(ge=0, le=64)
    ffn_hidden: int = Field(ge=64, le=65536)


@router.post("/growth-request")
def growth_request(body: GrowthRequestIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    """Ask for one growth experiment in the next cycle. It stays a candidate: evaluated against the deployed
    model on held-out benchmarks and discarded unless it passes; the deployed model is never modified."""
    from moth_server.evolution.growth_diagnostics import inspect

    d = inspect(ctx)
    opt = next((o for o in d.get("options", []) if o["add_layers"] == body.add_layers and o["ffn_hidden"] == body.ffn_hidden), None)
    if opt is None:
        raise HTTPException(409, "That expansion is not valid for the deployed model or exceeds the parameter budget.")
    ctx.db.set_config("growth_request", {**body.model_dump(), "params": opt["params"], "requested_by": auth.uid, "at": time.time()})
    MEM.event(ctx, "growth.requested", f"Owner requested a growth experiment to {opt['params']:,} parameters", actor=auth.uid)
    return {"request": ctx.db.get_config("growth_request")}


@router.delete("/growth-request")
def growth_request_cancel(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    ctx.db.set_config("growth_request", None)
    return {"request": None}


class NativeResetPreviewIn(BaseModel):
    include_managed_backups: bool = False

class NativeResetExecuteIn(BaseModel):
    reset_id: str
    confirmation: str
    backup_confirmation: str = ""

@router.get('/native-reset')
def native_reset_status(auth:Auth=Depends(require_owner),ctx:Ctx=Depends(get_ctx)):
    from moth_server.evolution.native_reset import status
    return status(ctx)

@router.post('/native-reset/preview')
def native_reset_preview(body:NativeResetPreviewIn,auth:Auth=Depends(owner_reauthed),ctx:Ctx=Depends(get_ctx)):
    from moth_server.evolution.native_reset import preview
    try:return preview(ctx,auth.uid,body.include_managed_backups)
    except ValueError as error:raise _bad(error) from None

@router.post('/native-reset/execute')
def native_reset_execute(body:NativeResetExecuteIn,auth:Auth=Depends(owner_reauthed),ctx:Ctx=Depends(get_ctx)):
    from moth_server.evolution.native_reset import execute
    try:return execute(ctx,body.reset_id,body.confirmation,auth.uid,body.backup_confirmation)
    except ValueError as error:raise _bad(error) from None
