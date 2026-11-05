"""Subscription billing through Stripe (REST API; no card data ever touches MOTH servers).

Checkout and the customer portal are hosted by the payment processor. Everything stays
disabled (HTTP 503) until ``MOTH_STRIPE_SECRET_KEY`` and ``MOTH_STRIPE_WEBHOOK_SECRET`` are
configured *and* the owner has set a provider price id and enabled checkout for a plan.

Webhooks are verified with the ``Stripe-Signature`` HMAC-SHA256 scheme (timestamped, 5-minute
tolerance) and de-duplicated by event id, so retries are processed exactly once.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

import httpx
from sqlalchemy import select

from moth_server.audit import audit
from moth_server.billing import start_new_period
from moth_server.context import Ctx
from moth_server.db import now, payment_events, plans, subscriptions, users
from moth_server.hooks import run_hook

SIGNATURE_TOLERANCE = 300


class PaymentsUnavailable(Exception):
    pass


class WebhookError(ValueError):
    pass


def verify_signature(payload: bytes, header: str, secret: str, tolerance: int = SIGNATURE_TOLERANCE,
                     t_now: float | None = None) -> None:
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    sigs = [v for k, v in (p.split("=", 1) for p in header.split(",") if "=" in p) if k == "v1"]
    try:
        ts = int(parts.get("t", ""))
    except ValueError:
        raise WebhookError("missing timestamp") from None
    if abs((t_now or time.time()) - ts) > tolerance:
        raise WebhookError("timestamp outside tolerance")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise WebhookError("signature mismatch")


class StripeProvider:
    def __init__(self, ctx: Ctx, http: httpx.Client | None = None):
        self.ctx = ctx
        self.http = http or httpx.Client(timeout=30)

    def _post(self, path: str, data: dict[str, Any]) -> dict:
        s = self.ctx.settings
        if not s.payments_configured:
            raise PaymentsUnavailable("Paid plans are not available yet.")
        r = self.http.post(s.stripe_api_base + path, data=data, auth=(s.stripe_secret_key, ""))
        if r.status_code >= 400:
            raise PaymentsUnavailable(f"payment provider error ({r.status_code})")
        return r.json()

    def checkout(self, user: dict, plan_code: str) -> str:
        plan = self.ctx.db.one(select(plans).where(plans.c.code == plan_code))
        if not plan or plan["code"] == "free" or not plan["checkout_enabled"] or not plan["provider_price_id"]:
            raise PaymentsUnavailable("This plan is not available for purchase yet.")
        base = self.ctx.settings.public_url
        session = self._post("/v1/checkout/sessions", {
            "mode": "subscription",
            "line_items[0][price]": plan["provider_price_id"], "line_items[0][quantity]": "1",
            "success_url": f"{base}/billing/success", "cancel_url": f"{base}/billing/cancelled",
            "client_reference_id": str(user["id"]), "customer_email": user["email"],
            "subscription_data[metadata][user_id]": str(user["id"]),
            "subscription_data[metadata][plan_code]": plan["code"],
            "metadata[user_id]": str(user["id"]),
        })
        return session["url"]

    def portal(self, customer_id: str) -> str:
        return self._post("/v1/billing_portal/sessions", {"customer": customer_id,
                                                          "return_url": self.ctx.settings.public_url})["url"]

    def cancel_at_period_end(self, subscription_id: str) -> None:
        self._post(f"/v1/subscriptions/{subscription_id}", {"cancel_at_period_end": "true"})


def _plan_for_price(conn, price_id: str | None, fallback: str | None) -> str:
    if price_id:
        row = conn.execute(select(plans.c.code).where(plans.c.provider_price_id == price_id)).first()
        if row:
            return row[0]
    return fallback or "free"


def handle_event(ctx: Ctx, event: dict) -> str:
    """Apply one verified webhook event. Returns an outcome string."""
    db = ctx.db
    eid, etype = event.get("id"), event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    if not eid:
        raise WebhookError("missing event id")
    with db.tx() as c:
        if c.execute(select(payment_events.c.id).where(payment_events.c.id == eid)).first():
            return "duplicate"
        c.execute(payment_events.insert().values(id=eid, type=etype, received_at=now()))
        outcome = "ignored"
        if etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
            uid = int((obj.get("metadata") or {}).get("user_id") or 0)
            existing = c.execute(select(subscriptions).where(subscriptions.c.provider_subscription_id == obj["id"])
                                 ).mappings().first()
            uid = uid or (existing["user_id"] if existing else 0)
            if not uid or not c.execute(select(users.c.id).where(users.c.id == uid)).first():
                outcome = "unknown user"
            else:
                items = (obj.get("items") or {}).get("data") or [{}]
                code = _plan_for_price(c, ((items[0].get("price") or {}).get("id")),
                                       (obj.get("metadata") or {}).get("plan_code"))
                status = "canceled" if etype.endswith("deleted") else obj.get("status", "incomplete")
                values = dict(user_id=uid, plan_code=code, status=status, provider="stripe",
                              provider_customer_id=obj.get("customer"),
                              current_period_start=obj.get("current_period_start"),
                              current_period_end=obj.get("current_period_end"),
                              cancel_at_period_end=bool(obj.get("cancel_at_period_end")), updated_at=now())
                if existing:
                    c.execute(subscriptions.update().where(subscriptions.c.id == existing["id"]).values(**values))
                else:
                    c.execute(subscriptions.insert().values(**values, provider_subscription_id=obj["id"],
                                                            created_at=now()))
                entitled = status in ("active", "trialing", "past_due")
                c.execute(users.update().where(users.c.id == uid).values(plan_code=code if entitled else "free"))
                outcome = f"subscription {status} ({code})"
        elif etype in ("invoice.paid", "invoice.payment_succeeded"):
            sub = c.execute(select(subscriptions).where(subscriptions.c.provider_subscription_id == obj.get("subscription"))
                            ).mappings().first()
            if not sub:
                outcome = "unknown subscription"
            else:
                lines = (obj.get("lines") or {}).get("data") or [{}]
                period = lines[0].get("period") or {}
                start = period.get("start") or obj.get("period_start") or now()
                end = period.get("end") or obj.get("period_end") or start + 30 * 86400
                c.execute(subscriptions.update().where(subscriptions.c.id == sub["id"])
                          .values(status="active", current_period_start=start, current_period_end=end,
                                  updated_at=now()))
                c.execute(users.update().where(users.c.id == sub["user_id"]).values(plan_code=sub["plan_code"]))
                start_new_period(c, sub["user_id"], float(start), float(end), sub["plan_code"])
                run_hook(ctx, "payment_succeeded", conn=c, user_id=sub["user_id"], amount=obj.get("amount_paid", 0),
                         reference=obj.get("id") or eid, plan_code=sub["plan_code"])
                outcome = "renewed"
        elif etype == "invoice.payment_failed":
            res = c.execute(subscriptions.update().where(subscriptions.c.provider_subscription_id == obj.get("subscription"))
                            .values(status="past_due", updated_at=now()))
            outcome = "past_due" if res.rowcount else "unknown subscription"
        elif etype in ("charge.refunded", "charge.dispute.created"):
            run_hook(ctx, "payment_reversed", conn=c, reference=obj.get("invoice") or obj.get("id"), event_type=etype)
            outcome = "reversal processed"
        c.execute(payment_events.update().where(payment_events.c.id == eid).values(processed_at=now(), outcome=outcome))
        audit(db, "billing.webhook", None, f"event:{eid}", {"type": etype, "outcome": outcome}, conn=c)
        return outcome


def parse_and_verify(ctx: Ctx, payload: bytes, signature: str) -> dict:
    secret = ctx.settings.stripe_webhook_secret
    if not secret:
        raise PaymentsUnavailable("webhooks are not configured")
    verify_signature(payload, signature or "", secret)
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        raise WebhookError("invalid JSON") from None
