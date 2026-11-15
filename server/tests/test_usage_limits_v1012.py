"""1.0.12: rolling 5-hour and weekly limits per plan, shown as percentages."""
import pytest

from moth_server import billing


def test_free_plan_session_limit_blocks_and_reports_percent(client, settings):
    from conftest import H, register_verified
    from sqlalchemy import select
    from moth_server.db import users
    ctx = client.app.state.ctx
    login = register_verified(client, settings, "lim")
    with ctx.db.tx() as c:  # no credits: the limits decide
        c.execute(users.update().where(users.c.username == "lim").values(credit_balance=0))
    u = dict(ctx.db.one(select(users).where(users.c.username == "lim")))
    billing.reserve(ctx.db, u, "a", 15_000)
    billing.settle(ctx.db, "a", 5_000, 10_000)
    with ctx.db.tx() as c:
        lim = billing.limits(c, u)
    assert lim["session"]["percent"] == 75.0 and lim["weekly"]["percent"] == pytest.approx(18.8, abs=0.1)
    assert lim["session"]["resets_at"] is not None
    with pytest.raises(billing.InsufficientUsage) as e:
        billing.reserve(ctx.db, u, "b", 10_000)  # 15k + 10k > 20k, and no credits
    assert e.value.reason == "session" and "5-hour" in e.value.user_message()
    billing.reserve(ctx.db, u, "c", 5_000)  # what is left still works
    api = client.get("/v1/billing/limits", headers=H(login["token"])).json()
    assert api["session"]["percent"] == 100.0 and api["plan"] == "free" and not api["unlimited"]
