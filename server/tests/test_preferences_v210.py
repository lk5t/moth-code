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


def test_theme_accent_and_saved_prompts_follow_the_account(client, settings):
    tok = register_verified(client, settings)["token"]
    r = client.put("/v1/me/preferences", headers=H(tok), json={"theme": "midnight", "accent": "blue", "saved_prompts": ["Explain this error", "Write tests for this"]})
    assert r.json()["preferences"] == {"theme": "midnight", "accent": "blue", "saved_prompts": ["Explain this error", "Write tests for this"]}
    assert client.get("/v1/me/preferences", headers=H(tok)).json()["preferences"]["saved_prompts"][1] == "Write tests for this"
    assert client.put("/v1/me/preferences", headers=H(tok), json={"theme": "neon"}).status_code == 422
    assert client.put("/v1/me/preferences", headers=H(tok), json={"saved_prompts": ["x" * 2001]}).status_code == 422
    assert client.put("/v1/me/preferences", headers=H(tok), json={"saved_prompts": ["x"] * 31}).status_code == 422
