"""Training network API: user enrollment/management and the worker-only API.

Worker endpoints accept only worker credentials (``mw_…``); user sessions cannot call them,
and worker credentials cannot call any user endpoint (they are not sessions).
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from moth_server import training as T
from moth_server.audit import audit
from moth_server.context import public_url
from moth_server.context import Ctx, get_ctx
from moth_server.db import now, training_jobs, workers
from moth_server.deps import Auth, bearer, current_auth
from moth_server.routes.admin import flags

router = APIRouter(tags=["training"])


class EnrollmentIn(BaseModel):
    kind: Literal["personal", "cloud"] = "personal"
    name: str | None = Field(default=None, max_length=64)
    referral_code: str | None = Field(default=None, max_length=16)


class LimitsIn(BaseModel):
    gpu_memory_fraction: float | None = Field(default=None, ge=0.1, le=0.95)
    duty_cycle: float | None = Field(default=None, ge=0.1, le=1.0)
    max_hours_per_day: float | None = Field(default=None, ge=0.5, le=24)
    cpu_threads: int | None = Field(default=None, ge=1, le=256)  # CPU workers: threads used for training


class WorkerEnrollIn(BaseModel):
    token: str = Field(max_length=200)
    hardware: dict = {}
    version: str | None = None


class TrainingMetrics(BaseModel):
    step: int = Field(ge=0)
    tokens: int = Field(ge=0)
    train_loss: float | None = Field(default=None, allow_inf_nan=False)
    checkpoint_step: int | None = Field(default=None, ge=0)


class HeartbeatIn(BaseModel):
    hardware: dict | None = None
    job_id: int | None = None
    progress: float | None = None
    version: str | None = Field(default=None, max_length=32)
    metrics: TrainingMetrics | None = None
    reset_ack: int | None = Field(default=None,ge=0)
    reset_retained: int = Field(default=0,ge=0,le=1000000)


class ProgressIn(BaseModel):
    progress: float = Field(ge=0, le=1)
    message: str | None = Field(default=None, max_length=500)


class FailIn(BaseModel):
    error: str = Field(max_length=2000)


def worker_release(ctx: Ctx) -> dict | None:
    """The newest MOTH Worker bundle this server can hand out: one relayed by the update agent from a
    signed server release (``releases``), else one published by hand with ``moth-server worker-release``."""
    from moth.model.registry import sha256_file

    from moth_server import compat
    from moth_server import releases as R
    from moth_server.db import software_releases

    rows = ctx.db.all(select(software_releases).where(software_releases.c.component == "worker",
                                                      software_releases.c.channel == "stable"))
    rows.sort(key=lambda r: compat.parse_version(r["version"]), reverse=True)
    for r in rows:
        f = R.files_ready(ctx, "worker", r["version"])
        if f:
            return {"version": r["version"], "file": f["file"], "sha256": f["sha256"], "source": "release",
                    "url": f"{public_url(ctx)}/downloads/worker/{f['file']}"}
    m = ctx.settings.storage_dir / "worker" / "manifest.json"
    if not m.exists():
        return None
    data = json.loads(m.read_text())
    path = ctx.settings.storage_dir / "worker" / data["file"]
    if not path.exists():
        return None
    return {**data, "sha256": data.get("sha256") or sha256_file(path), "source": "manual",
            "url": f"{public_url(ctx)}/downloads/worker/{data['file']}"}


def install_command(ctx: Ctx, release: dict, token: str) -> str:
    """Linux and macOS: download, verify the pinned SHA-256, unpack, install (one command)."""
    f = shlex.quote(release["file"])
    d = shlex.quote(release["file"].removesuffix(".tar.gz"))
    check = f"'{release['sha256']}  {release['file']}'"
    return (f"cd \"$(mktemp -d)\" && curl -fsSLO {shlex.quote(release['url'])} && "
            f"{{ echo {check} | sha256sum -c - 2>/dev/null || echo {check} | shasum -a 256 -c -; }} && "
            f"tar xzf {f} && ./{d}/install.sh --server {shlex.quote(public_url(ctx))} --token {shlex.quote(token)}")


def windows_command(ctx: Ctx, release: dict, token: str) -> str:
    """Windows 10/11 PowerShell: the same verified download, then install.ps1 (no administrator needed)."""
    def q(v: str) -> str:
        return "'" + v.replace("'", "''") + "'"
    d = release["file"].removesuffix(".tar.gz")
    return ("$ErrorActionPreference='Stop'; $d=Join-Path $env:TEMP ('moth-worker-'+[guid]::NewGuid()); "
            "New-Item -ItemType Directory $d | Out-Null; Set-Location $d; "
            f"Invoke-WebRequest -UseBasicParsing {q(release['url'])} -OutFile {q(release['file'])}; "
            f"if ((Get-FileHash {q(release['file'])} -Algorithm SHA256).Hash -ne {q(release['sha256'].upper())}) "
            "{ throw 'The MOTH Worker download failed verification. Nothing was installed.' }; "
            f"tar -xzf {q(release['file'])}; "
            f"& (Join-Path $d {q(d + '/install.ps1')}) -Server {q(public_url(ctx))} -Token {q(token)}")


# ---- users -------------------------------------------------------------------------------------
@router.post("/v1/training/enrollments")
def new_enrollment(body: EnrollmentIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    if not flags(ctx).get("training_enrollment_open"):
        raise HTTPException(503, "Training enrollment is currently closed.")
    if auth.user["email_verified_at"] is None:
        raise HTTPException(403, "Verify your email address first.")
    from moth_server.routes.auth import limit

    limit(ctx, f"enroll:user:{auth.uid}", 10, 3600)
    if body.kind == "cloud" and not auth.is_owner:
        raise HTTPException(403, "Only the Owner may authorize cloud infrastructure workers")
    token = T.create_enrollment(ctx, auth.user, body.name, body.referral_code, body.kind)
    release = worker_release(ctx)
    return {
        "token": token, "expires_at": now() + T.ENROLL_TTL, "single_use": True,
        "release": release,
        "command": install_command(ctx, release, token) if release else None,
        "windows_command": windows_command(ctx, release, token) if release else None,
        "manual_command": f"moth-worker enroll --server {public_url(ctx)} --token {token}",
        "note": None if release else "No MOTH Worker release is published on this server yet; install from source "
                                     "(see docs/WORKER.md) and run the manual command.",
    }


def own_worker(ctx: Ctx, auth: Auth, wid: int) -> dict:
    w = ctx.db.one(select(workers).where(workers.c.id == wid))
    if not w or (w["user_id"] != auth.uid and not auth.is_owner):
        raise HTTPException(404, "Worker not found.")
    return w


@router.get("/v1/training/workers")
def my_workers(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    T.requeue_expired(ctx)
    rows = ctx.db.all(select(workers).where(workers.c.user_id == auth.uid,
                                          workers.c.revoked_at.is_(None)).order_by(workers.c.id))
    jobs = T.worker_jobs(ctx, [w["id"] for w in rows])
    coord = T.coordinator(ctx)
    return {"workers": [T.public_worker(w) for w in rows], "jobs": jobs,
            "network": {"configured": coord is not None,
                        "round": coord.config["round"] if coord else None,
                        "checkpoint_version": coord.config["version"] if coord else None}}


@router.post("/v1/training/workers/{wid}/{action}")
def control_worker(wid: int, action: str, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    w = own_worker(ctx, auth, wid)
    if w["revoked_at"]:
        raise HTTPException(409, "This worker was revoked.")
    if action == "resume" and w["user_id"] != auth.uid:
        raise HTTPException(403, "Only the enrolled account may resume this device.")
    values = {"pause": {"paused": True}, "resume": {"paused": False}, "stop": {"paused": True},
              "revoke": {"revoked_at": now(), "status": "revoked", "token_hash": f"revoked-{wid}-{now()}"}}.get(action)
    if values is None:
        raise HTTPException(404, "Unknown action.")
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == wid).values(**values))
        if action in ("revoke", "stop"):  # release its jobs back to the queue
            c.execute(training_jobs.update().where(training_jobs.c.worker_id == wid, training_jobs.c.status == "leased")
                      .values(status="queued", worker_id=None, lease_expires_at=None, updated_at=now()))
        audit(ctx.db, f"training.worker_{action}", auth.uid, f"worker:{wid}", conn=c)
    return T.public_worker(ctx.db.one(select(workers).where(workers.c.id == wid)))


@router.put("/v1/training/workers/{wid}/limits")
def set_limits(wid: int, body: LimitsIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    w = own_worker(ctx, auth, wid)
    if w["user_id"] != auth.uid:
        raise HTTPException(403, "Only the enrolled account may change device resource limits")
    limits = {**json.loads(w["limits"] or "{}"), **body.model_dump(exclude_none=True)}
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == wid).values(limits=json.dumps(limits)))
    return T.public_worker(ctx.db.one(select(workers).where(workers.c.id == wid)))


@router.get("/downloads/worker/{name}", include_in_schema=False)
def download_worker(name: str, ctx: Ctx = Depends(get_ctx)):
    from moth_server import releases as R

    rel = worker_release(ctx)
    if not rel or name != rel["file"]:
        raise HTTPException(404, "Not found.")
    path = (R.served_file(ctx, "worker", rel["version"], name) if rel["source"] == "release"
            else ctx.settings.storage_dir / "worker" / name)
    if not path or not path.exists():
        raise HTTPException(404, "Not found.")
    return FileResponse(path, media_type="application/gzip", filename=name)


# ---- workers (worker credentials only) ---------------------------------------------------------
def current_worker(request: Request, ctx: Ctx = Depends(get_ctx)) -> dict:
    w = T.worker_by_token(ctx, bearer(request))
    if not w:
        raise HTTPException(401, "Invalid or revoked worker credential.")
    return w


@router.post("/v1/worker/enroll")
def worker_enroll(body: WorkerEnrollIn, request: Request, ctx: Ctx = Depends(get_ctx)):
    from moth_server.context import client_ip
    from moth_server.routes.auth import limit

    limit(ctx, f"worker-enroll:ip:{client_ip(request)}", 20, 3600)
    try:
        wid, secret = T.enroll_worker(ctx, body.token, body.hardware, body.version)
    except T.TrainingError as e:
        raise HTTPException(400, str(e)) from None
    return {"worker_id": wid, "worker_token": secret, "heartbeat_seconds": 30}


@router.post("/v1/worker/leave")
def worker_leave(w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    T.leave(ctx, w)
    return {"ok": True}


@router.post("/v1/worker/heartbeat")
def worker_heartbeat(body: HeartbeatIn, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    return T.heartbeat(ctx, w, body.hardware, body.job_id, body.progress, body.version,
                       body.metrics.model_dump() if body.metrics else None,body.reset_ack,body.reset_retained)


@router.post("/v1/worker/jobs/claim")
def worker_claim(w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    job = T.claim_job(ctx, w, allow_cpu=bool(flags(ctx).get("allow_cpu_workers")))
    return job or Response(status_code=204)


def _job(ctx: Ctx, w: dict, job_id: int) -> dict:
    try:
        return T.leased_job(ctx, w, job_id)
    except T.TrainingError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/v1/worker/jobs/{job_id}/weights")
def job_weights(job_id: int, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    j = _job(ctx, w, job_id)
    spec = json.loads(j["spec"])
    if j["kind"] == "dist_shard":
        from moth_server.evolution.distributed import job_files as dist_files

        return FileResponse(dist_files(ctx, spec)[0], media_type="application/octet-stream")
    if j["kind"] == "eval_loss":
        from moth_server.evolution.remote_eval import files as eval_files

        return FileResponse(eval_files(ctx, spec)[0], media_type="application/octet-stream")
    if j["kind"] == "prep_tokenize":
        from moth_server.intelligence.distributed_prep import files as prep_files

        return FileResponse(prep_files(ctx, spec)[0], media_type="application/octet-stream")
    if j["kind"] == "evolve_train":
        from moth_server.evolution.backends import job_files

        return FileResponse(job_files(ctx, spec)[0], media_type="application/octet-stream")
    p = T.coordinator(ctx).version_dir(spec["model_version"]) / "model.pt"
    return FileResponse(p, media_type="application/octet-stream")


@router.get("/v1/worker/jobs/{job_id}/shard")
def job_shard(job_id: int, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    j = _job(ctx, w, job_id)
    spec = json.loads(j["spec"])
    if j["kind"] == "dist_shard":
        from moth_server.evolution.distributed import job_files as dist_files

        return FileResponse(dist_files(ctx, spec)[1], media_type="application/octet-stream")
    if j["kind"] == "eval_loss":
        from moth_server.evolution.remote_eval import files as eval_files

        return FileResponse(eval_files(ctx, spec)[1], media_type="application/octet-stream")
    if j["kind"] == "prep_tokenize":
        from moth_server.intelligence.distributed_prep import files as prep_files

        return FileResponse(prep_files(ctx, spec)[1], media_type="application/octet-stream")
    if j["kind"] == "evolve_train":
        from moth_server.evolution.backends import job_files

        return FileResponse(job_files(ctx, spec)[1], media_type="application/octet-stream")
    p = T.coordinator_root(ctx) / "shards" / f"{spec['shard_id']}.bin"
    return FileResponse(p, media_type="application/octet-stream")


@router.get("/v1/worker/jobs/{job_id}/mask")
def job_mask(job_id: int, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    """The loss mask of an evolution job's shard (1 = learn this token)."""
    j = _job(ctx, w, job_id)
    spec = json.loads(j["spec"])
    if j["kind"] != "evolve_train" or not spec.get("mask_sha256"):
        raise HTTPException(404, "this job has no loss mask")
    from moth_server.evolution.backends import job_mask as mask_path

    return FileResponse(mask_path(ctx, spec), media_type="application/octet-stream")


