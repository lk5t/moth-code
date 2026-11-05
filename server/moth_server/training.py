"""Central training coordination: enrollment, workers, job leases, verified contributions.

Training rounds use MOTH's existing community coordinator (``moth.community.coordinator``)
for job specs, checkpoint versions, data shards, contribution validation (checksums, tensor
shapes, finiteness, update size, held-out probe loss) and token-weighted aggregation.

Job lifecycle: ``queued`` → ``leased`` (to one worker, lease renewed by heartbeats and
progress) → ``completed`` (contribution verified and accepted) or ``failed``. Expired leases
return the job to the queue (failure recovery); jobs fail permanently after ``max_attempts``.
Only verified, accepted contributions count towards a worker's record and rewards.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import and_, func, or_, select

from moth_server.audit import audit
from moth_server.context import Ctx
from moth_server.db import enrollment_tokens, now, training_jobs, workers
from moth_server.hooks import run_hook
from moth_server.security import new_token, token_hash

ENROLL_TTL = 15 * 60
LEASE_SECONDS = 10 * 60
OFFLINE_AFTER = 3 * 60
MAX_QUEUED = 8
WORKER_TOKEN_PREFIX = "mw_"


class TrainingError(ValueError):
    pass


def coordinator_root(ctx: Ctx) -> Path:
    return ctx.settings.data_dir / "coordinator"


def coordinator(ctx: Ctx):
    """The training coordinator, if the Owner initialised one (``moth-server training init``)."""
    coord = ctx.extras.get("coordinator")
    if coord is None and (coordinator_root(ctx) / "config.json").exists():
        from moth.community.coordinator import Coordinator

        coord = Coordinator(coordinator_root(ctx))
        ctx.extras["coordinator"] = coord
    return coord


# ---- enrollment ------------------------------------------------------------------------------
def create_enrollment(ctx: Ctx, user: dict, name: str | None, referral_code: str | None) -> str:
    token = "me_" + new_token(24)
    t = now()
    with ctx.db.tx() as c:
        c.execute(enrollment_tokens.insert().values(user_id=user["id"], token_hash=token_hash(token),
                                                    referral_code=(referral_code or "").strip().upper() or None,
                                                    worker_name=(name or "")[:64] or None, created_at=t,
                                                    expires_at=t + ENROLL_TTL))
        audit(ctx.db, "training.enrollment_created", user["id"], f"user:{user['id']}", conn=c)
    return token


def enroll_worker(ctx: Ctx, token: str, hardware: dict[str, Any], version: str | None) -> tuple[int, str]:
    """Exchange a single-use enrollment token for a long-lived worker credential."""
    from moth_server.referrals import find_referrer

    t = now()
    with ctx.db.tx() as c:
        row = c.execute(select(enrollment_tokens).where(enrollment_tokens.c.token_hash == token_hash(token))
                        ).mappings().first()
        if not row or row["used_at"] is not None or row["expires_at"] < t:
            raise TrainingError("This enrollment command is invalid, already used, or expired. Generate a new one.")
        res = c.execute(enrollment_tokens.update().where(enrollment_tokens.c.id == row["id"],
                                                         enrollment_tokens.c.used_at.is_(None)).values(used_at=t))
        if res.rowcount != 1:
            raise TrainingError("This enrollment command was already used.")
        referrer = find_referrer(c, row["referral_code"])
        referrer_id = referrer["id"] if referrer and referrer["id"] != row["user_id"] else None  # no self-referral
        secret = WORKER_TOKEN_PREFIX + new_token(32)
        count = c.execute(select(func.count()).where(workers.c.user_id == row["user_id"])).scalar()
        wid = c.execute(workers.insert().values(
            user_id=row["user_id"], name=row["worker_name"] or f"gpu-server-{count + 1}", token_hash=token_hash(secret),
            status="online", paused=False, hardware=json.dumps(_clean_hw(hardware)), limits=json.dumps({}),
            version=(version or "")[:32], referrer_id=referrer_id, verified_jobs=0, failed_jobs=0, enrolled_at=t,
            last_heartbeat_at=t)).inserted_primary_key[0]
        audit(ctx.db, "training.worker_enrolled", row["user_id"], f"worker:{wid}",
              {"gpus": [g.get("name") for g in _clean_hw(hardware).get("gpus", [])], "referrer": referrer_id}, conn=c)
    return int(wid), secret


def _clean_hw(hw: dict[str, Any]) -> dict[str, Any]:
    def s(v, n=96):
        return str(v)[:n] if v is not None else None

    gpus = [{"name": s(g.get("name")), "memory_gb": float(g.get("memory_gb") or 0), "driver": s(g.get("driver"), 32),
             "utilization": g.get("utilization"), "memory_used_gb": g.get("memory_used_gb")}
            for g in (hw.get("gpus") or [])[:16] if isinstance(g, dict)]
    return {"gpus": gpus, "cuda": s(hw.get("cuda"), 32), "torch": s(hw.get("torch"), 32), "cpu_count": hw.get("cpu_count"),
            "ram_gb": hw.get("ram_gb"), "os": s(hw.get("os"), 128), "disk_free_gb": hw.get("disk_free_gb")}


def worker_by_token(ctx: Ctx, token: str | None) -> dict | None:
    if not token or not token.startswith(WORKER_TOKEN_PREFIX):
        return None
    w = ctx.db.one(select(workers).where(workers.c.token_hash == token_hash(token)))
    if not w or w["revoked_at"] is not None:
        return None
    return w


# ---- scheduling ------------------------------------------------------------------------------
def requeue_expired(ctx: Ctx) -> int:
    t = now()
    n = 0
    with ctx.db.tx() as c:
        for j in c.execute(select(training_jobs).where(training_jobs.c.status == "leased",
                                                       training_jobs.c.lease_expires_at < t)).mappings().all():
            final = j["attempts"] >= j["max_attempts"]
            c.execute(training_jobs.update().where(training_jobs.c.id == j["id"]).values(
                status="failed" if final else "queued", worker_id=None if not final else j["worker_id"],
                lease_expires_at=None, error="lease expired (worker stopped responding)", updated_at=t))
            n += 1
        c.execute(workers.update().where(workers.c.status == "online", workers.c.last_heartbeat_at < t - OFFLINE_AFTER)
                  .values(status="offline"))
    return n


def ensure_jobs(ctx: Ctx) -> None:
    """Keep a small queue of training-round jobs while a coordinator is initialised."""
    coord = coordinator(ctx)
    if coord is None:
        return
    with ctx.db.tx() as c:
        open_jobs = c.execute(select(func.count()).where(training_jobs.c.status.in_(("queued", "leased")),
                                                         training_jobs.c.kind == "train_round")).scalar()
        cfg_round = coord.config["round"]
        # Drop queued jobs from an older round (their base checkpoint is outdated).
        for j in c.execute(select(training_jobs).where(training_jobs.c.status == "queued")).mappings().all():
            if json.loads(j["spec"]).get("round") != cfg_round:
                c.execute(training_jobs.update().where(training_jobs.c.id == j["id"])
                          .values(status="cancelled", error="superseded by a newer round", updated_at=now()))
                open_jobs -= 1
        for _ in range(max(0, MAX_QUEUED - open_jobs)):
            c.execute(training_jobs.insert().values(kind="train_round", status="queued",
                                                    spec=json.dumps({"round": cfg_round}), attempts=0, max_attempts=3,
                                                    created_at=now(), updated_at=now()))


def claim_job(ctx: Ctx, worker: dict, allow_cpu: bool) -> dict | None:
    if worker["paused"]:
        return None
    hw = json.loads(worker["hardware"] or "{}")
    if not hw.get("gpus") and not allow_cpu:
        return None  # GPU workers only (CPU allowed only in development)
    requeue_expired(ctx)
    ensure_jobs(ctx)
    coord = coordinator(ctx)
    if coord is None:
        return None
    t = now()
    with ctx.db.tx() as c:
        # Resume: a job this worker still holds comes back first (e.g. after a reconnect).
        job = c.execute(select(training_jobs).where(training_jobs.c.status == "leased",
                                                    training_jobs.c.worker_id == worker["id"])).mappings().first()
        if not job:
            job = c.execute(select(training_jobs).where(training_jobs.c.status == "queued")
                            .order_by(training_jobs.c.id)).mappings().first()
            if not job:
                return None
            spec = json.loads(job["spec"])
            if "job_id" not in spec or spec.get("round") != coord.config["round"]:
                spec = {**coord.next_job(f"worker-{worker['id']}").to_dict(), "round": coord.config["round"]}
            res = c.execute(training_jobs.update().where(training_jobs.c.id == job["id"],
                                                         training_jobs.c.status == "queued").values(
                status="leased", worker_id=worker["id"], lease_expires_at=t + LEASE_SECONDS,
                attempts=training_jobs.c.attempts + 1, spec=json.dumps(spec), updated_at=t))
            if res.rowcount != 1:
                return None
            job = c.execute(select(training_jobs).where(training_jobs.c.id == job["id"])).mappings().first()
        return {"id": job["id"], "kind": job["kind"], "spec": json.loads(job["spec"]),
                "limits": json.loads(worker["limits"] or "{}"), "lease_seconds": LEASE_SECONDS}


def leased_job(ctx: Ctx, worker: dict, job_id: int) -> dict:
    j = ctx.db.one(select(training_jobs).where(training_jobs.c.id == job_id))
    if not j or j["worker_id"] != worker["id"] or j["status"] != "leased":
        raise TrainingError("job is not leased to this worker")
    return j


def extend_lease(ctx: Ctx, worker: dict, job_id: int | None, progress: float | None = None) -> None:
    t = now()
    with ctx.db.tx() as c:
        if job_id:
            values: dict[str, Any] = {"lease_expires_at": t + LEASE_SECONDS, "updated_at": t}
            if progress is not None:
                values["progress"] = max(0.0, min(1.0, float(progress)))
            c.execute(training_jobs.update().where(training_jobs.c.id == job_id, training_jobs.c.worker_id == worker["id"],
                                                   training_jobs.c.status == "leased").values(**values))


def submit_result(ctx: Ctx, worker: dict, job_id: int, meta: dict, payload: bytes) -> dict:
    """Verify a contribution with the coordinator; only accepted work is counted and rewarded."""
    from moth.community.protocol import JobSpec

    job = leased_job(ctx, worker, job_id)
    coord = coordinator(ctx)
    if coord is None:
        raise TrainingError("training is not configured on this server")
    spec = json.loads(job["spec"])
    coord.jobs.setdefault(spec["job_id"], JobSpec.from_dict(spec))  # durable across coordinator restarts
    meta = {**meta, "job_id": spec["job_id"], "client_id": f"worker-{worker['id']}"}
    result = coord.submit(meta, payload)
    t = now()
    with ctx.db.tx() as c:
        if result.get("accepted"):
            c.execute(training_jobs.update().where(training_jobs.c.id == job_id).values(
                status="completed", progress=1.0, result=json.dumps({k: v for k, v in result.items() if k != "aggregated"}),
                lease_expires_at=None, updated_at=t))
            c.execute(workers.update().where(workers.c.id == worker["id"])
                      .values(verified_jobs=workers.c.verified_jobs + 1))
            fresh = dict(c.execute(select(workers).where(workers.c.id == worker["id"])).mappings().first())
            run_hook(ctx, "worker_contribution_verified", conn=c, worker=fresh, job_id=job_id)
            if result.get("aggregated"):
                run_hook(ctx, "checkpoint_aggregated", conn=c, info=result["aggregated"])
        else:
            c.execute(training_jobs.update().where(training_jobs.c.id == job_id).values(
                status="failed", error="; ".join(result.get("reasons", []))[:2000], lease_expires_at=None, updated_at=t))
            c.execute(workers.update().where(workers.c.id == worker["id"]).values(failed_jobs=workers.c.failed_jobs + 1))
        audit(ctx.db, "training.result", worker["user_id"], f"job:{job_id}",
              {"worker": worker["id"], "accepted": bool(result.get("accepted")), "reasons": result.get("reasons")}, conn=c)
    return result


def fail_job(ctx: Ctx, worker: dict, job_id: int, error: str) -> None:
    leased_job(ctx, worker, job_id)
    t = now()
    with ctx.db.tx() as c:
        j = c.execute(select(training_jobs).where(training_jobs.c.id == job_id)).mappings().first()
        final = j["attempts"] >= j["max_attempts"]
        c.execute(training_jobs.update().where(training_jobs.c.id == job_id).values(
            status="failed" if final else "queued", worker_id=j["worker_id"] if final else None, lease_expires_at=None,
            error=error[:2000], updated_at=t))
        c.execute(workers.update().where(workers.c.id == worker["id"]).values(failed_jobs=workers.c.failed_jobs + 1))


def heartbeat(ctx: Ctx, worker: dict, hardware: dict | None, job_id: int | None, progress: float | None,
              version: str | None = None) -> dict:
    t = now()
    values: dict[str, Any] = {"last_heartbeat_at": t, "status": "online"}
    if version:
        values["version"] = version[:32]
    if hardware:
        values["hardware"] = json.dumps(_clean_hw(hardware))
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == worker["id"]).values(**values))
    if job_id and not worker["paused"]:
        extend_lease(ctx, worker, job_id, progress)
    return {"paused": bool(worker["paused"]), "revoked": worker["revoked_at"] is not None,
            "limits": json.loads(worker["limits"] or "{}"), "server_time": t}


def public_worker(w: dict) -> dict:
    return {"id": w["id"], "name": w["name"], "status": "revoked" if w["revoked_at"] else
            ("paused" if w["paused"] else w["status"]), "paused": bool(w["paused"]),
            "hardware": json.loads(w["hardware"] or "{}"), "limits": json.loads(w["limits"] or "{}"),
            "version": w["version"], "verified_jobs": w["verified_jobs"], "failed_jobs": w["failed_jobs"],
            "enrolled_at": w["enrolled_at"], "last_heartbeat_at": w["last_heartbeat_at"],
            "referred": w["referrer_id"] is not None}


def worker_jobs(ctx: Ctx, worker_ids: list[int], limit: int = 50) -> list[dict]:
    if not worker_ids:
        return []
    return ctx.db.all(select(training_jobs.c.id, training_jobs.c.status, training_jobs.c.worker_id, training_jobs.c.progress,
                             training_jobs.c.error, training_jobs.c.result, training_jobs.c.updated_at)
                      .where(training_jobs.c.worker_id.in_(worker_ids)).order_by(training_jobs.c.id.desc()).limit(limit))
