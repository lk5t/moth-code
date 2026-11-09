"""Owner model-release management and public model status.

Workflow: (desktop) select → validate → upload (``routes/uploads.py``) → evaluate → publish → deploy.
Evaluation datasets are managed here too (``/v1/admin/eval-datasets``).
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from moth_server import evalsets as E
from moth_server import models as M
from moth_server.context import Ctx, get_ctx
from moth_server.deps import Auth, current_auth, owner_reauthed, require_owner

router = APIRouter(tags=["models"])
PIPELINE_INTERVAL = 120.0


def setup(ctx: Ctx) -> None:
    M.restore_on_startup(ctx)
    stop = threading.Event()
    ctx.extras["models_stop"] = stop
    if ctx.extras.get("disable_background"):
        return

    def loop() -> None:
        while not stop.wait(PIPELINE_INTERVAL):
            try:
                from moth_server.evolution.native_reset import spawn
                spawn(ctx,lambda:M.auto_pipeline(ctx),"model-pipeline-work").join()
            except Exception:  # noqa: BLE001
                M.log.exception("model pipeline failed")

    threading.Thread(target=loop, daemon=True, name="model-pipeline").start()


def kick_pipeline(ctx: Ctx) -> None:
    """Continue the workflow now (e.g. after evaluation data was added) instead of waiting."""
    if ctx.extras.get("synchronous_jobs"):
        M.auto_pipeline(ctx)
    else:
        from moth_server.evolution.native_reset import spawn
        spawn(ctx,lambda:M.auto_pipeline(ctx),"model-pipeline-kick")


@router.get("/v1/models/current")
def current_model(ctx: Ctx = Depends(get_ctx)):
    """Public: which official MOTH model MOTH Cloud is serving (no weights are distributed)."""
    from moth_server.routes.admin import flags

    from moth_server.evolution.native_reset import fenced
    d = M.deployed(ctx)
    return {"available": bool(not fenced(ctx) and d and flags(ctx).get("cloud_inference_enabled") and ctx.extras.get("inference_engine")),
            "release": {k: d[k] for k in ("version", "name", "published_at")} | {"params": d["info"].get("params")}
            if d else None}


@router.get("/v1/admin/models")
def admin_models(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.routes.system import hardware

    sets = E.all_datasets(ctx)
    return {"releases": M.list_releases(ctx), "deployed": ctx.extras.get("deployed_version"),
            "eval_datasets": [E.public(d) for d in sets],
            "eval_ready": any(d["valid"] for d in sets), "hardware": hardware()}


@router.post("/v1/admin/models/upload")
async def upload(name: str = Form(..., max_length=128), file: UploadFile = File(...),
                 auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    """Single-request upload (v0.2 desktops and small models). v0.3 uses resumable uploads."""
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        while chunk := await file.read(1 << 20):
            tmp.write(chunk)
    try:
        rel = M.register_upload(ctx, Path(tmp.name), name, auth.uid)
    except (M.ReleaseError, OSError, ValueError) as e:
        raise HTTPException(422, str(e)) from None
    finally:
        Path(tmp.name).unlink(missing_ok=True)
    M.evaluate_in_background(ctx, rel["version"], auth.uid)
    return rel


@router.post("/v1/admin/models/sync")
def sync(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return M.auto_pipeline(ctx)


@router.post("/v1/admin/models/{version}/evaluate")
def evaluate(version: int, wait: bool = False, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    """Evaluate (or retry the evaluation of) a stored release. No re-upload is needed."""
    try:
        rel = M.release(ctx, version)
        if wait:
            return M.evaluate(ctx, version, actor_id=auth.uid)
        if rel["status"] in ("uploading", "deploying", "deployed", "evaluating"):
            raise M.ReleaseError(f"a release that is {rel['status']} cannot be evaluated now")
        if not rel["path"]:
            raise M.ReleaseError("this release has no stored package; upload the model again")
    except M.ReleaseError as e:
        raise HTTPException(409 if "unknown" not in str(e) else 404, str(e)) from None
    M.evaluate_in_background(ctx, version, auth.uid)
    return {**rel, "queued": True}


class PublishIn(BaseModel):
    override_regression: bool = False


@router.post("/v1/admin/models/{version}/publish")
def publish(version: int, body: PublishIn | None = None, auth: Auth = Depends(owner_reauthed),
            ctx: Ctx = Depends(get_ctx)):
    try:
        return M.publish(ctx, version, auth.uid, bool(body and body.override_regression))
    except M.ReleaseError as e:
        raise HTTPException(409, str(e)) from None


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


# ---- evaluation datasets -------------------------------------------------------------------------
@router.get("/v1/admin/eval-datasets")
def eval_datasets(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return [E.public(d) for d in E.all_datasets(ctx)]


@router.post("/v1/admin/eval-datasets")
async def add_eval_dataset(name: str = Form("", max_length=128), kind: str = Form("text"),
                           license: str = Form("", max_length=64), tokenizer_fingerprint: str = Form(""),
                           file: UploadFile = File(...), auth: Auth = Depends(owner_reauthed),
                           ctx: Ctx = Depends(get_ctx)):
    tmp = Path(tempfile.mkstemp(prefix="moth-evalset-", dir=E.root(ctx))[1])
    size = 0
    try:
        with open(tmp, "wb") as f:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > E.MAX_UPLOAD_BYTES:
                    raise E.EvalSetError(f"the file is larger than {E.MAX_UPLOAD_BYTES // 2**20} MB")
                f.write(chunk)
        d = E.add(ctx, name, file.filename or "dataset", tmp, kind, license, tokenizer_fingerprint or None, auth.uid)
    except E.EvalSetError as e:
        raise HTTPException(422, str(e)) from None
    finally:
        tmp.unlink(missing_ok=True)
    kick_pipeline(ctx)  # releases waiting for evaluation data continue automatically
    return {**E.public(d), "retrying": M.retry_candidates(ctx)}


class PinIn(BaseModel):
    id: str | None = None


@router.put("/v1/admin/eval-datasets/pinned")
def pin_eval_dataset(body: PinIn, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    try:
        E.pin(ctx, body.id, auth.uid)
    except E.EvalSetError as e:
        raise HTTPException(422, str(e)) from None
    kick_pipeline(ctx)
    return [E.public(d) for d in E.all_datasets(ctx)]


@router.delete("/v1/admin/eval-datasets/{did}")
def delete_eval_dataset(did: str, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        E.remove(ctx, did, auth.uid)
    except E.EvalSetError as e:
        raise HTTPException(422, str(e)) from None
    return {"ok": True}


@router.get("/v1/models/deployed/package-info")
def deployed_package_info(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """What MOTH Code needs to download the deployed model for on-computer inference (0.5.2): the release,
    the package's SHA-256 and, for official releases, the signed release manifest."""
    import base64

    d = M.deployed(ctx)
    if not d:
        raise HTTPException(404, "No model is deployed on MOTH Cloud yet.")
    path, sha = M.package_archive(ctx, d["version"])
    out = {"version": d["version"], "name": d["name"], "model_version": d["info"].get("model_version"),
           "display_name": d["info"].get("display_name") or d["name"], "params": d["info"].get("params"),
           "weights_sha256": d["sha256"], "package_sha256": sha, "size": path.stat().st_size,
           "context_length": d["info"].get("context_length")}
    sm = Path(d["path"]) / "model-manifest.json"
    if sm.exists():  # promoted by this server: signed with its model key (MOTH Code pins the key)
        from moth_server import serving

        out["server_manifest"] = base64.b64encode(sm.read_bytes()).decode()
        out["server_signature"] = (Path(d["path"]) / "model-manifest.json.sig").read_text().strip()
        out["server_key"] = serving.public_key_b64(ctx)
    mf = Path(d["path"]) / "release-manifest.json"
    if mf.exists():
        out["release_manifest"] = base64.b64encode(mf.read_bytes()).decode()
        out["release_signature"] = (Path(d["path"]) / "release-manifest.json.sig").read_text().strip()
    return out


