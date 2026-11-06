"""Shared server context and request helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from moth_server.config import Settings
from moth_server.db import Database
from moth_server.mailer import Mailer
from moth_server.ratelimit import RateLimiter


@dataclass
class Ctx:
    settings: Settings
    db: Database
    mailer: Mailer
    limiter: RateLimiter
    extras: dict[str, Any] = field(default_factory=dict)


def get_ctx(request: Request) -> Ctx:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    ctx: Ctx = request.app.state.ctx
    if ctx.settings.trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def public_url(ctx: Ctx) -> str:
    """The server's public address for long-lived links (emails, referral links, worker installs):
    the Owner's dashboard setting if present, else MOTH_SERVER_PUBLIC_URL."""
    try:
        override = ctx.db.get_config("public_url")
    except Exception:  # noqa: BLE001 — config table not ready yet
        override = None
    return (override or ctx.settings.public_url).rstrip("/")


_LOOPBACK = ("127.", "localhost", "[::1]", "0.0.0.0")


def request_base(request: Request, ctx: Ctx) -> str:
    """The address this request reached the server on (through a trusted reverse proxy or tunnel), for
    links the same client uses right away, such as update downloads. Falls back to public_url()."""
    if ctx.settings.trust_proxy_headers:
        proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
        host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").split(",")[0].strip()
        if host and proto in ("http", "https") and not host.startswith(_LOOPBACK):
            return f"{proto}://{host}"
    return public_url(ctx)