@router.post("/v1/worker/jobs/{job_id}/progress")
def job_progress(job_id: int, body: ProgressIn, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    _job(ctx, w, job_id)
    T.extend_lease(ctx, w, job_id, body.progress)
    return {"paused": bool(w["paused"])}


@router.post("/v1/worker/jobs/{job_id}/result")
async def job_result(job_id: int, request: Request, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    _job(ctx, w, job_id)
    try:
        meta = json.loads(request.headers.get("x-moth-contribution", ""))
    except json.JSONDecodeError:
        raise HTTPException(400, "missing contribution metadata") from None
    payload = await request.body()
    if len(payload) > 4 * 1024**3:
        raise HTTPException(413, "update too large")
    try:
        result = T.submit_result(ctx, w, job_id, meta, payload)
    except T.TrainingError as e:
        raise HTTPException(409, str(e)) from None
    return {k: v for k, v in result.items() if k != "aggregated"} | {"aggregated": bool(result.get("aggregated"))}


@router.post("/v1/worker/jobs/{job_id}/fail")
def job_fail(job_id: int, body: FailIn, w: dict = Depends(current_worker), ctx: Ctx = Depends(get_ctx)):
    _job(ctx, w, job_id)
    T.fail_job(ctx, w, job_id, body.error)
    return {"ok": True}
