"""Authentication dependencies: current session/user, owner role, recent re-authentication."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from moth_server.context import Ctx, get_ctx
from moth_server.db import now, sessions, users
from moth_server.security import token_hash

TOUCH_INTERVAL = 3600.0


@dataclass
class Auth:
    user: dict
    session: dict

    @property
    def uid(self) -> int:
        return self.user["id"]

    @property
    def is_owner(self) -> bool:
        return self.user["role"] == "owner"

    @property
    def is_admin(self) -> bool:
        return self.user["role"] in ("owner", "admin")


def bearer(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else None


def current_auth(request: Request, ctx: Ctx = Depends(get_ctx)) -> Auth:
    token = bearer(request)
    if not token:
        raise HTTPException(401, "Sign in required.")
    t = now()
    row = ctx.db.one(
        select(sessions, users.c.id.label("u_id")).join(users, users.c.id == sessions.c.user_id)
        .where(sessions.c.token_hash == token_hash(token), sessions.c.revoked_at.is_(None),
               sessions.c.expires_at > t))
    if not row:
        raise HTTPException(401, "Your session has expired. Please sign in again.")
    user = ctx.db.one(select(users).where(users.c.id == row["user_id"]))
    if not user or user["status"] != "active":
        raise HTTPException(403, "This account is suspended.")
    if t - row["last_used_at"] > TOUCH_INTERVAL:
        values = {"last_used_at": t}
        if row["remember"]:  # sliding expiry for remembered sessions
            values["expires_at"] = t + ctx.settings.session_days_remember * 86400
        with ctx.db.tx() as c:
            c.execute(sessions.update().where(sessions.c.id == row["id"]).values(**values))
        row.update(values)
    sess = {k: row[k] for k in ("id", "user_id", "remember", "device_name", "created_at", "last_used_at",
                                "expires_at", "reauth_at", "ip", "user_agent")}
    return Auth(user=user, session=sess)


def require_owner(auth: Auth = Depends(current_auth)) -> Auth:
    if not auth.is_owner:
        raise HTTPException(403, "Owner access required.")
    return auth


def require_admin(auth: Auth = Depends(current_auth)) -> Auth:
    if not auth.is_admin:
        raise HTTPException(403, "Administrator access required.")
    return auth


def require_recent_auth(auth: Auth, ctx: Ctx) -> None:
    """Sensitive operations need a password re-entry within the last few minutes."""
    ra = auth.session.get("reauth_at")
    if not ra or now() - ra > ctx.settings.reauth_minutes * 60:
        raise HTTPException(428, "Please confirm your password to continue.")


def owner_reauthed(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)) -> Auth:
    require_recent_auth(auth, ctx)
    return auth