@router.get("/v1/models/signing-key")
def model_signing_key(ctx: Ctx = Depends(get_ctx)):
    from moth_server import serving

    return {"key": serving.public_key_b64(ctx), "algorithm": "ed25519"}


class ModelPinIn(BaseModel):
    version: int | None = None


@router.put("/v1/me/model-pin")
def pin_model(body: ModelPinIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """Pin a model version (or ``null`` to follow the stable model). Honoured while that version is served."""
    import json as _json

    from sqlalchemy import select

    from moth_server import serving
    from moth_server.db import users

    if body.version is not None and body.version not in [v["version"] for v in serving.loaded_versions(ctx)]:
        raise HTTPException(409, "That model version is not being served right now.")
    with ctx.db.tx() as c:
        row = c.execute(select(users.c.settings).where(users.c.id == auth.uid)).first()
        s = _json.loads(row[0] or "{}")
        s["pinned_model_version"] = body.version
        c.execute(users.update().where(users.c.id == auth.uid).values(settings=_json.dumps(s)))
    return {"pinned_model_version": body.version, "served": serving.loaded_versions(ctx)}


@router.get("/v1/models/deployed/package")
def deployed_package(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    from fastapi.responses import FileResponse

    d = M.deployed(ctx)
    if not d:
        raise HTTPException(404, "No model is deployed on MOTH Cloud yet.")
    path, sha = M.package_archive(ctx, d["version"])
    return FileResponse(path, media_type="application/x-tar", filename=f"moth-model-v{d['version']}.tar",
                        headers={"X-Moth-Package-Sha256": sha})
