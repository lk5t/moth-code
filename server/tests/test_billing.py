import json
import threading
import time

import httpx
import pytest
from sqlalchemy import func, select

from conftest import H, PASSWORD, register_verified, sign_webhook
from moth_server import billing
from moth_server.db import credit_ledger, sessions, usage_periods, users

SECRET = "whsec_test_only"


def user_row(client, username):
    return client.app.state.ctx.db.one(select(users).where(users.c.username_lc == username.lower()))


def ledger_consistent(db, uid):
    total = db.one(select(func.coalesce(func.sum(credit_ledger.c.amount), 0).label("s"))
                   .where(credit_ledger.c.user_id == uid))["s"]
    bal = db.one(select(users.c.credit_balance).where(users.c.id == uid))["credit_balance"]
    return total == bal


def test_plans_are_public_and_checkout_disabled_until_configured(client, settings):
    plans = client.get("/v1/billing/plans").json()
    assert [p["code"] for p in plans] == ["free", "pro", "max"]
    assert all(not p["checkout_available"] for p in plans)
    t = register_verified(client, settings)["token"]
    r = client.post("/v1/billing/checkout", json={"plan": "pro"}, headers=H(t))
    assert r.status_code == 503 and "not available" in r.json()["detail"]


def test_metering_allowance_then_credits_and_no_negative(client, settings):
    register_verified(client, settings, "meter")
    db = client.app.state.ctx.db
    u = user_row(client, "meter")
    with db.tx() as c:
        billing.ledger_entry(c, u["id"], 1000, "admin_adjustment", "seed")
    allowance = billing.summary(db, u)["period"]["allowance"]
    assert allowance == 200_000
    # reserve more than the allowance: the rest comes from credits
    ev = billing.reserve(db, u, "r1", allowance + 500)
    assert ev["reserved_allowance"] == allowance and ev["reserved_credits"] == 500
    assert user_row(client, "meter")["credit_balance"] == 500
    # settle a smaller actual amount: unused hold is returned (allowance first)
    done = billing.settle(db, "r1", 100, allowance + 50)
    assert done["charged_allowance"] == allowance and done["charged_credits"] == 150
    assert user_row(client, "meter")["credit_balance"] == 850
    assert billing.settle(db, "r1", 1, 1)["charged_credits"] == 150  # idempotent
    # not enough left: refused, nothing changes
    with pytest.raises(billing.InsufficientUsage):
        billing.reserve(db, u, "r2", 10_000)
    assert user_row(client, "meter")["credit_balance"] == 850
    assert ledger_consistent(db, u["id"])
    # same request id is never charged twice
    a = billing.reserve(db, u, "r3", 100)
    b = billing.reserve(db, u, "r3", 100)
    assert a["id"] == b["id"] and user_row(client, "meter")["credit_balance"] == 750


def test_concurrent_reservations_never_overspend(client, settings):
    register_verified(client, settings, "race")
    db = client.app.state.ctx.db
    u = user_row(client, "race")
    with db.tx() as c:
        c.execute(usage_periods.update().values(allowance=0))
        billing.current_period(c, u)
        c.execute(usage_periods.update().where(usage_periods.c.user_id == u["id"]).values(allowance=0))
        billing.ledger_entry(c, u["id"], 1000, "admin_adjustment", "seed-race")
    ok, fail = [], []

    def worker(i):
        try:
            billing.reserve(db, u, f"race-{i}", 100)
            ok.append(i)
        except billing.InsufficientUsage:
            fail.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 10 and len(fail) == 15
    assert user_row(client, "race")["credit_balance"] == 0 and ledger_consistent(db, u["id"])


def test_period_rollover(client, settings):
    register_verified(client, settings, "roll")
    db = client.app.state.ctx.db
    u = user_row(client, "roll")
    billing.reserve(db, u, "p1", 1000)
    with db.tx() as c:
        c.execute(usage_periods.update().where(usage_periods.c.user_id == u["id"])
                  .values(period_start=time.time() - 40 * 86400, period_end=time.time() - 10 * 86400))
    s = billing.summary(db, u)
    assert s["period"]["used"] == 0 and s["period"]["remaining"] == 200_000


def test_owner_is_unlimited_and_unmetered(client, owner):
    db = client.app.state.ctx.db
    u = user_row(client, "lk5t")
    ev = billing.reserve(db, u, "own-1", 10**10)
    assert ev["unmetered"] and ev["reserved_credits"] == 0
    billing.settle(db, "own-1", 5, 5)
    s = client.get("/v1/billing/summary", headers=H(owner["token"])).json()
    assert s["unlimited"] is True and s["period"]["used"] == 0
    assert client.post("/v1/billing/checkout", json={"plan": "pro"}, headers=H(owner["token"])).status_code == 400


