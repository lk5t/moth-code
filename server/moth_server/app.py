"""MOTH Server application factory."""

from __future__ import annotations

import importlib
import logging
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
    "moth_server.routes.training",
    "moth_server.routes.models",
    "moth_server.routes.dashboard",
    "moth_server.routes.uploads",
    "moth_server.routes.updates",
    "moth_server.routes.system",
    "moth_server.routes.evolution",
    "moth_server.routes.notifications",
    "moth_server.routes.intelligence",
    "moth_server.pages.web",
]


class DbErrorLog(logging.Handler):
    """Keeps recent server errors in the database for the Owner Dashboard (bounded, best effort)."""

    def __init__(self, db: Database, keep: int = 500):
        super().__init__(level=logging.ERROR)
        self.db, self.keep, self._busy = db, keep, False

    def emit(self, record: logging.LogRecord) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            from sqlalchemy import delete, func, select

            from moth_server.db import error_log, now

            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg += f" — {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
            with self.db.tx() as c:
                c.execute(error_log.insert().values(ts=now(), source=record.name[:64], message=msg[:2000]))
                newest = c.execute(select(func.max(error_log.c.id))).scalar() or 0
                c.execute(delete(error_log).where(error_log.c.id <= newest - self.keep))
        except Exception:  # noqa: BLE001 — logging must never raise
            pass
        finally:
            self._busy = False


def create_app(settings: Settings | None = None, extras: dict | None = None) -> FastAPI:
    settings = (settings or Settings.from_env()).ensure_dirs()
    try:  # the shared MOTH model code is required (model registry, evaluation, inference)
        import moth  # noqa: F401
    except ImportError as e:
        raise RuntimeError("the MOTH backend package (moth) is not installed or not on PYTHONPATH; install "
                           "MOTH Cloud with deploy/install-server.sh or `pip install ./backend`") from e
    db = Database(settings.db_url)
    db.migrate()  # additive migrations only; destructive ones need explicit Owner approval
    ctx = Ctx(settings=settings, db=db, mailer=Mailer(settings), limiter=RateLimiter(db), extras=dict(extras or {}))
    app = FastAPI(title="MOTH Server", version=__version__, docs_url="/docs" if settings.dev_mode else None,
                  redoc_url=None, openapi_url="/openapi.json" if settings.dev_mode else None)
    app.state.ctx = ctx
    ctx.extras.setdefault("app", app)  # 0.7.2: the built-in cloud worker talks to this app in-process
    app.state.started_at = time.time()
    log_handler = DbErrorLog(db)
    for name in ("moth_server", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers = [h for h in lg.handlers if not isinstance(h, DbErrorLog)] + [log_handler]

    @app.middleware("http")
    async def compatibility(request: Request, call_next):
        from moth_server import compat

        path = request.url.path
        if request.method != "OPTIONS" and not path.startswith(compat.EXEMPT_PREFIXES):
            client = compat.parse_client(request.headers.get("x-moth-client"))
            need = compat.outdated(ctx, client)
            if need:
                kind = (client or compat.LEGACY_CLIENT)[0]
                return JSONResponse(
                    {"detail": f"This version of MOTH {'Code' if kind == 'desktop' else 'Worker'} is too old for "
                               f"MOTH Cloud. Version {need} or newer is required; it updates automatically.",
                     "min_version": need},
                    status_code=426, headers={"X-Moth-Reason": "client_outdated",
                                              "Access-Control-Expose-Headers": "X-Moth-Reason"})
        return await call_next(request)

    @app.middleware("http")
    async def native_reset_fence(request:Request,call_next):
        from moth_server.evolution import native_reset as NR
        import anyio
        path=request.url.path
        native=(path.startswith(("/v1/worker/jobs/","/cloud/v1/")) or path=="/v1/chat" or
                (request.method not in ("GET","HEAD","OPTIONS") and path.startswith(("/v1/admin/models","/v1/admin/eval-datasets","/v1/admin/library","/v1/admin/evolution"))))
        if path.startswith('/v1/admin/evolution/native-reset'):native=False
        if not native:return await call_next(request)
        def enter():
            with NR.lock(ctx):
                if NR.fenced(ctx):return False
                ctx.extras['native_http_active']=ctx.extras.get('native_http_active',0)+1
                return True
        def leave():
            with NR.lock(ctx):ctx.extras['native_http_active']=max(0,ctx.extras.get('native_http_active',0)-1)
        if not await anyio.to_thread.run_sync(enter):
            return JSONResponse({'detail':'Native AI reset requires recovery. New native work is paused.'},status_code=503,headers={'X-Moth-Reason':'native_reset'})
        try:response=await call_next(request)
        except BaseException:
            await anyio.to_thread.run_sync(leave);raise
        original=response.body_iterator
        async def finish():
            try:
                async for chunk in original:yield chunk
            finally:await anyio.to_thread.run_sync(leave)
        response.body_iterator=finish()
        return response

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
        from moth_server import compat

        engine = ctx.extras.get("inference_engine")
        return {"service": "moth-server", "version": __version__, "status": "ok",
                "api_version": compat.API_VERSION, "min_client_versions": compat.min_versions(ctx),
                "schema_version": db.schema_version(), "uptime_s": round(time.time() - app.state.started_at),
                "model_version": ctx.extras.get("deployed_version") if engine else None,
                "email": ctx.mailer.mode, "payments_configured": settings.payments_configured}

    return app
