"""Plans, usage periods, metering and the credit ledger.

Metering protocol for every cloud inference request:

1. ``reserve(request_id, max_tokens)`` — atomically hold up to ``max_tokens`` from the
   monthly allowance first, then from earned credits. Fails with ``InsufficientUsage`` if the
   user cannot cover the maximum. The ``request_id`` is unique, so retries never double-charge.
2. ``settle(request_id, input_tokens, output_tokens)`` — charge the actual count and return
   the unused part of the hold. Idempotent.

All balance changes use conditional updates (``… WHERE balance >= n``) inside a transaction,
so balances can never go negative even under concurrency. Every credit movement is written
to ``credit_ledger`` with ``balance_after``; ``SUM(amount) == users.credit_balance`` always.
"""

from __future__ import annotations

import calendar
import datetime as dt
import json
from typing import Any

from sqlalchemy import and_, desc, select
from sqlalchemy.engine import Connection

from moth_server.db import Database, credit_ledger, now, plans, subscriptions, usage_events, usage_periods, users

DEFAULT_PLANS = [
    {"code": "free", "name": "Free", "price_cents": 0, "monthly_tokens": 200_000, "priority": 0, "sort": 0,
     "features": {"cloud_inference": True, "priority_queue": False}},
    {"code": "pro", "name": "Pro", "price_cents": 1500, "monthly_tokens": 5_000_000, "priority": 1, "sort": 1,
     "features": {"cloud_inference": True, "priority_queue": False}},
    {"code": "max", "name": "Max", "price_cents": 4000, "monthly_tokens": 20_000_000, "priority": 2, "sort": 2,
     "features": {"cloud_inference": True, "priority_queue": True}},
]
ACTIVE_SUB_STATES = ("active", "trialing", "past_due")  # past_due keeps access during the provider's retry window


class InsufficientUsage(Exception):
    pass


class BillingError(ValueError):
    pass


class DuplicateRequest(BillingError):
    """The request id was already used: the caller must not serve it again."""


def seed_plans(db: Database) -> None:
    with db.tx() as c:
        for p in DEFAULT_PLANS:
            if not c.execute(select(plans.c.code).where(plans.c.code == p["code"])).first():
                c.execute(plans.insert().values(
                    code=p["code"], name=p["name"], price_cents=p["price_cents"], currency="usd", interval="month",
                    monthly_tokens=p["monthly_tokens"], priority=p["priority"], features=json.dumps(p["features"]),
                    provider_price_id=None, checkout_enabled=False, sort=p["sort"], updated_at=now()))


def plan_row(conn: Connection, code: str) -> dict:
    row = conn.execute(select(plans).where(plans.c.code == code)).mappings().first()
    if not row:
        row = conn.execute(select(plans).where(plans.c.code == "free")).mappings().first()
    return dict(row)


def month_bounds(t: float) -> tuple[float, float]:
    d = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    start = dt.datetime(d.year, d.month, 1, tzinfo=dt.timezone.utc)
    days = calendar.monthrange(d.year, d.month)[1]
    return start.timestamp(), (start + dt.timedelta(days=days)).timestamp()


def active_subscription(conn: Connection, user_id: int) -> dict | None:
    row = conn.execute(select(subscriptions).where(subscriptions.c.user_id == user_id,
                                                    subscriptions.c.status.in_(ACTIVE_SUB_STATES))
                       .order_by(desc(subscriptions.c.updated_at))).mappings().first()
    if row and row["provider"] == "manual" and row["current_period_end"] and row["current_period_end"] < now():
        return None  # expired complimentary plan
    return dict(row) if row else None


def effective_plan(conn: Connection, user: dict) -> str:
    sub = active_subscription(conn, user["id"])
    return sub["plan_code"] if sub else "free"