def test_admin_credit_adjustments_require_owner_and_reauth(client, settings, owner):
    t = register_verified(client, settings, "carl")["token"]
    uid = user_row(client, "carl")["id"]
    assert client.post(f"/v1/admin/users/{uid}/credits", json={"amount": 500, "reason": "gift"},
                       headers=H(t)).status_code == 403  # normal users cannot
    r = client.post(f"/v1/admin/users/{uid}/credits", json={"amount": 500, "reason": "launch gift",
                                                          "idempotency_key": "g1"}, headers=H(owner["token"]))
    assert r.status_code == 200 and r.json()["balance_after"] == 500
    dup = client.post(f"/v1/admin/users/{uid}/credits", json={"amount": 500, "reason": "launch gift",
                                                            "idempotency_key": "g1"}, headers=H(owner["token"]))
    assert dup.json() == {"duplicate": True} and user_row(client, "carl")["credit_balance"] == 500
    assert client.post(f"/v1/admin/users/{uid}/credits", json={"amount": -900, "reason": "too much"},
                       headers=H(owner["token"])).status_code == 422
    # stale re-authentication → 428 until the owner confirms the password again
    db = client.app.state.ctx.db
    with db.tx() as c:
        c.execute(sessions.update().values(reauth_at=0))
    assert client.post(f"/v1/admin/users/{uid}/credits", json={"amount": 1, "reason": "x y z"},
                       headers=H(owner["token"])).status_code == 428
    assert client.post("/v1/auth/reauth", json={"password": "crimson wings 2026!"},
                       headers=H(owner["token"])).status_code == 200
    assert client.post(f"/v1/admin/users/{uid}/credits", json={"amount": 1, "reason": "x y z"},
                       headers=H(owner["token"])).status_code == 200
    tx = client.get("/v1/billing/transactions", headers=H(t)).json()
    assert [e["amount"] for e in tx["ledger"]] == [1, 500]


def test_owner_role_cannot_be_assigned_and_plans_are_owner_editable(client, settings, owner):
    t = register_verified(client, settings, "dana")["token"]
    uid = user_row(client, "dana")["id"]
    o = H(owner["token"])
    assert client.post(f"/v1/admin/users/{uid}/role", json={"role": "owner"}, headers=o).status_code == 422
    assert client.post(f"/v1/admin/users/{owner['user']['id']}/role", json={"role": "user"}, headers=o).status_code == 403
    assert client.post(f"/v1/admin/users/{owner['user']['id']}/status", json={"status": "suspended"},
                       headers=o).status_code == 403
    assert client.put("/v1/admin/plans/pro", json={"monthly_tokens": 1}, headers=H(t)).status_code == 403
    r = client.put("/v1/admin/plans/pro", json={"monthly_tokens": 7_000_000, "price_cents": 1900}, headers=o)
    assert r.status_code == 200 and r.json()["monthly_tokens"] == 7_000_000
    # complimentary plan grant gives the new allowance immediately
    s = client.post(f"/v1/admin/users/{uid}/plan", json={"plan": "pro", "days": 30}, headers=o).json()
    assert s["plan"]["code"] == "pro" and s["period"]["allowance"] == 7_000_000
    # suspension revokes sessions
    assert client.post(f"/v1/admin/users/{uid}/status", json={"status": "suspended"}, headers=o).status_code == 200
    assert client.get("/v1/me", headers=H(t)).status_code == 401
    log = client.app.state.ctx.db.all(select(__import__("moth_server.db", fromlist=["audit_log"]).audit_log))
    assert {"admin.plan_updated", "admin.plan_granted", "admin.status_changed"} <= {e["action"] for e in log}


def _webhook(client, event, secret=SECRET, ts=None):
    payload = json.dumps(event).encode()
    return client.post("/v1/billing/webhook", content=payload,
                       headers={"stripe-signature": sign_webhook(payload, secret, ts)})


@pytest.fixture
def paid_settings(settings):
    settings.stripe_secret_key = "sk_test_only"
    settings.stripe_webhook_secret = SECRET
    return settings


