"""Account operations shared by the API and the CLI."""

from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from moth_server.db import Database, email_tokens, now, users
from moth_server.security import (
    OWNER_USERNAME, hash_password, new_token, normalize_email, referral_code, token_hash,
)


class AccountError(ValueError):
    pass


def find_by_username(db: Database, username: str, conn: Connection | None = None) -> dict | None:
    return db.one(select(users).where(users.c.username_lc == username.strip().lower()), conn)


def find_by_email(db: Database, email: str, conn: Connection | None = None) -> dict | None:
    return db.one(select(users).where(users.c.email_normalized == normalize_email(email)), conn)


def unique_referral_code(conn: Connection) -> str:
    while True:
        code = referral_code()
        if not conn.execute(select(users.c.id).where(users.c.referral_code == code)).first():
            return code


def create_user(conn: Connection, username: str, email: str, password: str, role: str = "user",
                verified: bool = False, ip: str | None = None) -> int:
    if role == "owner" and username.lower() != OWNER_USERNAME.lower():
        raise AccountError("only the reserved owner account can have the owner role")
    res = conn.execute(users.insert().values(
        username=username, username_lc=username.lower(), email=email.strip(),
        email_normalized=normalize_email(email), password_hash=hash_password(password), role=role,
        status="active", email_verified_at=now() if verified else None, settings=json.dumps({}),
        referral_code=unique_referral_code(conn), credit_balance=0, plan_code="free",
        registration_ip=ip, created_at=now()))
    return int(res.inserted_primary_key[0])


def issue_email_token(conn: Connection, user_id: int, purpose: str, ttl: float) -> str:
    token = new_token(24)
    t = now()
    # Only the newest token of each purpose stays valid.
    conn.execute(email_tokens.update().where(email_tokens.c.user_id == user_id, email_tokens.c.purpose == purpose,
                                             email_tokens.c.used_at.is_(None)).values(used_at=t))
    conn.execute(email_tokens.insert().values(user_id=user_id, purpose=purpose, token_hash=token_hash(token),
                                              created_at=t, expires_at=t + ttl))
    return token


def consume_email_token(conn: Connection, token: str, purpose: str) -> int | None:
    t = now()
    row = conn.execute(select(email_tokens).where(email_tokens.c.token_hash == token_hash(token),
                                                  email_tokens.c.purpose == purpose)).mappings().first()
    if not row or row["used_at"] is not None or row["expires_at"] < t:
        return None
    res = conn.execute(email_tokens.update().where(email_tokens.c.id == row["id"], email_tokens.c.used_at.is_(None))
                       .values(used_at=t))
    return row["user_id"] if res.rowcount == 1 else None


def owner_exists(db: Database) -> bool:
    return bool(db.one(select(func.count().label("n")).select_from(users).where(users.c.role == "owner"))["n"])


def init_owner(db: Database, email: str, password: str) -> int:
    """One-time creation of the reserved LK5T owner account."""
    with db.tx() as c:
        if c.execute(select(users.c.id).where(users.c.role == "owner")).first():
            raise AccountError("the owner account already exists")
        if c.execute(select(users.c.id).where(users.c.username_lc == OWNER_USERNAME.lower())).first():
            raise AccountError(f"username {OWNER_USERNAME} is already taken by a non-owner account")
        uid = create_user(c, OWNER_USERNAME, email, password, role="owner", verified=True)
        from moth_server.audit import audit

        audit(db, "owner.initialized", uid, f"user:{uid}", conn=c)
        db.set_config("owner_initialized_at", now(), conn=c)
        return uid
