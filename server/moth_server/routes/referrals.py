"""Referral dashboard, share page, and Owner referral administration."""

from __future__ import annotations

import html
import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from moth_server import referrals as R
from moth_server.audit import audit
from moth_server.context import public_url
from moth_server.context import Ctx, get_ctx
from moth_server.db import now, referral_rewards, referrals, users
from moth_server.deps import Auth, current_auth, owner_reauthed, require_owner
from moth_server.pages.web import page

router = APIRouter(tags=["referrals"])
PROCESS_INTERVAL = 600.0


def setup(ctx: Ctx) -> None:
    R.setup_hooks(ctx)

    def loop() -> None:  # credit matured rewards periodically
        stop: threading.Event = ctx.extras["referral_stop"]
        while not stop.wait(PROCESS_INTERVAL):
            try:
                R.process_pending(ctx.db)
            except Exception:  # noqa: BLE001 — retried next cycle
                pass

    ctx.extras["referral_stop"] = threading.Event()
    threading.Thread(target=loop, daemon=True, name="referral-rewards").start()


class RulesIn(BaseModel):
    enabled: bool | None = None
    user_reward_tokens: int | None = Field(default=None, ge=0, le=10**10)
    qualifying_min_amount_cents: int | None = Field(default=None, ge=0)
    gpu_reward_tokens_per_job: int | None = Field(default=None, ge=0, le=10**10)
    gpu_min_verified_jobs: int | None = Field(default=None, ge=0, le=10_000)
    pending_days: int | None = Field(default=None, ge=0, le=365)
    max_user_rewards_per_month: int | None = Field(default=None, ge=0, le=10_000)
    max_gpu_reward_tokens_per_month: int | None = Field(default=None, ge=0)
    lifetime_cap_tokens: int | None = Field(default=None, ge=0)
    hold_same_ip_for_review: bool | None = None
    contribution_reward_per_1k_tokens: float | None = Field(default=None, ge=0, le=10**6)
    max_reward_per_job: int | None = Field(default=None, ge=0, le=10**10)
    contributor_min_verified_jobs: int | None = Field(default=None, ge=0, le=10_000)
    min_reputation: float | None = Field(default=None, ge=0, le=1)
    reputation_min_jobs: int | None = Field(default=None, ge=0, le=10_000)
    hold_duplicate_machines: bool | None = None
    user_payment_rewards: bool | None = None


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.get("/v1/referrals")
def my_referrals(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    R.process_pending(ctx.db)
    return R.dashboard(ctx.db, auth.uid, public_url(ctx), auth.user["referral_code"])


@router.get("/r/{code}", include_in_schema=False)
def share_page(code: str, ctx: Ctx = Depends(get_ctx)):
    clean = html.escape(code.strip().upper()[:16])
    valid = ctx.db.one(select(users.c.id).where(users.c.referral_code == clean)) is not None
    if not valid:
        return page("Invitation", "<h1>Invitation not found</h1><p>This referral link is not valid.</p>")
    return page("Join MOTH Code", f"""<h1>You're invited to MOTH Code</h1>
<p>MOTH Code is an independent AI coding agent with its own neural network.</p>
<p>When you create your account, enter this referral code:</p>
<p style="font-size:22px;letter-spacing:.2em;color:#fff;font-weight:700">{clean}</p>""")


# ---- Owner administration --------------------------------------------------------------------
@router.get("/v1/admin/referrals")
def admin_referrals(status: str | None = None, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    referrer = users.alias("referrer")
    q = (select(referrals, referrer.c.username.label("referrer"), users.c.username.label("referred"))
         .join(referrer, referrer.c.id == referrals.c.referrer_id).join(users, users.c.id == referrals.c.referred_id))
    if status:
        q = q.where(referrals.c.status == status)
    rewards = ctx.db.all(select(referral_rewards).order_by(referral_rewards.c.id.desc()).limit(500))
    return {"rules": R.rules(ctx.db), "referrals": ctx.db.all(q.order_by(referrals.c.id.desc()).limit(500)),
            "rewards": rewards}


@router.put("/v1/admin/referral-rules")
def update_rules(body: RulesIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    current: dict[str, Any] = {**(ctx.db.get_config("referral_rules", {}) or {}), **body.model_dump(exclude_none=True)}
    ctx.db.set_config("referral_rules", current)
    audit(ctx.db, "admin.referral_rules_updated", auth.uid, "config:referral_rules", body.model_dump(exclude_none=True))
    return R.rules(ctx.db)


@router.post("/v1/admin/referrals/{rid}/approve")
def approve(rid: int, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    t = now()
    with ctx.db.tx() as c:
        ref = c.execute(select(referrals).where(referrals.c.id == rid)).mappings().first()
        if not ref or ref["status"] != "review":
            raise HTTPException(409, "Only referrals held for review can be approved.")
        held = c.execute(select(referral_rewards).where(referral_rewards.c.referral_id == rid,
                                                        referral_rewards.c.status == "review")).mappings().first()
        c.execute(referrals.update().where(referrals.c.id == rid)
                  .values(status="qualified" if held else "registered", updated_at=t))
        if held:
            c.execute(referral_rewards.update().where(referral_rewards.c.id == held["id"])
                      .values(status="pending", updated_at=t))
        audit(ctx.db, "admin.referral_approved", auth.uid, f"referral:{rid}", conn=c)
    return {"ok": True}


@router.post("/v1/admin/referrals/{rid}/reject")
def reject(rid: int, body: ReasonIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    t = now()
    with ctx.db.tx() as c:
        ref = c.execute(select(referrals).where(referrals.c.id == rid)).mappings().first()
        if not ref:
            raise HTTPException(404, "Referral not found.")
        for rw in c.execute(select(referral_rewards).where(referral_rewards.c.referral_id == rid)).mappings().all():
            R.reverse_reward(ctx.db, c, dict(rw), f"rejected: {body.reason}", auth.uid)
        c.execute(referrals.update().where(referrals.c.id == rid).values(status="rejected", updated_at=t))
        audit(ctx.db, "admin.referral_rejected", auth.uid, f"referral:{rid}", {"reason": body.reason}, conn=c)
    return {"ok": True}


@router.post("/v1/admin/rewards/{reward_id}/reverse")
def reverse(reward_id: int, body: ReasonIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    with ctx.db.tx() as c:
        rw = c.execute(select(referral_rewards).where(referral_rewards.c.id == reward_id)).mappings().first()
        if not rw:
            raise HTTPException(404, "Reward not found.")
        return {"status": R.reverse_reward(ctx.db, c, dict(rw), body.reason, auth.uid)}


@router.post("/v1/admin/rewards/process")
def process(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return R.process_pending(ctx.db)
