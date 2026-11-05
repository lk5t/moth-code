import json
import time

import pytest
from sqlalchemy import select

from conftest import H, register_verified, sign_webhook
from moth_server import referrals as R
from moth_server.db import credit_ledger, plans, referral_rewards, referrals, users

SECRET = "whsec_test_only"


@pytest.fixture
def paid_settings(settings):
    settings.stripe_secret_key = "sk_test_only"
    settings.stripe_webhook_secret = SECRET
    return settings


def uid_of(client, name):
    return client.app.state.ctx.db.one(select(users.c.id).where(users.c.username_lc == name.lower()))["id"]


def credits(client, name):
    return client.app.state.ctx.db.one(select(users.c.credit_balance).where(users.c.username_lc == name.lower()))[
        "credit_balance"]


def hook(client, event):
    payload = json.dumps(event).encode()
    r = client.post("/v1/billing/webhook", content=payload, headers={"stripe-signature": sign_webhook(payload, SECRET)})
    assert r.status_code == 200, r.text
    return r.json()["outcome"]


def subscribe_and_pay(client, name, n=1, amount=1500):
    uid = uid_of(client, name)
    t0 = int(time.time())
    sub = {"id": f"sub_{name}", "customer": f"cus_{name}", "status": "active", "metadata": {"user_id": str(uid)},
           "items": {"data": [{"price": {"id": "price_pro"}}]}, "current_period_start": t0,
           "current_period_end": t0 + 30 * 86400}
    hook(client, {"id": f"evt_sub_{name}", "type": "customer.subscription.created", "data": {"object": sub}})
    for i in range(n):
        hook(client, {"id": f"evt_inv_{name}_{i}", "type": "invoice.paid", "data": {"object": {
            "id": f"in_{name}_{i}", "subscription": f"sub_{name}", "amount_paid": amount,
            "lines": {"data": [{"period": {"start": t0 + i * 30 * 86400, "end": t0 + (i + 1) * 30 * 86400}}]}}}})


@pytest.fixture
def world(paid_settings, client, owner):
    db = client.app.state.ctx.db
    with db.tx() as c:
        c.execute(plans.update().where(plans.c.code == "pro").values(provider_price_id="price_pro"))
    alice = register_verified(client, paid_settings, "alice")
    # the test client always uses one IP; disable the same-IP hold except where tested
    client.put("/v1/admin/referral-rules", json={"hold_same_ip_for_review": False}, headers=H(owner["token"]))
    return {"alice": alice, "code": alice["user"]["referral_code"], "owner": owner, "settings": paid_settings}


def test_no_reward_for_registration_only(client, world):
    register_verified(client, world["settings"], "bob", referral_code=world["code"].lower())
    db = client.app.state.ctx.db
    ref = db.one(select(referrals))
    assert ref["status"] == "registered" and ref["referrer_id"] == uid_of(client, "alice")
    assert db.one(select(users.c.referred_by).where(users.c.id == uid_of(client, "bob")))["referred_by"] == ref["referrer_id"]
    R.process_pending(db, time.time() + 365 * 86400)
    assert credits(client, "alice") == 0 and db.all(select(referral_rewards)) == []


def test_paid_referral_reward_pending_then_credited_once(client, world):
    db = client.app.state.ctx.db
    register_verified(client, world["settings"], "carl", referral_code=world["code"])
    subscribe_and_pay(client, "carl", n=2)  # two invoices → only the first qualifies
    rewards = db.all(select(referral_rewards))
    assert len(rewards) == 1 and rewards[0]["status"] == "pending" and rewards[0]["amount"] == 500_000
    assert R.process_pending(db) == {"credited": 0, "capped": 0}  # still in the pending period
    assert R.process_pending(db, time.time() + 15 * 86400)["credited"] == 1
    assert R.process_pending(db, time.time() + 15 * 86400)["credited"] == 0  # idempotent
    assert credits(client, "alice") == 500_000
    assert db.one(select(referrals.c.status))["status"] == "rewarded"
    dash = client.get("/v1/referrals", headers=H(world["alice"]["token"])).json()
    assert dash["stats"]["earned_tokens"] == 500_000 and dash["referrals"][0]["user"].startswith("ca")
    assert "carl" not in json.dumps(dash["referrals"])  # referred usernames are masked
    assert dash["link"].endswith(f"/r/{world['code']}")


