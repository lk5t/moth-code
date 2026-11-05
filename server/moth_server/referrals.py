"""Referral attribution, qualifying events, pending rewards, caps and reversals.

Rewards are MOTH usage credits (never cash) and are only created by *verified qualifying
events*:

* user referral — the referred user's first successful paid invoice (verified webhook);
* GPU server referral — a referred training server's verified training contributions,
  after a minimum number of verified jobs (idle or failing servers earn nothing).

Each reward waits ``pending_days`` (refunds/chargebacks in that window reverse it), then is
credited through the ledger, subject to monthly and lifetime caps. Suspicious referrals
(e.g. same IP as the referrer) are held for Owner review instead of paying out.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.engine import Connection

from moth_server.audit import audit
from moth_server.billing import InsufficientUsage, ledger_entry
from moth_server.context import Ctx
from moth_server.db import Database, credit_ledger, now, referral_rewards, referrals, sessions, users, workers
from moth_server.hooks import register_hook

DEFAULT_RULES: dict[str, Any] = {
    "enabled": True,
    "user_reward_tokens": 500_000,
    "qualifying_min_amount_cents": 100,
    "gpu_reward_tokens_per_job": 50_000,
    "gpu_min_verified_jobs": 3,
    "pending_days": 14,
    "max_user_rewards_per_month": 10,
    "max_gpu_reward_tokens_per_month": 2_000_000,
    "lifetime_cap_tokens": 20_000_000,
    "hold_same_ip_for_review": True,
}


def rules(db: Database) -> dict[str, Any]:
    return {**DEFAULT_RULES, **(db.get_config("referral_rules", {}) or {})}


def find_referrer(conn: Connection, code: str | None) -> dict | None:
    if not code:
        return None
    row = conn.execute(select(users).where(users.c.referral_code == code.strip().upper())).mappings().first()
    if not row or row["status"] != "active" or row["email_verified_at"] is None:
        return None
    return dict(row)


def _ips_of(conn: Connection, user_id: int) -> set[str]:
    since = now() - 30 * 86400
    ips = {r[0] for r in conn.execute(select(sessions.c.ip).where(sessions.c.user_id == user_id,
                                                                  sessions.c.created_at > since)) if r[0]}
    reg = conn.execute(select(users.c.registration_ip).where(users.c.id == user_id)).scalar()
    return ips | ({reg} if reg else set())


# ---- hooks --------------------------------------------------------------------------------
def on_registered(ctx: Ctx, conn: Connection, user: dict, referral_code: str | None, ip: str | None) -> None:
    r = rules(ctx.db)
    if not r["enabled"]:
        return
    referrer = find_referrer(conn, referral_code)
    if not referrer or referrer["id"] == user["id"]:
        return
    flags = []
    if ip and ip in _ips_of(conn, referrer["id"]):
        flags.append("same_ip_as_referrer")
    status = "review" if flags and r["hold_same_ip_for_review"] else "registered"
    t = now()
    conn.execute(referrals.insert().values(referrer_id=referrer["id"], referred_id=user["id"], status=status,
                                           flags=json.dumps(flags), created_at=t, updated_at=t))
    conn.execute(users.update().where(users.c.id == user["id"]).values(referred_by=referrer["id"]))


def on_payment(ctx: Ctx, conn: Connection, user_id: int, amount: int, reference: str, plan_code: str) -> None:
    r = rules(ctx.db)
    ref = conn.execute(select(referrals).where(referrals.c.referred_id == user_id)).mappings().first()
    if not ref or ref["status"] in ("rewarded", "reversed", "rejected", "qualified"):
        return  # only the first qualifying payment counts
    if int(amount or 0) < r["qualifying_min_amount_cents"]:
        return
    t = now()
    held = ref["status"] == "review"
    conn.execute(referral_rewards.insert().values(
        referrer_id=ref["referrer_id"], kind="user", referral_id=ref["id"], qualifying_ref=f"user-referral:{ref['id']}",
        source_ref=reference, amount=r["user_reward_tokens"], status="review" if held else "pending",
        available_at=t + r["pending_days"] * 86400, reason="first paid invoice", created_at=t, updated_at=t))
    if not held:
        conn.execute(referrals.update().where(referrals.c.id == ref["id"]).values(status="qualified", updated_at=t))


def on_payment_reversed(ctx: Ctx, conn: Connection, reference: str | None, event_type: str) -> None:
    if not reference:
        return
    for rw in conn.execute(select(referral_rewards).where(referral_rewards.c.source_ref == reference)).mappings().all():
        reverse_reward(ctx.db, conn, dict(rw), f"payment {event_type}")


def on_contribution_verified(ctx: Ctx, conn: Connection, worker: dict, job_id: int) -> None:
    r = rules(ctx.db)
    if not r["enabled"] or not worker.get("referrer_id") or worker["referrer_id"] == worker["user_id"]:
        return
    verified = conn.execute(select(workers.c.verified_jobs).where(workers.c.id == worker["id"])).scalar_one()
    if verified < r["gpu_min_verified_jobs"]:
        return
    t = now()
    key = f"gpu:{worker['id']}:{job_id}"
    if conn.execute(select(referral_rewards.c.id).where(referral_rewards.c.qualifying_ref == key)).first():
        return
    conn.execute(referral_rewards.insert().values(
        referrer_id=worker["referrer_id"], kind="gpu", worker_id=worker["id"], qualifying_ref=key,
        source_ref=f"job:{job_id}", amount=r["gpu_reward_tokens_per_job"], status="pending",
        available_at=t + r["pending_days"] * 86400, reason="verified training contribution",
        created_at=t, updated_at=t))


# ---- reward processing --------------------------------------------------------------------
def _month_start(t: float) -> float:
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    return dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc).timestamp()


def process_pending(db: Database, t: float | None = None) -> dict[str, int]:
    """Credit rewards whose pending period has ended, applying caps. Safe to run repeatedly."""
    t = t or now()
    r = rules(db)
    counts = {"credited": 0, "capped": 0}
    due = db.all(select(referral_rewards.c.id).where(referral_rewards.c.status == "pending",
                                                     referral_rewards.c.available_at <= t)
                 .order_by(referral_rewards.c.id))
    for row in due:
        with db.tx() as c:
            rw = c.execute(select(referral_rewards).where(referral_rewards.c.id == row["id"],
                                                          referral_rewards.c.status == "pending")).mappings().first()
            if not rw:
                continue
            ms = _month_start(t)
            credited = and_(referral_rewards.c.referrer_id == rw["referrer_id"], referral_rewards.c.status == "credited")
            lifetime = c.execute(select(func.coalesce(func.sum(referral_rewards.c.amount), 0)).where(credited)).scalar()
            month_count = c.execute(select(func.count()).where(credited, referral_rewards.c.kind == "user",
                                                               referral_rewards.c.updated_at >= ms)).scalar()
            month_gpu = c.execute(select(func.coalesce(func.sum(referral_rewards.c.amount), 0))
                                  .where(credited, referral_rewards.c.kind == "gpu",
                                         referral_rewards.c.updated_at >= ms)).scalar()
            reason = None
            if lifetime + rw["amount"] > r["lifetime_cap_tokens"]:
                reason = "lifetime cap reached"
            elif rw["kind"] == "user" and month_count >= r["max_user_rewards_per_month"]:
                reason = "monthly referral cap reached"
            elif rw["kind"] == "gpu" and month_gpu + rw["amount"] > r["max_gpu_reward_tokens_per_month"]:
                reason = "monthly GPU reward cap reached"
            if reason:
                c.execute(referral_rewards.update().where(referral_rewards.c.id == rw["id"])
                          .values(status="capped", reason=reason, updated_at=t))
                counts["capped"] += 1
                continue
            kind = "referral_reward" if rw["kind"] == "user" else "gpu_referral_reward"
            entry = ledger_entry(c, rw["referrer_id"], rw["amount"], kind, f"reward:{rw['id']}",
                                 reference=rw["qualifying_ref"], note=rw["reason"])
            c.execute(referral_rewards.update().where(referral_rewards.c.id == rw["id"])
                      .values(status="credited", ledger_id=entry["id"] if entry else None, updated_at=t))
            if rw["referral_id"]:
                c.execute(referrals.update().where(referrals.c.id == rw["referral_id"]).values(status="rewarded",
                                                                                           updated_at=t))
            counts["credited"] += 1
    return counts


def reverse_reward(db: Database, conn: Connection, rw: dict, reason: str, actor_id: int | None = None) -> str:
    t = now()
    if rw["status"] in ("reversed", "rejected"):
        return rw["status"]
    if rw["status"] == "credited":
        bal = conn.execute(select(users.c.credit_balance).where(users.c.id == rw["referrer_id"])).scalar_one()
        take = min(bal, rw["amount"])  # never drive the balance negative; record a partial clawback
        if take:
            ledger_entry(conn, rw["referrer_id"], -take, "reversal", f"reverse:{rw['id']}", reference=rw["qualifying_ref"],
                         note=reason if take == rw["amount"] else f"{reason} (partial clawback {take} of {rw['amount']})",
                         actor_id=actor_id)
    conn.execute(referral_rewards.update().where(referral_rewards.c.id == rw["id"])
                 .values(status="reversed", reason=reason, updated_at=t))
    if rw["referral_id"]:
        conn.execute(referrals.update().where(referrals.c.id == rw["referral_id"]).values(status="reversed",
                                                                                      updated_at=t))
    audit(db, "referral.reward_reversed", actor_id, f"reward:{rw['id']}", {"reason": reason}, conn=conn)
    return "reversed"


def setup_hooks(ctx: Ctx) -> None:
    register_hook(ctx, "user_registered", on_registered)
    register_hook(ctx, "payment_succeeded", on_payment)
    register_hook(ctx, "payment_reversed", on_payment_reversed)
    register_hook(ctx, "worker_contribution_verified", on_contribution_verified)


def dashboard(db: Database, user_id: int, public_url: str, code: str) -> dict[str, Any]:
    r = rules(db)
    refs = db.all(select(referrals, users.c.username).join(users, users.c.id == referrals.c.referred_id)
                  .where(referrals.c.referrer_id == user_id).order_by(referrals.c.created_at.desc()))
    rewards = db.all(select(referral_rewards).where(referral_rewards.c.referrer_id == user_id)
                     .order_by(referral_rewards.c.created_at.desc()))
    earned = db.one(select(func.coalesce(func.sum(credit_ledger.c.amount), 0).label("s"))
                    .where(credit_ledger.c.user_id == user_id,
                           credit_ledger.c.kind.in_(("referral_reward", "gpu_referral_reward", "reversal"))))["s"]

    def mask(name: str) -> str:
        return name[:2] + "•" * max(1, len(name) - 2)

    return {
        "code": code, "link": f"{public_url}/r/{code}",
        "rules": {k: r[k] for k in ("enabled", "user_reward_tokens", "gpu_reward_tokens_per_job", "gpu_min_verified_jobs",
                                    "pending_days")},
        "stats": {
            "referred": len(refs),
            "qualified": sum(1 for x in refs if x["status"] in ("qualified", "rewarded")),
            "pending_tokens": sum(x["amount"] for x in rewards if x["status"] in ("pending", "review")),
            "earned_tokens": earned,
        },
        "referrals": [{"user": mask(x["username"]), "status": x["status"], "created_at": x["created_at"]} for x in refs],
        "rewards": [{k: x[k] for k in ("id", "kind", "amount", "status", "available_at", "reason", "created_at",
                                       "worker_id")} for x in rewards],
    }
