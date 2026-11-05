"""Owner model-release management (evaluate, deploy, roll back) and public model status."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from moth_server import models as M
from moth_server.context import Ctx, get_ctx
from moth_server.deps import Auth, owner_reauthed, require_owner

router = APIRouter(tags=["models"])
PIPELINE_INTERVAL = 120.0


def setup(ctx: Ctx) -> None:
    M.restore_on_startup(ctx)
    stop = threading.Event()
    ctx.extras["models_stop"] = stop

    def loop() -> None:
        while not stop.wait(PIPELINE_INTERVAL):
            try:
                M.auto_pipeline(ctx)
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=loop, daemon=True, name="model-pipeline").start()


@router.get("/v1/models/current")
def current_model(ctx: Ctx = Depends(get_ctx)):
    """Public: which official MOTH model MOTH Cloud is serving (no weights are distributed)."""
    from moth_server.routes.admin import flags

    d = M.deployed(ctx)
    return {"available": bool(d and flags(ctx).get("cloud_inference_enabled") and ctx.extras.get("inference_engine")),
            "release": {k: d[k] for k in ("version", "name", "published_at")} | {"params": d["info"].get("params")}
            if d else None}


@router.get("/v1/admin/models")
def admin_models(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return {"releases": M.list_releases(ctx), "deployed": ctx.extras.get("deployed_version")}


@router.post("/v1/admin/models/upload")
async def upload(name: str = Form(..., max_length=128), file: UploadFile = File(...),
                 auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        while chunk := await file.read(1 << 20):
            tmp.write(chunk)
    try:
        return M.register_upload(ctx, Path(tmp.name), name, auth.uid)
    except (M.ReleaseError, OSError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    finally:
        Path(tmp.name).unlink(missing_ok=True)


@router.post("/v1/admin/models/sync")
def sync(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return M.auto_pipeline(ctx)


@router.post("/v1/admin/models/{version}/evaluate")
def evaluate(version: int, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    try:
        return M.evaluate(ctx, version, actor_id=auth.uid)
    except M.ReleaseError as e:
        raise HTTPException(404, str(e)) from None


@router.post("/v1/admin/models/{version}/deploy")
def deploy(version: int, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return M.deploy(ctx, version, auth.uid)
    except M.ReleaseError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/v1/admin/models/rollback")
def rollback(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return M.rollback(ctx, auth.uid)
    except M.ReleaseError as e:
        raise HTTPException(409, str(e)) from None