def test_refund_reverses_reward_with_ledger_clawback(client, world):
    db = client.app.state.ctx.db
    register_verified(client, world["settings"], "dina", referral_code=world["code"])
    subscribe_and_pay(client, "dina")
    R.process_pending(db, time.time() + 15 * 86400)
    assert credits(client, "alice") == 500_000
    hook(client, {"id": "evt_refund", "type": "charge.refunded", "data": {"object": {"id": "ch_1", "invoice": "in_dina_0"}}})
    assert credits(client, "alice") == 0
    assert db.one(select(referral_rewards.c.status))["status"] == "reversed"
    kinds = [r["kind"] for r in db.all(select(credit_ledger).where(credit_ledger.c.user_id == uid_of(client, "alice")))]
    assert kinds == ["referral_reward", "reversal"]


def test_refund_during_pending_period_cancels_reward(client, world):
    db = client.app.state.ctx.db
    register_verified(client, world["settings"], "emil", referral_code=world["code"])
    subscribe_and_pay(client, "emil")
    hook(client, {"id": "evt_dispute", "type": "charge.dispute.created", "data": {"object": {"id": "dp", "invoice": "in_emil_0"}}})
    R.process_pending(db, time.time() + 30 * 86400)
    assert credits(client, "alice") == 0 and db.one(select(referral_rewards.c.status))["status"] == "reversed"


def test_monthly_cap(client, world):
    db = client.app.state.ctx.db
    client.put("/v1/admin/referral-rules", json={"max_user_rewards_per_month": 1}, headers=H(world["owner"]["token"]))
    for name in ("fred", "gina"):
        register_verified(client, world["settings"], name, referral_code=world["code"])
        subscribe_and_pay(client, name)
    assert R.process_pending(db, time.time() + 15 * 86400) == {"credited": 1, "capped": 1}
    assert credits(client, "alice") == 500_000


def test_same_ip_referral_held_for_owner_review(client, world):
    db = client.app.state.ctx.db
    o = H(world["owner"]["token"])
    client.put("/v1/admin/referral-rules", json={"hold_same_ip_for_review": True}, headers=o)
    register_verified(client, world["settings"], "hank", referral_code=world["code"])
    ref = db.one(select(referrals))
    assert ref["status"] == "review" and "same_ip_as_referrer" in ref["flags"]
    subscribe_and_pay(client, "hank")
    assert db.one(select(referral_rewards.c.status))["status"] == "review"
    assert R.process_pending(db, time.time() + 30 * 86400)["credited"] == 0  # held, not paid
    listing = client.get("/v1/admin/referrals", headers=o).json()
    assert listing["referrals"][0]["referrer"] == "alice"
    alice_token = H(world["alice"]["token"])
    assert client.post(f"/v1/admin/referrals/{ref['id']}/approve", headers=alice_token).status_code == 403
    assert client.post(f"/v1/admin/referrals/{ref['id']}/approve", headers=o).status_code == 200
    assert R.process_pending(db, time.time() + 30 * 86400)["credited"] == 1
    assert credits(client, "alice") == 500_000


def test_invalid_codes_and_suspended_referrers_are_ignored(client, world):
    db = client.app.state.ctx.db
    register_verified(client, world["settings"], "ivan", referral_code="NOPE1234")
    assert db.all(select(referrals)) == []
    o = H(world["owner"]["token"])
    client.post(f"/v1/admin/users/{uid_of(client, 'alice')}/status", json={"status": "suspended"}, headers=o)
    client.app.state.ctx.limiter.clear("register:ip:testclient")
    register_verified(client, world["settings"], "jane", referral_code=world["code"])
    assert db.all(select(referrals)) == []


def test_share_page(client, world):
    r = client.get(f"/r/{world['code']}")
    assert r.status_code == 200 and world["code"] in r.text
    assert "not valid" in client.get("/r/ZZZZZZZZ").text
