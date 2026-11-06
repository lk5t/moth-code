"""Owner administration API (Owner role only; changes need recent re-authentication)."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from moth_server import billing
from moth_server.audit import audit
from moth_server.context import Ctx, get_ctx
from moth_server.db import now, plans, users
from moth_server.deps import Auth, owner_reauthed, require_owner

router = APIRouter(prefix="/v1/admin", tags=["admin"])

FEATURE_FLAGS = {
    "cloud_inference_enabled": False,   # only once MOTH-operated GPU inference exists
    "registration_open": True,
    "referrals_enabled": True,
    "training_enrollment_open": True,
    "auto_deploy_models": False,        # deploy candidates automatically when they pass evaluation
}
# Flags that no longer do anything but are still accepted from older apps and scripts.
RETIRED_FLAGS = {"allow_cpu_workers"}  # 0.5: CPU workers are production workers


class PlanIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    price_cents: int | None = Field(default=None, ge=0, le=10_000_00)
    currency: str | None = Field(default=None, max_length=8)
    monthly_tokens: int | None = Field(default=None, ge=0, le=10**12)
    priority: int | None = Field(default=None, ge=0, le=10)
    features: dict[str, Any] | None = None
    provider_price_id: str | None = Field(default=None, max_length=128)
    checkout_enabled: bool | None = None


class CreditIn(BaseModel):
    amount: int = Field(ge=-10**12, le=10**12)
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=100)


class PlanGrantIn(BaseModel):
    plan: str
    days: int = Field(default=30, ge=1, le=3650)


class RoleIn(BaseModel):
    role: str


class StatusIn(BaseModel):
    status: str


def flags(ctx: Ctx) -> dict[str, Any]:
    stored = ctx.db.get_config("feature_flags", {}) or {}
    return {**FEATURE_FLAGS, **{k: v for k, v in stored.items() if k in FEATURE_FLAGS}}


@router.get("/plans")
def admin_plans(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return ctx.db.all(select(plans).order_by(plans.c.sort))


@router.put("/plans/{code}")
def update_plan(code: str, body: PlanIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    values = body.model_dump(exclude_none=True)
    if "features" in values:
        values["features"] = json.dumps(values["features"])
    if code == "free" and values.get("checkout_enabled"):
        raise HTTPException(422, "The free plan cannot be purchased.")
    with ctx.db.tx() as c:
        res = c.execute(plans.update().where(plans.c.code == code).values(**values, updated_at=now()))
        if res.rowcount == 0:
            raise HTTPException(404, "Unknown plan.")
        audit(ctx.db, "admin.plan_updated", auth.uid, f"plan:{code}", body.model_dump(exclude_none=True), conn=c)
    return ctx.db.one(select(plans).where(plans.c.code == code))


@router.post("/users/{user_id}/credits")
def adjust_credits(user_id: int, body: CreditIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    key = f"admin:{body.idempotency_key}" if body.idempotency_key else f"admin:{auth.uid}:{user_id}:{now():.6f}"
    with ctx.db.tx() as c:
        if not c.execute(select(users.c.id).where(users.c.id == user_id)).first():
            raise HTTPException(404, "User not found.")
        try:
            entry = billing.ledger_entry(c, user_id, body.amount, "admin_adjustment", key, note=body.reason,
                                         actor_id=auth.uid)
        except billing.InsufficientUsage:
            raise HTTPException(422, "That would make the user's credit balance negative.") from None
        audit(ctx.db, "admin.credits_adjusted", auth.uid, f"user:{user_id}",
              {"amount": body.amount, "reason": body.reason}, conn=c)
    return entry or {"duplicate": True}


@router.post("/users/{user_id}/plan")
def grant_plan(user_id: int, body: PlanGrantIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    if not ctx.db.one(select(plans.c.code).where(plans.c.code == body.plan)):
        raise HTTPException(404, "Unknown plan.")
    target = ctx.db.one(select(users).where(users.c.id == user_id))
    if not target:
        raise HTTPException(404, "User not found.")
    billing.grant_manual_plan(ctx.db, user_id, body.plan, body.days, auth.uid)
    audit(ctx.db, "admin.plan_granted", auth.uid, f"user:{user_id}", body.model_dump())
    return billing.summary(ctx.db, ctx.db.one(select(users).where(users.c.id == user_id)))


@router.post("/users/{user_id}/role")
def set_role(user_id: int, body: RoleIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    if body.role not in ("user", "admin"):
        raise HTTPException(422, "Role must be 'user' or 'admin'. The owner role cannot be assigned.")
    target = ctx.db.one(select(users).where(users.c.id == user_id))
    if not target:
        raise HTTPException(404, "User not found.")
    if target["role"] == "owner":
        raise HTTPException(403, "The owner's role cannot be changed.")
    with ctx.db.tx() as c:
        c.execute(users.update().where(users.c.id == user_id).values(role=body.role))
        audit(ctx.db, "admin.role_changed", auth.uid, f"user:{user_id}", {"role": body.role}, conn=c)
    return {"ok": True}


@router.post("/users/{user_id}/status")
def set_status(user_id: int, body: StatusIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.db import sessions

    if body.status not in ("active", "suspended"):
        raise HTTPException(422, "Status must be 'active' or 'suspended'.")
    target = ctx.db.one(select(users).where(users.c.id == user_id))
    if not target:
        raise HTTPException(404, "User not found.")
    if target["role"] == "owner":
        raise HTTPException(403, "The owner account cannot be suspended.")
    with ctx.db.tx() as c:
        c.execute(users.update().where(users.c.id == user_id).values(status=body.status))
        if body.status == "suspended":
            c.execute(sessions.update().where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
                      .values(revoked_at=now()))
        audit(ctx.db, "admin.status_changed", auth.uid, f"user:{user_id}", {"status": body.status}, conn=c)
    return {"ok": True}


@router.get("/config")
def get_config(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return {"feature_flags": flags(ctx)}


@router.put("/config/flags")
def set_flags(body: dict[str, bool], auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    unknown = set(body) - set(FEATURE_FLAGS) - RETIRED_FLAGS
    if unknown:
        raise HTTPException(422, f"Unknown flags: {', '.join(sorted(unknown))}")
    body = {k: v for k, v in body.items() if k in FEATURE_FLAGS}
    current = {**(ctx.db.get_config("feature_flags", {}) or {}), **body}
    ctx.db.set_config("feature_flags", current)
    audit(ctx.db, "admin.flags_updated", auth.uid, "config:feature_flags", body)
    return {"feature_flags": flags(ctx)}


# ---- content policy (applied server-side to every MOTH Cloud request) ----------------------------
@router.get("/policy")
def get_policy(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth.policy.engine import PolicyEngine

    return PolicyEngine(ctx.db.get_config("content_policy", {}) or {}).data


@router.put("/policy")
def put_policy(body: dict[str, Any], auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth.policy.engine import PolicyEngine, PolicyError

    try:
        engine = PolicyEngine(body)
    except PolicyError as e:
        raise HTTPException(422, str(e)) from None
    ctx.db.set_config("content_policy", engine.data)
    audit(ctx.db, "admin.policy_updated", auth.uid, "config:content_policy", {"rules": len(engine.rules)})
    return engine.data


class PublicUrlIn(BaseModel):
    url: str = Field(default="", max_length=300)


@router.put("/config/public-url")
def set_public_url(body: PublicUrlIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    """The address used in emails, referral links and worker install commands. Empty = use the
    MOTH_SERVER_PUBLIC_URL setting. No restart needed."""
    from urllib.parse import urlparse

    from moth_server.context import public_url

    url = body.url.strip().rstrip("/")
    if url:
        u = urlparse(url)
        if u.scheme != "https" or not u.netloc or u.path not in ("", "/") or u.query:
            raise HTTPException(422, "Use the server's base address with https://, e.g. https://moth.example.com")
    ctx.db.set_config("public_url", url or None)
    audit(ctx.db, "admin.public_url", auth.uid, "server", {"url": url or None})
    return {"public_url": public_url(ctx), "public_url_env": ctx.settings.public_url}
