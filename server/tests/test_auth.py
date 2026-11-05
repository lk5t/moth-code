import io
import struct
import sys
import zlib

from sqlalchemy import select

from conftest import H, PASSWORD, last_token, outbox, register_verified
from moth_server.db import sessions, users


def _png() -> bytes:
    raw = b"\x00\xff\x00\x00"
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_register_verify_login_and_profile(client, settings):
    r = client.post("/v1/auth/register", json={"username": "Alice", "email": "Alice@Example.com", "password": PASSWORD})
    assert r.status_code == 202 and "verification email" in r.json()["message"]
    # cannot sign in before verifying
    r = client.post("/v1/auth/login", json={"username": "alice", "password": PASSWORD})
    assert r.status_code == 403 and r.headers["x-moth-reason"] == "email_unverified"
    assert client.post("/v1/auth/verify-email", json={"token": "bogus"}).status_code == 400
    token = last_token(settings, "verify")
    assert client.post("/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/v1/auth/verify-email", json={"token": token}).status_code == 400  # single use
    r = client.post("/v1/auth/login", json={"username": "ALICE", "password": PASSWORD})  # case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["remember"] is True and body["user"]["username"] == "Alice" and body["user"]["role"] == "user"
    me = client.get("/v1/me", headers=H(body["token"])).json()
    assert me["email_verified"] and len(me["referral_code"]) == 8
    me = client.patch("/v1/me", json={"display_name": "Alice A", "settings": {"theme": "moth"}},
                      headers=H(body["token"])).json()
    assert me["display_name"] == "Alice A" and me["settings"] == {"theme": "moth"}


def test_passwords_are_argon2id(client, settings):
    register_verified(client, settings)
    h = client.app.state.ctx.db.one(select(users.c.password_hash))["password_hash"]
    assert h.startswith("$argon2id$") and PASSWORD not in h


def test_username_rules_and_reserved_owner_name(client, settings):
    register_verified(client, settings, "bob")
    lim = client.app.state.ctx.limiter
    for name in ("BOB", "bob"):
        r = client.post("/v1/auth/register", json={"username": name, "email": "other@example.com", "password": PASSWORD})
        assert r.status_code == 409
    lim.clear("register:ip:testclient")
    for name in ("LK5T", "lk5t", "Lk5T", "admin"):
        r = client.post("/v1/auth/register", json={"username": name, "email": f"{name}x@example.com", "password": PASSWORD})
        assert r.status_code == 409, name
    lim.clear("register:ip:testclient")
    for bad in ("a", "-bad", "has space", "x" * 40):
        assert client.post("/v1/auth/register", json={"username": bad, "email": "z@example.com",
                                                      "password": PASSWORD}).status_code == 422
    lim.clear("register:ip:testclient")
    assert client.post("/v1/auth/register", json={"username": "carol", "email": "c@example.com",
                                                  "password": "short"}).status_code == 422
    assert client.post("/v1/auth/register", json={"username": "carol", "email": "c@example.com",
                                                  "password": "carol-password-123"}).status_code == 422


def test_duplicate_email_is_not_revealed(client, settings):
    register_verified(client, settings, "dave", email="dave.smith@gmail.com")
    before = len(outbox(settings))
    r = client.post("/v1/auth/register", json={"username": "dave2", "email": "DaveSmith+x@googlemail.com",
                                               "password": PASSWORD})
    assert r.status_code == 202 and "verification email" in r.json()["message"]  # identical response
    assert client.app.state.ctx.db.one(select(users).where(users.c.username_lc == "dave2")) is None
    assert "sign-up attempt" in outbox(settings)[before]  # the real owner is told instead


