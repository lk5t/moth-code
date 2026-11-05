"""MOTH Server application factory."""

from __future__ import annotations

import importlib
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from moth_server import __version__
from moth_server.config import Settings
from moth_server.context import Ctx
from moth_server.db import Database
from moth_server.mailer import Mailer
from moth_server.ratelimit import RateLimiter

# Components are separate modules; each exposes ``router`` and optionally ``setup(ctx)``.
COMPONENTS = [
    "moth_server.routes.auth",
    "moth_server.routes.billing",
    "moth_server.routes.admin",
    "moth_server.routes.inference",
    "moth_server.routes.referrals",
    "moth_server.pages.web",
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = (settings or Settings.from_env()).ensure_dirs()
    db = Database(settings.db_url)
    db.migrate()
    ctx = Ctx(settings=settings, db=db, mailer=Mailer(settings), limiter=RateLimiter(db))
    app = FastAPI(title="MOTH Server", version=__version__, docs_url="/docs", redoc_url=None)
    app.state.ctx = ctx
    app.state.started_at = time.time()
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                       allow_methods=["*"], allow_headers=["*"], expose_headers=["Retry-After", "X-Moth-Reason"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):  # never leak internals to clients
        import logging

        logging.getLogger("moth_server").exception("unhandled error", exc_info=exc)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    for name in COMPONENTS:
        module = importlib.import_module(name)
        if hasattr(module, "setup"):
            module.setup(ctx)
        for attr in ("router", "me_router"):
            if hasattr(module, attr):
                app.include_router(getattr(module, attr))

    @app.get("/v1/health")
    def health():
        return {"service": "moth-server", "version": __version__, "status": "ok",
                "email": ctx.mailer.mode, "payments_configured": settings.payments_configured}

    return app
