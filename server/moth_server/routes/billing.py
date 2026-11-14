"""Plans, usage summary, transactions, checkout and payment webhooks."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select

from moth_server import billing
from moth_server.context import Ctx, get_ctx
from moth_server.db import plans, subscriptions
from moth_server.deps import Auth, current_auth
from moth_server.payments import PaymentsUnavailable, StripeProvider, WebhookError, handle_event, parse_and_verify

router = APIRouter(prefix="/v1/billing", tags=["billing"])


def setup(ctx: Ctx) -> None:
    billing.seed_plans(ctx.db)


def provider(ctx: Ctx) -> StripeProvider:
    return ctx.extras.get("payment_provider") or StripeProvider(ctx)


class CheckoutIn(BaseModel):
    plan: str


def public_plan(p: dict, ctx: Ctx) -> dict:
    return {"code": p["code"], "name": p["name"], "price_cents": p["price_cents"], "currency": p["currency"],
            "interval": p["interval"], "monthly_tokens": p["monthly_tokens"], "priority": p["priority"],
            "features": json.loads(p["features"] or "{}"),
            "checkout_available": bool(ctx.settings.payments_configured and p["checkout_enabled"]
                                       and p["provider_price_id"] and p["code"] != "free")}


@router.get("/plans")
def list_plans(ctx: Ctx = Depends(get_ctx)):
    return [public_plan(p, ctx) for p in ctx.db.all(select(plans).order_by(plans.c.sort))]


@router.get("/summary")
def usage_summary(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    return billing.summary(ctx.db, auth.user)


@router.get("/usage-daily")
def usage_daily(days: int = 30, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """1.0 usage page: tokens used per day (settled requests) for the last ``days`` days."""
    import datetime as _dt

    from moth_server.db import now as _now, usage_events

    days = min(max(days, 1), 90)
    since = _now() - days * 86400
    rows = ctx.db.all(select(usage_events.c.settled_at, usage_events.c.input_tokens, usage_events.c.output_tokens)
                      .where(usage_events.c.user_id == auth.uid, usage_events.c.status == "settled",
                             usage_events.c.settled_at >= since))
    per: dict[str, int] = {}
    for r in rows:
        day = _dt.datetime.fromtimestamp(float(r["settled_at"]), _dt.timezone.utc).strftime("%Y-%m-%d")
        per[day] = per.get(day, 0) + int(r["input_tokens"] or 0) + int(r["output_tokens"] or 0)
    today = _dt.datetime.now(_dt.timezone.utc).date()
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - _dt.timedelta(days=i)).isoformat()
        out.append({"day": d, "tokens": per.get(d, 0)})
    return out


@router.get("/transactions")
def list_transactions(limit: int = 100, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    return billing.transactions(ctx.db, auth.uid, min(max(limit, 1), 500))


@router.post("/checkout")
def checkout(body: CheckoutIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    if auth.is_owner:
        raise HTTPException(400, "The owner account has unlimited usage and needs no subscription.")
    if auth.user["email_verified_at"] is None:
        raise HTTPException(403, "Verify your email address first.")
    try:
        return {"url": provider(ctx).checkout(auth.user, body.plan)}
    except PaymentsUnavailable as e:
        raise HTTPException(503, str(e)) from None


@router.post("/portal")
def portal(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    sub = ctx.db.one(select(subscriptions).where(subscriptions.c.user_id == auth.uid, subscriptions.c.provider == "stripe",
                                                 subscriptions.c.provider_customer_id.is_not(None)))
    if not sub:
        raise HTTPException(404, "No paid subscription found.")
    try:
        return {"url": provider(ctx).portal(sub["provider_customer_id"])}
    except PaymentsUnavailable as e:
        raise HTTPException(503, str(e)) from None


@router.post("/subscription/cancel")
def cancel(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    sub = ctx.db.one(select(subscriptions).where(subscriptions.c.user_id == auth.uid, subscriptions.c.provider == "stripe",
                                                 subscriptions.c.status.in_(("active", "trialing", "past_due"))))
    if not sub:
        raise HTTPException(404, "No active paid subscription.")
    try:
        provider(ctx).cancel_at_period_end(sub["provider_subscription_id"])
    except PaymentsUnavailable as e:
        raise HTTPException(503, str(e)) from None
    # The provider's subscription.updated webhook confirms the change; reflect it immediately too.
    with ctx.db.tx() as c:
        c.execute(subscriptions.update().where(subscriptions.c.id == sub["id"]).values(cancel_at_period_end=True))
    return {"ok": True, "access_until": sub["current_period_end"]}


@router.post("/webhook")
async def webhook(request: Request, ctx: Ctx = Depends(get_ctx)):
    payload = await request.body()
    try:
        event = parse_and_verify(ctx, payload, request.headers.get("stripe-signature", ""))
    except PaymentsUnavailable as e:
        raise HTTPException(503, str(e)) from None
    except WebhookError as e:
        raise HTTPException(400, f"invalid webhook: {e}") from None
    return {"outcome": handle_event(ctx, event)}
