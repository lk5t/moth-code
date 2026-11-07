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
        hw = _clean_hw(hardware)
        mid = hw.get("machine_id")
        replaced = []
        if mid:  # the same computer enrolled again by the same account replaces its old registration
            for old in c.execute(select(workers.c.id).where(workers.c.machine_id == mid, workers.c.user_id == row["user_id"],
                                                            workers.c.revoked_at.is_(None))).all():
                c.execute(workers.update().where(workers.c.id == old[0]).values(
                    revoked_at=t, status="revoked", token_hash=f"replaced-{old[0]}-{t}"))
                c.execute(training_jobs.update().where(training_jobs.c.worker_id == old[0],
                                                       training_jobs.c.status == "leased")
                          .values(status="queued", worker_id=None, lease_expires_at=None, updated_at=t))
                replaced.append(old[0])
        secret = WORKER_TOKEN_PREFIX + new_token(32)
        count = c.execute(select(func.count()).where(workers.c.user_id == row["user_id"])).scalar()
        default_name = f"{'gpu' if hw.get('compute') == 'gpu' else 'cpu'}-worker-{count + 1}"
        wid = c.execute(workers.insert().values(
            user_id=row["user_id"], name=row["worker_name"] or default_name, token_hash=token_hash(secret),
            status="online", paused=False, hardware=json.dumps(hw), limits=json.dumps({}),
            version=(version or "")[:32], referrer_id=referrer_id, verified_jobs=0, failed_jobs=0, enrolled_at=t,
            last_heartbeat_at=t, machine_id=mid, trained_tokens=0)).inserted_primary_key[0]
        audit(ctx.db, "training.worker_enrolled", row["user_id"], f"worker:{wid}",
              {"gpus": [g.get("name") for g in hw.get("gpus", [])], "compute": hw.get("compute"),
               "referrer": referrer_id, "replaced": replaced}, conn=c)
    return int(wid), secret


def _clean_hw(hw: dict[str, Any]) -> dict[str, Any]:
    def s(v, n=96):
        return str(v)[:n] if v is not None else None

    gpus = [{"name": s(g.get("name")), "memory_gb": float(g.get("memory_gb") or 0), "driver": s(g.get("driver"), 32),
             "utilization": g.get("utilization"), "memory_used_gb": g.get("memory_used_gb")}
            for g in (hw.get("gpus") or [])[:16] if isinstance(g, dict)]
    bench = hw.get("benchmark") if isinstance(hw.get("benchmark"), dict) else None
    def num(v):
        return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    return {"gpus": gpus, "cuda": s(hw.get("cuda"), 32), "torch": s(hw.get("torch"), 32), "cpu_count": hw.get("cpu_count"),
            "ram_gb": num(hw.get("ram_gb")), "os": s(hw.get("os"), 128), "disk_free_gb": num(hw.get("disk_free_gb")),
            "cpu_model": s(hw.get("cpu_model"), 80), "compute": hw["compute"] if hw.get("compute") in ("gpu", "cpu") else ("gpu" if gpus else "cpu"),  # 0.4 workers

            "machine_id": s(hw.get("machine_id"), 64),
            "client": s(hw.get("client"), 24),  # "moth-code" when MOTH Code contributes its own computer
            "benchmark": {"device": s(bench.get("device"), 8), "gflops": num(bench.get("gflops"))} if bench else None}


# ---- capability-based assignment -------------------------------------------------------------
GB = 1024**3
GPU_PREFERENCE_SECONDS = 300
MIN_ROUND_BYTES = 1 * GB  # a training-network round needs at least this much memory  # a job that would run much faster on a GPU waits this long for one


def capacity_bytes(hw: dict[str, Any]) -> int:
    """Memory a worker can give one training job: most of a usable GPU's memory, else most of its RAM."""
    if hw.get("compute") == "gpu" and hw.get("gpus"):
        return int(max(float(g.get("memory_gb") or 0) for g in hw["gpus"]) * 0.9 * GB)
    ram = hw.get("ram_gb")
    return int((float(ram) * 0.7 if ram else 2.0) * GB)


def fits(hw: dict[str, Any], spec: dict[str, Any]) -> bool:
    need = int((spec.get("requirements") or {}).get("memory_bytes") or 0)
    return need <= capacity_bytes(hw)


def gpu_worker_online(conn) -> bool:
    for w in conn.execute(select(workers.c.hardware).where(workers.c.status == "online", workers.c.paused.is_(False),
                                                           workers.c.revoked_at.is_(None))).all():
        if json.loads(w[0] or "{}").get("compute") == "gpu":
            return True
    return False


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
        for j in c.execute(select(training_jobs).where(training_jobs.c.status == "queued",
                                                       training_jobs.c.kind == "train_round")).mappings().all():
            if json.loads(j["spec"]).get("round") != cfg_round:
                c.execute(training_jobs.update().where(training_jobs.c.id == j["id"])
                          .values(status="cancelled", error="superseded by a newer round", updated_at=now()))
                open_jobs -= 1
        for _ in range(max(0, MAX_QUEUED - open_jobs)):
            c.execute(training_jobs.insert().values(kind="train_round", status="queued",
                                                    spec=json.dumps({"round": cfg_round}), attempts=0, max_attempts=3,
                                                    created_at=now(), updated_at=now()))