def current_period(conn: Connection, user: dict, t: float | None = None) -> dict:
    """The user's usage period containing ``t``, created (rolled over) if needed."""
    t = t or now()
    row = conn.execute(select(usage_periods).where(usage_periods.c.user_id == user["id"],
                                                   usage_periods.c.period_start <= t, usage_periods.c.period_end > t)
                       .order_by(desc(usage_periods.c.period_start))).mappings().first()
    if row:
        return dict(row)
    sub = active_subscription(conn, user["id"])
    if sub and sub["current_period_start"] and sub["current_period_end"] and \
            sub["current_period_start"] <= t < sub["current_period_end"]:
        start, end, code = sub["current_period_start"], sub["current_period_end"], sub["plan_code"]
    else:
        (start, end), code = month_bounds(t), (sub["plan_code"] if sub else "free")
    allowance = plan_row(conn, code)["monthly_tokens"]
    existing = conn.execute(select(usage_periods).where(usage_periods.c.user_id == user["id"],
                                                        usage_periods.c.period_start == start)).mappings().first()
    if existing:  # e.g. created concurrently
        return dict(existing)
    pid = conn.execute(usage_periods.insert().values(user_id=user["id"], period_start=start, period_end=end,
                                                     allowance=allowance, used=0, plan_code=code)).inserted_primary_key[0]
    return dict(conn.execute(select(usage_periods).where(usage_periods.c.id == pid)).mappings().first())


def start_new_period(conn: Connection, user_id: int, start: float, end: float, plan_code: str) -> None:
    """Renewal (e.g. a paid invoice): a fresh period with the plan's allowance."""
    allowance = plan_row(conn, plan_code)["monthly_tokens"]
    exists = conn.execute(select(usage_periods.c.id).where(usage_periods.c.user_id == user_id,
                                                           usage_periods.c.period_start == start)).first()
    # End any overlapping current period at the renewal boundary.
    conn.execute(usage_periods.update().where(usage_periods.c.user_id == user_id, usage_periods.c.period_start < start,
                                              usage_periods.c.period_end > start).values(period_end=start))
    if exists:
        conn.execute(usage_periods.update().where(usage_periods.c.id == exists[0])
                     .values(period_end=end, allowance=allowance, plan_code=plan_code))
    else:
        conn.execute(usage_periods.insert().values(user_id=user_id, period_start=start, period_end=end,
                                                   allowance=allowance, used=0, plan_code=plan_code))


# ---- credit ledger ---------------------------------------------------------------------------
def ledger_entry(conn: Connection, user_id: int, amount: int, kind: str, idempotency_key: str,
                 reference: str | None = None, note: str | None = None, actor_id: int | None = None,
                 allow_negative_result: bool = False) -> dict | None:
    """Apply ``amount`` to the user's credit balance atomically and record it. Returns None if
    this idempotency key was already applied. Raises InsufficientUsage if the balance would go negative."""
    if conn.execute(select(credit_ledger.c.id).where(credit_ledger.c.idempotency_key == idempotency_key)).first():
        return None
    upd = users.update().where(users.c.id == user_id)
    if amount < 0 and not allow_negative_result:
        upd = upd.where(users.c.credit_balance >= -amount)
    res = conn.execute(upd.values(credit_balance=users.c.credit_balance + amount))
    if res.rowcount != 1:
        raise InsufficientUsage("not enough credits")
    bal = conn.execute(select(users.c.credit_balance).where(users.c.id == user_id)).scalar_one()
    lid = conn.execute(credit_ledger.insert().values(
        user_id=user_id, amount=amount, kind=kind, reference=reference, idempotency_key=idempotency_key,
        balance_after=bal, note=note, actor_id=actor_id, created_at=now())).inserted_primary_key[0]
    return {"id": lid, "balance_after": bal}


# ---- metering --------------------------------------------------------------------------------
def reserve(db: Database, user: dict, request_id: str, max_tokens: int, model: str | None = None,
            allow_existing: bool = True) -> dict:
    """Reserve usage. With ``allow_existing=False`` a reused request id raises DuplicateRequest
    (callers that *serve* work must use this so a reused id can't obtain free service)."""
    if max_tokens <= 0:
        raise BillingError("max_tokens must be positive")
    with db.tx() as c:
        existing = c.execute(select(usage_events).where(usage_events.c.request_id == request_id)).mappings().first()
        if existing:
            if existing["user_id"] != user["id"] or not allow_existing:
                raise DuplicateRequest("request id already used")
            return dict(existing)
        base = dict(user_id=user["id"], request_id=request_id, status="reserved", model=model, created_at=now())
        if user["role"] == "owner":  # Owner: unlimited, recorded but never charged
            c.execute(usage_events.insert().values(**base, unmetered=True))
            return dict(c.execute(select(usage_events).where(usage_events.c.request_id == request_id)).mappings().first())
        period = current_period(c, user)
        free_allow = max(0, period["allowance"] - period["used"])
        from_allow = min(max_tokens, free_allow)
        if from_allow:
            res = c.execute(usage_periods.update().where(
                usage_periods.c.id == period["id"], usage_periods.c.used + from_allow <= usage_periods.c.allowance)
                .values(used=usage_periods.c.used + from_allow))
            if res.rowcount != 1:
                raise InsufficientUsage("usage changed concurrently; retry")
        from_credits = max_tokens - from_allow
        if from_credits:
            ledger_entry(c, user["id"], -from_credits, "usage_hold", f"hold:{request_id}", reference=request_id)
        c.execute(usage_events.insert().values(**base, reserved_allowance=from_allow, reserved_credits=from_credits,
                                               period_id=period["id"], unmetered=False))
        return dict(c.execute(select(usage_events).where(usage_events.c.request_id == request_id)).mappings().first())


