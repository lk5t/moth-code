"""Owner Dashboard read API: overview, users, workers/jobs, system health, audit log."""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import desc, func, or_, select

from moth_server import billing, models as M, training as T
from moth_server.context import public_url
from moth_server.context import Ctx, get_ctx
from moth_server.db import (
    audit_log, credit_ledger, model_releases, referral_rewards, sessions, subscriptions, training_jobs, usage_events,
    usage_periods, users, workers,
)
from moth_server.deps import Auth, require_owner
from moth_server.routes.admin import flags

router = APIRouter(prefix="/v1/admin", tags=["dashboard"])


def dir_size(p: Path) -> int:
    total = 0
    if p.exists():
        for f in p.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
    return total


@router.get("/overview")
def overview(request: Request, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    db, t = ctx.db, time.time()
    T.requeue_expired(ctx)
    month_start = billing.month_bounds(t)[0]
    count = lambda q: db.one(q)["n"]  # noqa: E731
    plans = {r["plan_code"]: r["n"] for r in db.all(select(users.c.plan_code, func.count().label("n")).group_by(users.c.plan_code))}
    coord = T.coordinator(ctx)
    dep = M.deployed(ctx)
    data_dir = ctx.settings.data_dir
    disk = shutil.disk_usage(data_dir)
    db_size = None
    if db.is_sqlite:
        db_file = Path(ctx.settings.db_url.removeprefix("sqlite:///"))
        db_size = db_file.stat().st_size if db_file.exists() else None
    return {
        "users": {
            "total": count(select(func.count().label("n")).select_from(users)),
            "verified": count(select(func.count().label("n")).select_from(users).where(users.c.email_verified_at.is_not(None))),
            "suspended": count(select(func.count().label("n")).select_from(users).where(users.c.status == "suspended")),
            "new_30d": count(select(func.count().label("n")).select_from(users).where(users.c.created_at > t - 30 * 86400)),
            "active_sessions": count(select(func.count().label("n")).select_from(sessions)
                                     .where(sessions.c.revoked_at.is_(None), sessions.c.expires_at > t)),
            "by_plan": plans,
        },
        "billing": {
            "active_subscriptions": count(select(func.count().label("n")).select_from(subscriptions)
                                          .where(subscriptions.c.status.in_(billing.ACTIVE_SUB_STATES))),
            "payments_configured": ctx.settings.payments_configured,
            "tokens_used_this_month": db.one(select(func.coalesce(func.sum(usage_events.c.input_tokens + usage_events.c.output_tokens), 0)
                                                    .label("n")).where(usage_events.c.created_at >= month_start))["n"],
            "credits_outstanding": db.one(select(func.coalesce(func.sum(users.c.credit_balance), 0).label("n")))["n"],
            "pending_rewards": count(select(func.count().label("n")).select_from(referral_rewards)
                                     .where(referral_rewards.c.status.in_(("pending", "review")))),
        },
        "training": {
            "configured": coord is not None,
            "round": coord.config["round"] if coord else None,
            "checkpoint_version": coord.config["version"] if coord else None,
            "workers_online": count(select(func.count().label("n")).select_from(workers).where(workers.c.status == "online",
                                                                                               workers.c.revoked_at.is_(None))),
            "workers_total": count(select(func.count().label("n")).select_from(workers).where(workers.c.revoked_at.is_(None))),
            "jobs": {r["status"]: r["n"] for r in db.all(select(training_jobs.c.status, func.count().label("n"))
                                                          .group_by(training_jobs.c.status))},
        },
        "models": {
            "deployed": {k: dep[k] for k in ("version", "name", "published_at")} if dep else None,
            "cloud_inference_enabled": bool(flags(ctx).get("cloud_inference_enabled")),
            "serving": ctx.extras.get("inference_engine") is not None,
            "releases": {r["status"]: r["n"] for r in db.all(select(model_releases.c.status, func.count().label("n"))
                                                              .group_by(model_releases.c.status))},
        },
        "system": {
            "uptime_seconds": round(t - request.app.state.started_at),
            "database": "sqlite" if db.is_sqlite else "postgresql",
            "database_bytes": db_size,
            "storage_bytes": dir_size(ctx.settings.storage_dir),
            "coordinator_bytes": dir_size(T.coordinator_root(ctx)),
            "disk_free_bytes": disk.free, "disk_total_bytes": disk.total,
            "email": ctx.mailer.mode, "public_url": public_url(ctx), "public_url_env": ctx.settings.public_url,
            "pid": os.getpid(),
        },
        "feature_flags": flags(ctx),
    }


@router.get("/users")
def list_users(q: str = "", limit: int = 100, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    stmt = select(users.c.id, users.c.username, users.c.email, users.c.role, users.c.status, users.c.plan_code,
                  users.c.credit_balance, users.c.email_verified_at, users.c.created_at, users.c.last_login_at)
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(users.c.username_lc.like(like), func.lower(users.c.email).like(like)))
    rows = ctx.db.all(stmt.order_by(desc(users.c.created_at)).limit(min(max(limit, 1), 500)))
    t = time.time()
    used = {r["user_id"]: r for r in ctx.db.all(select(usage_periods).where(usage_periods.c.period_start <= t,
                                                                            usage_periods.c.period_end > t))}
    for r in rows:
        p = used.get(r["id"])
        r["usage"] = {"used": p["used"], "allowance": p["allowance"]} if p else None
    return rows


@router.get("/users/{user_id}")
def user_detail(user_id: int, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    u = ctx.db.one(select(users).where(users.c.id == user_id))
    if not u:
        raise HTTPException(404, "User not found.")
    safe = {k: v for k, v in u.items() if k not in ("password_hash", "avatar")}
    return {
        "user": safe,
        "summary": billing.summary(ctx.db, u),
        "subscriptions": ctx.db.all(select(subscriptions).where(subscriptions.c.user_id == user_id)),
        "ledger": ctx.db.all(select(credit_ledger).where(credit_ledger.c.user_id == user_id).order_by(desc(credit_ledger.c.id)).limit(100)),
        "workers": [T.public_worker(w) for w in ctx.db.all(select(workers).where(workers.c.user_id == user_id))],
        "sessions": ctx.db.one(select(func.count().label("n")).select_from(sessions)
                               .where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None),
                                      sessions.c.expires_at > time.time()))["n"],
    }


@router.get("/workers")
def all_workers(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    T.requeue_expired(ctx)
    rows = ctx.db.all(select(workers, users.c.username).join(users, users.c.id == workers.c.user_id).order_by(workers.c.id))
    return [{**T.public_worker(r), "owner": r["username"]} for r in rows]


@router.get("/jobs")
def all_jobs(limit: int = 100, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.all(select(training_jobs).order_by(desc(training_jobs.c.id)).limit(min(max(limit, 1), 500)))
    for r in rows:
        r["spec"] = {k: v for k, v in json.loads(r["spec"]).items() if k in ("round", "shard_id", "model_version")}
        r["metrics"] = json.loads(r.get("result") or "{}")
    return rows


@router.get("/audit")
def audit_entries(limit: int = 200, action: str = "", auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    stmt = select(audit_log, users.c.username).join(users, users.c.id == audit_log.c.actor_id, isouter=True)
    if action:
        stmt = stmt.where(audit_log.c.action.like(f"{action}%"))
    rows = ctx.db.all(stmt.order_by(desc(audit_log.c.id)).limit(min(max(limit, 1), 1000)))
    for r in rows:
        r["detail"] = json.loads(r["detail"] or "{}")
    return rows
