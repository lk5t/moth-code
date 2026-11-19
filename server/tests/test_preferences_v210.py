"""2.1: app preferences (size, animations, quiet alerts, sounds) follow the account to other computers."""
from conftest import H, register_verified


def test_preferences_round_trip_and_validation(client, settings):
    tok = register_verified(client, settings)["token"]
    assert client.get("/v1/me/preferences", headers=H(tok)).json() == {"preferences": {}}
    r = client.put("/v1/me/preferences", headers=H(tok), json={"ui_size": "large", "motion": False})
    assert r.json()["preferences"] == {"ui_size": "large", "motion": False}
    client.put("/v1/me/preferences", headers=H(tok), json={"quiet_alerts": True})
    assert client.get("/v1/me/preferences", headers=H(tok)).json()["preferences"] == {"ui_size": "large", "motion": False, "quiet_alerts": True}
    assert client.put("/v1/me/preferences", headers=H(tok), json={"ui_size": "huge"}).status_code == 422
    assert client.get("/v1/me/preferences").status_code == 401
    other = register_verified(client, settings, username="bob")["token"]
    assert client.get("/v1/me/preferences", headers=H(other)).json()["preferences"] == {}  # per account