def claim_job(ctx: Ctx, worker: dict, allow_cpu: bool) -> dict | None:
    """Give the worker a job its hardware can run. CPU and GPU workers are both production workers:
    a job is offered only if its memory requirement fits the worker (GPU memory, else RAM); jobs that
    benefit from a GPU wait briefly for an online GPU worker before a CPU worker takes them.
    ``allow_cpu`` is kept for compatibility and no longer restricts anything."""
    if worker["paused"]:
        return None
    hw = json.loads(worker["hardware"] or "{}")
    requeue_expired(ctx)
    ensure_jobs(ctx)
    coord = coordinator(ctx)
    t = now()
    with ctx.db.tx() as c:
        # Resume: a job this worker still holds comes back first (e.g. after a reconnect).
        job = c.execute(select(training_jobs).where(training_jobs.c.status == "leased",
                                                    training_jobs.c.worker_id == worker["id"])).mappings().first()
        if not job:
            # model-evolution experiments first (one per worker), then training-network rounds
            job = None
            gpu_online = None
            for cand in c.execute(select(training_jobs).where(training_jobs.c.status == "queued",
                                                              training_jobs.c.kind.in_(("evolve_train", "dist_shard")))
                                  .order_by(training_jobs.c.id)).mappings().all():
                spec = json.loads(cand["spec"])
                if not fits(hw, spec):
                    continue
                if hw.get("compute") != "gpu" and spec.get("prefer_gpu") and t - cand["created_at"] < GPU_PREFERENCE_SECONDS:
                    gpu_online = gpu_worker_online(c) if gpu_online is None else gpu_online
                    if gpu_online:
                        continue
                job = cand
                break
            if not job and coord is not None and capacity_bytes(hw) >= MIN_ROUND_BYTES:
                job = c.execute(select(training_jobs).where(training_jobs.c.status == "queued",
                                                            training_jobs.c.kind == "train_round")
                                .order_by(training_jobs.c.id)).mappings().first()
            if not job:
                return None
            spec = json.loads(job["spec"])
            if job["kind"] == "train_round" and ("job_id" not in spec or spec.get("round") != coord.config["round"]):
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
    spec = json.loads(job["spec"])
    if job["kind"] == "evolve_train":
        from moth_server.evolution.backends import accept_worker_result

        result = accept_worker_result(ctx, job, meta, payload)
    elif job["kind"] == "dist_shard":
        from moth_server.evolution.distributed import accept_shard

        result = accept_shard(ctx, job, meta, payload)
    else:
        coord = coordinator(ctx)
        if coord is None:
            raise TrainingError("training is not configured on this server")
        coord.jobs.setdefault(spec["job_id"], JobSpec.from_dict(spec))  # durable across coordinator restarts
        meta = {**meta, "job_id": spec["job_id"], "client_id": f"worker-{worker['id']}"}
        result = coord.submit(meta, payload)
    t = now()
    with ctx.db.tx() as c:
        if result.get("accepted"):
            c.execute(training_jobs.update().where(training_jobs.c.id == job_id).values(
                status="completed", progress=1.0, result=json.dumps({k: v for k, v in result.items() if k != "aggregated"}),
                lease_expires_at=None, updated_at=t))
            tokens = max(0, int(meta.get("tokens") or 0))
            c.execute(workers.update().where(workers.c.id == worker["id"])
                      .values(verified_jobs=workers.c.verified_jobs + 1,
                              trained_tokens=workers.c.trained_tokens + tokens))
            fresh = dict(c.execute(select(workers).where(workers.c.id == worker["id"])).mappings().first())
            run_hook(ctx, "worker_contribution_verified", conn=c, worker=fresh, job_id=job_id, tokens=tokens)
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
        hw = _clean_hw(hardware)
        values["hardware"] = json.dumps(hw)
        if hw.get("machine_id"):
            values["machine_id"] = hw["machine_id"]
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == worker["id"]).values(**values))
    if job_id and not worker["paused"]:
        extend_lease(ctx, worker, job_id, progress)
    return {"paused": bool(worker["paused"]), "revoked": worker["revoked_at"] is not None,
            "limits": json.loads(worker["limits"] or "{}"), "server_time": t}


def leave(ctx: Ctx, worker: dict) -> None:
    """The worker removes itself (``moth-worker uninstall``): its credential stops working at once."""
    t = now()
    with ctx.db.tx() as c:
        c.execute(workers.update().where(workers.c.id == worker["id"]).values(
            revoked_at=t, status="revoked", token_hash=f"left-{worker['id']}-{t}"))
        c.execute(training_jobs.update().where(training_jobs.c.worker_id == worker["id"],
                                               training_jobs.c.status == "leased")
                  .values(status="queued", worker_id=None, lease_expires_at=None, updated_at=t))
        audit(ctx.db, "training.worker_left", worker["user_id"], f"worker:{worker['id']}", conn=c)


def public_worker(w: dict) -> dict:
    return {"id": w["id"], "name": w["name"], "status": "revoked" if w["revoked_at"] else
            ("paused" if w["paused"] else w["status"]), "paused": bool(w["paused"]),
            "hardware": json.loads(w["hardware"] or "{}"), "limits": json.loads(w["limits"] or "{}"),
            "version": w["version"], "verified_jobs": w["verified_jobs"], "failed_jobs": w["failed_jobs"],
            "enrolled_at": w["enrolled_at"], "last_heartbeat_at": w["last_heartbeat_at"],
            "referred": w["referrer_id"] is not None, "trained_tokens": int(w.get("trained_tokens") or 0),
            "reputation": round((w["verified_jobs"] + 1) / (w["verified_jobs"] + w["failed_jobs"] + 2), 2)}


def worker_jobs(ctx: Ctx, worker_ids: list[int], limit: int = 50) -> list[dict]:
    if not worker_ids:
        return []
    return ctx.db.all(select(training_jobs.c.id, training_jobs.c.status, training_jobs.c.worker_id, training_jobs.c.progress,
                             training_jobs.c.error, training_jobs.c.result, training_jobs.c.updated_at)
                      .where(training_jobs.c.worker_id.in_(worker_ids)).order_by(training_jobs.c.id.desc()).limit(limit))