def test_webhooks_subscription_lifecycle(paid_settings, client):
    settings = paid_settings
    register_verified(client, settings, "paula")
    uid = user_row(client, "paula")["id"]
    db = client.app.state.ctx.db
    with db.tx() as c:
        from moth_server.db import plans
        c.execute(plans.update().where(plans.c.code == "pro").values(provider_price_id="price_pro"))
    t0 = int(time.time())
    sub = {"id": "sub_1", "customer": "cus_1", "status": "active", "metadata": {"user_id": str(uid)},
           "items": {"data": [{"price": {"id": "price_pro"}}]}, "current_period_start": t0,
           "current_period_end": t0 + 30 * 86400, "cancel_at_period_end": False}
    # bad signature / stale timestamp / wrong secret are rejected
    assert client.post("/v1/billing/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=00"}).status_code == 400
    assert _webhook(client, {"id": "evt_0", "type": "x"}, ts=t0 - 3600).status_code == 400
    assert _webhook(client, {"id": "evt_0", "type": "x"}, secret="whsec_wrong").status_code == 400
    assert _webhook(client, {"id": "evt_1", "type": "customer.subscription.created", "data": {"object": sub}}).json() == \
        {"outcome": "subscription active (pro)"}
    assert user_row(client, "paula")["plan_code"] == "pro"
    assert _webhook(client, {"id": "evt_1", "type": "customer.subscription.created",
                             "data": {"object": sub}}).json()["outcome"] == "duplicate"
    inv = {"id": "in_1", "subscription": "sub_1", "amount_paid": 1500,
           "lines": {"data": [{"period": {"start": t0, "end": t0 + 30 * 86400}}]}}
    assert _webhook(client, {"id": "evt_2", "type": "invoice.paid", "data": {"object": inv}}).json()["outcome"] == "renewed"
    s = billing.summary(db, user_row(client, "paula"))
    assert s["plan"]["code"] == "pro" and s["period"]["allowance"] == 5_000_000
    assert _webhook(client, {"id": "evt_3", "type": "invoice.payment_failed",
                             "data": {"object": {"subscription": "sub_1"}}}).json()["outcome"] == "past_due"
    assert billing.summary(db, user_row(client, "paula"))["subscription"]["status"] == "past_due"
    assert _webhook(client, {"id": "evt_4", "type": "customer.subscription.deleted",
                             "data": {"object": {**sub, "status": "canceled"}}}).status_code == 200
    assert user_row(client, "paula")["plan_code"] == "free"
    assert billing.summary(db, user_row(client, "paula"))["plan"]["code"] == "free"


def test_checkout_uses_provider_without_card_data(paid_settings, client):
    settings = paid_settings
    t = register_verified(client, settings, "quinn")["token"]
    seen = {}

    def handler(request: httpx.Request):
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode()
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"id": "cs_1", "url": "https://checkout.example/cs_1"})

    from moth_server.payments import StripeProvider

    ctx = client.app.state.ctx
    ctx.extras["payment_provider"] = StripeProvider(ctx, httpx.Client(transport=httpx.MockTransport(handler)))
    from moth_server.db import plans
    with ctx.db.tx() as c:
        c.execute(plans.update().where(plans.c.code == "pro").values(provider_price_id="price_pro", checkout_enabled=True))
    assert client.get("/v1/billing/plans").json()[1]["checkout_available"] is True
    r = client.post("/v1/billing/checkout", json={"plan": "pro"}, headers=H(t))
    assert r.status_code == 200 and r.json()["url"] == "https://checkout.example/cs_1"
    assert seen["url"].endswith("/v1/checkout/sessions") and "price_pro" in seen["body"]
    assert "card" not in seen["body"] and seen["auth"].startswith("Basic ")
    assert client.post("/v1/billing/checkout", json={"plan": "free"}, headers=H(t)).status_code == 503


def test_metered_cloud_inference(client, settings, owner, tiny_model_dir):
    from moth.inference.local import LocalInference

    ctx = client.app.state.ctx
    assert client.get("/cloud/v1/health").json()["models"] == []
    t = register_verified(client, settings, "cloudy")["token"]
    body = {"model": "moth-cloud-test", "messages": [{"role": "user", "content": "def add("}],
            "params": {"max_new_tokens": 8, "temperature": 0.0}}
    assert client.post("/cloud/v1/chat", json=body, headers=H(t)).status_code == 503  # not available yet
    engine = LocalInference(tiny_model_dir.parent)
    engine.load(tiny_model_dir.name, "cpu")
    ctx.extras["inference_engine"] = engine
    assert client.post("/cloud/v1/chat", json=body, headers=H(t)).status_code == 503  # flag still off
    client.put("/v1/admin/config/flags", json={"cloud_inference_enabled": True}, headers=H(owner["token"]))
    assert client.get("/cloud/v1/health").json()["models"][0]["architecture"] == "moth-decoder-v1"
    assert client.post("/cloud/v1/chat", json=body).status_code == 401
    r = client.post("/cloud/v1/chat", json=body, headers={**H(t), "X-Request-Id": "req-1"})
    lines = [json.loads(l) for l in r.text.splitlines()]
    stats = lines[-1]["stats"]
    used = stats["prompt_tokens"] + stats["generated_tokens"]
    summary = client.get("/v1/billing/summary", headers=H(t)).json()
    assert summary["period"]["used"] == used > 0  # exactly the real tokens, not the reservation
    # a reused request id is refused: neither charged twice nor served for free
    assert client.post("/cloud/v1/chat", json=body, headers={**H(t), "X-Request-Id": "req-1"}).status_code == 409
    assert client.get("/v1/billing/summary", headers=H(t)).json()["period"]["used"] == used
    # out of allowance → 402
    with ctx.db.tx() as c:
        c.execute(usage_periods.update().values(used=usage_periods.c.allowance))
    assert client.post("/cloud/v1/chat", json=body, headers=H(t)).status_code == 402
