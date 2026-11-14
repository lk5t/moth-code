"""1.0 two-factor sign-in."""
from conftest import H
from moth_server import totp


def test_two_factor_setup_enable_login_disable(client, owner):
    h = H(owner["token"])
    s = client.post("/v1/me/2fa/setup", headers=h).json()
    assert s["uri"].startswith("otpauth://totp/MOTH:")
    assert client.post("/v1/me/2fa/enable", json={"code": "000000"}, headers=h).status_code == 400
    assert client.post("/v1/me/2fa/enable", json={"code": totp.code(s["secret"])}, headers=h).json()["enabled"]
    login = {"username": "lk5t", "password": "crimson wings 2026!"}
    r = client.post("/v1/auth/login", json=login)
    assert r.status_code == 401 and r.headers.get("X-Moth-Reason") == "two_factor_required"
    ok = client.post("/v1/auth/login", json={**login, "otp": totp.code(s["secret"])})
    assert ok.status_code == 200, ok.text
    assert client.post("/v1/me/2fa/disable", json={"code": totp.code(s["secret"]), "password": "wrong"}, headers=h).status_code == 400


def test_totp_matches_rfc_6238_vector():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert totp.code(secret, 59) == "287082"
