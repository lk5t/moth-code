"""0.7.1: Owner-only notifications, enforced by the server."""
from conftest import H, register_verified
from moth_server.evolution import memory as MEM


def test_owner_sees_important_events_and_marks_them_read(client, owner):
    ctx = client.app.state.ctx
    MEM.event(ctx, "cycle.completed", "v7 passed monitoring and is the new stable model (MOTH 0.0.3)")
    MEM.event(ctx, "worker.disconnected", "Worker gpu-1 stopped reporting", level="warning")
    MEM.event(ctx, "checkpoint.saved", "routine checkpoint")  # routine: not a notification
    r = client.get("/v1/admin/notifications", headers=H(owner["token"]))
    assert r.status_code == 200
    data = r.json()
    kinds = [n["kind"] for n in data["items"]]
    assert kinds == ["worker.disconnected", "cycle.completed"] and data["unread"] == 2
    assert data["items"][1]["title"] == "New MOTH version promoted" and "MOTH 0.0.3" in data["items"][1]["message"]
    read = client.post("/v1/admin/notifications/read", json={"up_to_id": data["items"][0]["id"]},
                       headers=H(owner["token"])).json()
    assert read["unread"] == 0
    MEM.event(ctx, "deploy.rollback", "v8 was rolled back to v7: error rate 9%", level="error")
    after = client.get("/v1/admin/notifications", headers=H(owner["token"])).json()
    assert after["unread"] == 1 and after["items"][0]["category"] == "rollback"


def test_other_accounts_cannot_read_or_acknowledge_notifications(client, settings, owner):
    MEM.event(client.app.state.ctx, "deploy.failed", "Deploying v9 failed")
    user = register_verified(client, settings, "notify-user")
    assert client.get("/v1/admin/notifications", headers=H(user["token"])).status_code == 403
    assert client.post("/v1/admin/notifications/read", json={"up_to_id": 10**9},
                       headers=H(user["token"])).status_code == 403
    assert client.get("/v1/admin/notifications").status_code == 401
    assert client.get("/v1/admin/notifications", headers=H(owner["token"])).json()["unread"] == 1
