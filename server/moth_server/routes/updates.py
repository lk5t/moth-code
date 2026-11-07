"""Update service: desktop (Tauri updater), workers, the local cloud update agent, Owner controls.

* ``/v1/updates/desktop/{target}/{arch}/{current}`` — Tauri 2 dynamic update endpoint. Returns the
  update JSON (version, url, minisign signature from the signed release) or 204 when up to date.
* ``/v1/updates/files/{component}/{version}/{name}`` — verified release files.
* ``/v1/updates/report`` — clients report update outcomes; failures halt staged rollouts.
* ``/v1/worker/update`` — the worker's update check (worker credential).
* ``/v1/agent/*`` — the cloud update agent on this machine (agent token from a 0600 file). The
  reverse proxy also blocks ``/v1/agent/`` from the internet.
* ``/v1/admin/updates*`` — Owner Dashboard: status, history, pause/resume, approvals, rollback.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from moth_server import compat
from moth_server import releases as R
from moth_server.audit import audit
from moth_server.context import Ctx, client_ip, get_ctx, request_base
from moth_server.db import now
from moth_server.deps import Auth, owner_reauthed, require_owner

router = APIRouter(tags=["updates"])

PLATFORMS = {("windows", "x86_64"): "windows-x86_64"}


def _install_id(request: Request, header: str | None) -> str:
    return (header or "").strip()[:64] or hashlib.sha256(client_ip(request).encode()).hexdigest()[:32]


# ---- desktop ------------------------------------------------------------------------------------
@router.get("/v1/updates/desktop/{target}/{arch}/{current}")
def desktop_update(target: str, arch: str, current: str, request: Request, channel: str = "stable",
                   x_moth_install_id: str | None = Header(default=None), ctx: Ctx = Depends(get_ctx)):
    platform = PLATFORMS.get((target.lower(), arch.lower()))
    if not platform:
        return Response(status_code=204)
    found = R.eligible(ctx, "desktop", current, _install_id(request, x_moth_install_id), channel[:16], platform)
    if not found:
        return Response(status_code=204)
    rel, f = found
    if not f.get("signature"):
        return Response(status_code=204)  # an update without an updater signature is never offered
    return {"version": rel["version"], "notes": rel["notes"] or "",
            "pub_date": _rfc3339(rel["created_at"]), "signature": f["signature"],
            "url": f"{request_base(request, ctx)}/v1/updates/files/desktop/{rel['version']}/{f['file']}"}


def _rfc3339(ts: float) -> str:
    import datetime as dt

    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("/v1/updates/files/{component}/{version}/{name}", include_in_schema=False)
def release_file(component: str, version: str, name: str, ctx: Ctx = Depends(get_ctx)):
    if component == "server":
        raise HTTPException(404, "Not found.")  # server bundles are for the local agent only
    p = R.served_file(ctx, component, version, name)
    if not p:
        raise HTTPException(404, "Not found.")
    return FileResponse(p, media_type="application/octet-stream", filename=name)


class ReportIn(BaseModel):
    component: str = Field(pattern="^(desktop|worker)$")
    from_version: str | None = Field(default=None, max_length=32)
    to_version: str = Field(max_length=32)
    ok: bool
    error: str | None = Field(default=None, max_length=2000)


@router.post("/v1/updates/report", status_code=204)
def update_report(body: ReportIn, request: Request, x_moth_install_id: str | None = Header(default=None),
                  ctx: Ctx = Depends(get_ctx)):
    from moth_server.routes.auth import limit

    limit(ctx, f"update-report:{client_ip(request)}", 30, 3600)
    R.record_report(ctx, body.component, _install_id(request, x_moth_install_id), body.from_version,
                    body.to_version, body.ok, body.error)
    return Response(status_code=204)


# ---- worker ---------------------------------------------------------------------------------------
@router.get("/v1/worker/update")
def worker_update(request: Request, channel: str = "stable", ctx: Ctx = Depends(get_ctx)):
    from moth_server.routes.training import current_worker

    w = current_worker(request, ctx)
    found = R.eligible(ctx, "worker", w["version"] or "0.0.0", f"worker-{w['id']}", channel[:16])
    if not found:
        return {"update": None}
    rel, f = found
    loaded = R.load_manifest(ctx, rel["version"], "worker")
    return {"update": {"version": rel["version"], "file": f["file"], "sha256": f["sha256"], "size": f.get("size"),
                       # a path on the server the worker is already connected to (works behind any proxy/domain)
                       "url": f"/v1/updates/files/worker/{rel['version']}/{f['file']}",
                       "manifest": R.encode_manifest(loaded[1]), "signature": loaded[2]}}


# ---- local update agent -------------------------------------------------------------------------------
def require_agent(x_moth_agent_token: str | None = Header(default=None), ctx: Ctx = Depends(get_ctx)) -> None:
    f = ctx.settings.agent_token_file
    if not f or not Path(f).exists():
        raise HTTPException(404, "Not found.")
    expected = Path(f).read_text().strip()
    if not x_moth_agent_token or not expected or not hmac.compare_digest(x_moth_agent_token.strip(), expected):
        raise HTTPException(404, "Not found.")  # indistinguishable from a missing route


def control(ctx: Ctx) -> dict:
    return ctx.db.get_config("agent_control", {}) or {}


@router.get("/v1/agent/control", dependencies=[Depends(require_agent)])
def agent_control(ctx: Ctx = Depends(get_ctx)):
    c = control(ctx)
    return {"paused": bool(c.get("paused")), "check_now_at": c.get("check_now_at"),
            "rollback_requested_at": c.get("rollback_requested_at"), "retry": c.get("retry", []),
            "approved_migrations": sorted(ctx.db.approved_migrations()), "channel": c.get("channel", "stable"),
            "server_releases": [r for r in R.list_releases(ctx, "server")]}


class AgentReleaseIn(BaseModel):
    manifest: str  # base64 of the exact signed bytes
    signature: str = Field(max_length=200)


@router.post("/v1/agent/releases", dependencies=[Depends(require_agent)])
def agent_register(body: AgentReleaseIn, ctx: Ctx = Depends(get_ctx)):
    import base64

    try:
        return R.register(ctx, base64.b64decode(body.manifest), body.signature)
    except (R.ReleaseError, ValueError) as e:
        raise HTTPException(422, str(e)) from None


class AgentFileIn(BaseModel):
    component: str = Field(pattern="^(desktop|worker)$")
    version: str = Field(max_length=32)
    path: str = Field(max_length=1024)  # a file the agent downloaded into the incoming area


class AgentModelIn(BaseModel):
    manifest: str  # base64 of the signed model release manifest
    signature: str
    path: str  # the verified package in the incoming area


@router.post("/v1/agent/models", dependencies=[Depends(require_agent)])
def agent_model(body: AgentModelIn, ctx: Ctx = Depends(get_ctx)):
    """Import a signed official MOTH model release (0.5.2). The server re-verifies the signature and the
    package checksum; the model is then evaluated and, if it passes, deployed (Owner flag)."""
    import base64
    import threading

    from moth_server import models as M

    incoming = (ctx.settings.releases_dir / "incoming").resolve()
    src = Path(body.path).resolve()
    if incoming not in src.parents or not src.is_file():
        raise HTTPException(422, "files must be placed in the incoming area first")
    try:
        rel = M.import_official(ctx, base64.b64decode(body.manifest), body.signature, src)
    except (M.ReleaseError, R.ReleaseError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    finally:
        src.unlink(missing_ok=True)
    if ctx.extras.get("synchronous_jobs"):  # tests: evaluate and deploy before answering
        M.auto_pipeline(ctx)
    else:
        threading.Thread(target=M.auto_pipeline, args=(ctx,), daemon=True, name="official-model").start()
    return {"ok": True, "version": rel["version"], "status": M.release(ctx, rel["version"])["status"]}


@router.post("/v1/agent/files", dependencies=[Depends(require_agent)])
def agent_file(body: AgentFileIn, ctx: Ctx = Depends(get_ctx)):
    incoming = (ctx.settings.releases_dir / "incoming").resolve()
    src = Path(body.path).resolve()
    if incoming not in src.parents or not src.is_file():
        raise HTTPException(422, "files must be placed in the incoming area first")
    try:
        dest = R.accept_file(ctx, body.component, body.version, src)
    except R.ReleaseError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True, "file": dest.name}


@router.post("/v1/agent/deployments", dependencies=[Depends(require_agent)])
def agent_deployment(body: dict[str, Any], ctx: Ctx = Depends(get_ctx)):
    try:
        return R.deployment_event(ctx, body)
    except (R.ReleaseError, KeyError) as e:
        raise HTTPException(422, str(e)) from None


@router.post("/v1/agent/heartbeat", dependencies=[Depends(require_agent)])
def agent_heartbeat(body: dict[str, Any], ctx: Ctx = Depends(get_ctx)):
    allowed = {k: body.get(k) for k in ("agent_version", "state", "message", "current", "previous", "last_check",
                                        "next_check", "disk_free", "supervisor", "last_error", "backups")}
    ctx.db.set_config("agent_status", {**allowed, "ts": now()})
    c = control(ctx)
    if body.get("ack_check_now") and c.get("check_now_at"):
        c.pop("check_now_at", None)
    if body.get("ack_rollback") and c.get("rollback_requested_at"):
        c.pop("rollback_requested_at", None)
    if body.get("ack_retry"):
        c["retry"] = [v for v in c.get("retry", []) if v not in body["ack_retry"]]
    ctx.db.set_config("agent_control", c)
    return {"ok": True}


# ---- Owner Dashboard ------------------------------------------------------------------------------------
@router.get("/v1/admin/updates")
def updates_overview(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from sqlalchemy import func, select

    from moth_server import __version__
    from moth_server.db import workers

    agent = ctx.db.get_config("agent_status", None)
    if agent:
        agent["online"] = now() - float(agent.get("ts", 0)) < 30 * 60
    worker_versions = ctx.db.all(select(workers.c.version, func.count().label("n"))
                                 .where(workers.c.revoked_at.is_(None)).group_by(workers.c.version))
    pending = ctx.db.pending_migrations()
    return {"server": {"version": __version__, "schema_version": ctx.db.schema_version(),
                       "api_version": compat.API_VERSION, "environment": ctx.settings.environment},
            "agent": agent, "control": control(ctx),
            "min_client_versions": compat.min_versions(ctx),
            "releases": R.list_releases(ctx), "deployments": R.list_deployments(ctx),
            "worker_versions": worker_versions, "pending_migrations": pending,
            "signing_configured": bool(ctx.settings.release_pubkey)}


@router.post("/v1/admin/updates/server/rollback")
def server_rollback(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    c = control(ctx)
    c["rollback_requested_at"] = now()
    ctx.db.set_config("agent_control", c)
    audit(ctx.db, "updates.server_rollback_requested", auth.uid, "server")
    return c


@router.post("/v1/admin/updates/server/retry/{version}")
def server_retry(version: str, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    c = control(ctx)
    c["retry"] = sorted(set(c.get("retry", [])) | {version[:32]})
    c["check_now_at"] = now()
    ctx.db.set_config("agent_control", c)
    audit(ctx.db, "updates.server_retry", auth.uid, f"server:{version}")
    return c


@router.post("/v1/admin/updates/server/{action}")
def server_action(action: str, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    c = control(ctx)
    if action == "pause":
        c["paused"] = True
    elif action == "resume":
        c["paused"] = False
    elif action == "check-now":
        c["check_now_at"] = now()
    else:
        raise HTTPException(404, "Unknown action.")
    ctx.db.set_config("agent_control", c)
    audit(ctx.db, f"updates.server_{action.replace('-', '_')}", auth.uid, "server")
    return c


class RolloutIn(BaseModel):
    percent: int | None = Field(default=None, ge=0, le=100)


@router.post("/v1/admin/updates/releases/{component}/{version}/{action}")
def release_action(component: str, version: str, action: str, body: RolloutIn | None = None,
                   auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return R.set_status(ctx, component, version, action, auth.uid, body.percent if body else None)
    except R.ReleaseError as e:
        raise HTTPException(404 if "unknown release" in str(e) else 422, str(e)) from None


@router.post("/v1/admin/updates/migrations/{version}/approve")
def approve_migration(version: int, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    approved = sorted(ctx.db.approved_migrations() | {version})
    ctx.db.set_config("approved_destructive_migrations", approved)
    audit(ctx.db, "updates.migration_approved", auth.uid, f"migration:{version}")
    return {"approved_migrations": approved}


class MinVersionsIn(BaseModel):
    desktop: str | None = Field(default=None, max_length=32)
    worker: str | None = Field(default=None, max_length=32)


@router.put("/v1/admin/updates/min-versions")
def set_min_versions(body: MinVersionsIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    cur = ctx.db.get_config("min_client_versions", {}) or {}
    for kind in ("desktop", "worker"):
        v = getattr(body, kind)
        if v:
            try:
                compat.parse_version(v)
            except ValueError as e:
                raise HTTPException(422, str(e)) from None
            cur[kind] = v
    ctx.db.set_config("min_client_versions", cur)
    audit(ctx.db, "updates.min_versions", auth.uid, "clients", cur)
    return compat.min_versions(ctx)


def setup(ctx: Ctx) -> None:
    import threading
    import time

    (ctx.settings.releases_dir / "incoming").mkdir(parents=True, exist_ok=True)
    if ctx.extras.get("disable_background"):
        return

    def loop() -> None:
        while True:
            time.sleep(300)
            try:
                R.advance_rollouts(ctx)
            except Exception:  # noqa: BLE001
                R.log.exception("rollout loop failed")

    threading.Thread(target=loop, name="moth-rollouts", daemon=True).start()