def settle(db: Database, request_id: str, input_tokens: int, output_tokens: int) -> dict:
    with db.tx() as c:
        ev = c.execute(select(usage_events).where(usage_events.c.request_id == request_id)).mappings().first()
        if not ev:
            raise BillingError("unknown request")
        if ev["status"] != "reserved":
            return dict(ev)  # idempotent
        actual = max(0, int(input_tokens)) + max(0, int(output_tokens))
        if ev["unmetered"]:
            ca = cc = 0
        else:
            ca = min(actual, ev["reserved_allowance"])
            cc = min(actual - ca, ev["reserved_credits"])
            refund_allow = ev["reserved_allowance"] - ca
            refund_credit = ev["reserved_credits"] - cc
            if refund_allow:
                c.execute(usage_periods.update().where(usage_periods.c.id == ev["period_id"])
                          .values(used=usage_periods.c.used - refund_allow))
            if refund_credit:
                ledger_entry(c, ev["user_id"], refund_credit, "usage_release", f"release:{request_id}",
                             reference=request_id)
        res = c.execute(usage_events.update().where(usage_events.c.id == ev["id"], usage_events.c.status == "reserved")
                        .values(status="settled" if actual else "released", input_tokens=input_tokens,
                                output_tokens=output_tokens, charged_allowance=ca, charged_credits=cc,
                                settled_at=now()))
        if res.rowcount != 1:
            raise BillingError("concurrent settlement")
        return dict(c.execute(select(usage_events).where(usage_events.c.id == ev["id"])).mappings().first())


def summary(db: Database, user: dict) -> dict[str, Any]:
    with db.tx() as c:
        period = current_period(c, user)
        sub = active_subscription(c, user["id"])
        plan = plan_row(c, sub["plan_code"] if sub else "free")
        credits = c.execute(select(users.c.credit_balance).where(users.c.id == user["id"])).scalar_one()
    unlimited = user["role"] == "owner"
    remaining = None if unlimited else max(0, period["allowance"] - period["used"])
    return {
        "plan": {"code": plan["code"], "name": plan["name"]}, "unlimited": unlimited,
        "period": {"start": period["period_start"], "end": period["period_end"], "allowance": period["allowance"],
                   "used": period["used"], "remaining": remaining},
        "credits": credits, "renews_at": sub["current_period_end"] if sub else period["period_end"],
        "subscription": {k: sub[k] for k in ("status", "provider", "cancel_at_period_end", "current_period_end")}
        if sub else None,
    }


def transactions(db: Database, user_id: int, limit: int = 100) -> dict[str, list]:
    usage = db.all(select(usage_events).where(usage_events.c.user_id == user_id)
                   .order_by(desc(usage_events.c.created_at)).limit(limit))
    ledger = db.all(select(credit_ledger).where(credit_ledger.c.user_id == user_id)
                    .order_by(desc(credit_ledger.c.id)).limit(limit))
    return {"usage": usage, "ledger": ledger}


def grant_manual_plan(db: Database, user_id: int, plan_code: str, days: int, actor_id: int) -> None:
    t = now()
    with db.tx() as c:
        plan_row(c, plan_code)
        c.execute(subscriptions.update().where(and_(subscriptions.c.user_id == user_id,
                                                    subscriptions.c.provider == "manual",
                                                    subscriptions.c.status == "active")).values(status="canceled",
                                                                                                 updated_at=t))
        if plan_code != "free":
            c.execute(subscriptions.insert().values(user_id=user_id, plan_code=plan_code, status="active",
                                                    provider="manual", current_period_start=t,
                                                    current_period_end=t + days * 86400, cancel_at_period_end=True,
                                                    created_at=t, updated_at=t))
            start_new_period(c, user_id, t, t + days * 86400, plan_code)
        c.execute(users.update().where(users.c.id == user_id).values(plan_code=plan_code))
