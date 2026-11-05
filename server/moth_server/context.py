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