def test_login_errors_are_generic_and_rate_limited(client, settings):
    register_verified(client, settings, "erin")
    a = client.post("/v1/auth/login", json={"username": "erin", "password": "wrong password!!"})
    b = client.post("/v1/auth/login", json={"username": "nobody", "password": "wrong password!!"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()
    codes = [client.post("/v1/auth/login", json={"username": "erin", "password": "nope nope nope"}).status_code
             for _ in range(12)]
    assert 429 in codes
    r = client.post("/v1/auth/login", json={"username": "erin", "password": PASSWORD})
    assert r.status_code == 429 and "Retry-After" in r.headers


def test_sessions_logout_revocation_and_expiry(client, settings):
    s1 = register_verified(client, settings, "fay")["token"]
    s2 = client.post("/v1/auth/login", json={"username": "fay", "password": PASSWORD, "remember": False,
                                             "device_name": "Laptop"}).json()
    listed = client.get("/v1/auth/sessions", headers=H(s1)).json()
    assert len(listed) == 2 and sum(s["current"] for s in listed) == 1
    short = next(s for s in listed if s["device_name"] == "Laptop")
    assert short["expires_at"] - short["created_at"] < 13 * 3600  # remember=False → short session
    assert client.delete(f"/v1/auth/sessions/{short['id']}", headers=H(s1)).status_code == 200
    assert client.get("/v1/me", headers=H(s2["token"])).status_code == 401
    assert client.post("/v1/auth/logout", headers=H(s1)).status_code == 200
    assert client.get("/v1/me", headers=H(s1)).status_code == 401
    # expiry
    s3 = client.post("/v1/auth/login", json={"username": "fay", "password": PASSWORD}).json()["token"]
    db = client.app.state.ctx.db
    with db.tx() as c:
        c.execute(sessions.update().values(expires_at=0))
    assert client.get("/v1/me", headers=H(s3)).status_code == 401
    assert client.get("/v1/me").status_code == 401


def test_revoke_other_sessions_and_password_change(client, settings):
    a = register_verified(client, settings, "gus")["token"]
    b = client.post("/v1/auth/login", json={"username": "gus", "password": PASSWORD}).json()["token"]
    assert client.post("/v1/me/password", json={"current_password": "wrong one!!!", "new_password": "x"},
                       headers=H(a)).status_code == 401
    assert client.post("/v1/me/password", json={"current_password": PASSWORD, "new_password": "a brand new secret"},
                       headers=H(a)).status_code == 200
    assert client.get("/v1/me", headers=H(b)).status_code == 401 and client.get("/v1/me", headers=H(a)).status_code == 200
    assert client.post("/v1/auth/login", json={"username": "gus", "password": "a brand new secret"}).status_code == 200


def test_password_recovery(client, settings):
    old = register_verified(client, settings, "hal")["token"]
    r1 = client.post("/v1/auth/forgot-password", json={"username_or_email": "hal@example.com"})
    r2 = client.post("/v1/auth/forgot-password", json={"username_or_email": "ghost@example.com"})
    assert r1.status_code == r2.status_code == 202 and r1.json() == r2.json()
    token = last_token(settings, "reset")
    assert client.post("/v1/auth/reset-password", json={"token": token, "new_password": "tiny"}).status_code == 422
    assert client.post("/v1/auth/reset-password", json={"token": token, "new_password": "recovered secret 1"}).status_code == 200
    assert client.post("/v1/auth/reset-password", json={"token": token, "new_password": "again secret 22"}).status_code == 400
    assert client.get("/v1/me", headers=H(old)).status_code == 401  # all sessions revoked
    assert client.post("/v1/auth/login", json={"username": "hal", "password": "recovered secret 1"}).status_code == 200


def test_web_pages_for_email_links(client, settings):
    client.post("/v1/auth/register", json={"username": "ivy", "email": "ivy@example.com", "password": PASSWORD})
    token = last_token(settings, "verify")
    page = client.get(f"/verify?token={token}")
    assert page.status_code == 200 and "MOTH" in page.text and token in page.text  # GET does not consume
    done = client.post("/verify", data={"token": token})
    assert "Email verified" in done.text
    assert client.post("/v1/auth/login", json={"username": "ivy", "password": PASSWORD}).status_code == 200
    assert "<script>" not in client.get("/verify?token=<script>alert(1)</script>").text


def test_reauth(client, settings):
    t = register_verified(client, settings, "jay")["token"]
    assert client.post("/v1/auth/reauth", json={"password": "wrong wrong"}, headers=H(t)).status_code == 401
    assert client.post("/v1/auth/reauth", json={"password": PASSWORD}, headers=H(t)).status_code == 200


def test_avatar_upload_and_validation(client, settings):
    t = register_verified(client, settings, "kim")["token"]
    bad = client.put("/v1/me/avatar", files={"file": ("x.png", b"<svg onload=alert(1)>", "image/png")}, headers=H(t))
    assert bad.status_code == 415
    big = client.put("/v1/me/avatar", files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 300_000, "image/png")},
                     headers=H(t))
    assert big.status_code == 413
    me = client.put("/v1/me/avatar", files={"file": ("a.png", _png(), "image/png")}, headers=H(t)).json()
    assert me["avatar_url"]
    uid = me["id"]
    r = client.get(f"/v1/users/{uid}/avatar")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_owner_one_time_initialisation(client, settings, owner, monkeypatch):
    from moth_server import cli
    from moth_server.accounts import AccountError, create_user

    assert owner["user"]["role"] == "owner" and owner["user"]["username"] == "LK5T"
    monkeypatch.setattr(sys, "stdin", io.StringIO("another password 99\n"))
    assert cli.main(["init-owner", "--email", "x@moth.test", "--password-stdin"]) == 1  # one-time only
    db = client.app.state.ctx.db
    import pytest
    with pytest.raises(AccountError):
        with db.tx() as c:
            create_user(c, "mallory", "m@example.com", PASSWORD, role="owner")
    assert db.one(select(users.c.role).where(users.c.username_lc == "lk5t"))["role"] == "owner"


def test_registration_is_rate_limited_per_ip(client):
    codes = [client.post("/v1/auth/register", json={"username": f"user{i}", "email": f"u{i}@example.com",
                                                    "password": PASSWORD}).status_code for i in range(7)]
    assert codes[:5] == [202] * 5 and codes[5:] == [429, 429]
