from conftest import H, register_verified


def test_dashboard_is_owner_only_and_complete(client, settings, owner):
    t = register_verified(client, settings, "someone")["token"]
    for path in ("/v1/admin/overview", "/v1/admin/users", "/v1/admin/workers", "/v1/admin/jobs", "/v1/admin/audit",
                 "/v1/admin/models", "/v1/admin/policy", "/v1/admin/config", "/v1/admin/referrals"):
        assert client.get(path, headers=H(t)).status_code == 403, path
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers=H(owner["token"])).status_code == 200, path
    o = client.get("/v1/admin/overview", headers=H(owner["token"])).json()
    assert o["users"]["total"] == 2 and o["users"]["by_plan"]["free"] == 2
    assert o["system"]["database"] in ("sqlite", "postgresql") and o["system"]["email"] == "outbox"
    assert o["models"]["deployed"] is None and o["training"]["configured"] is False
    users = client.get("/v1/admin/users?q=some", headers=H(owner["token"])).json()
    assert [u["username"] for u in users] == ["someone"] and "password_hash" not in users[0]
    detail = client.get(f"/v1/admin/users/{users[0]['id']}", headers=H(owner["token"])).json()
    assert "password_hash" not in detail["user"] and detail["summary"]["plan"]["code"] == "free"
    audit = client.get("/v1/admin/audit?action=auth.", headers=H(owner["token"])).json()
    assert {"auth.register", "auth.login"} <= {a["action"] for a in audit}
