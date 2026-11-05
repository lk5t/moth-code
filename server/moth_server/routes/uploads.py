"""Resumable, chunked model uploads (Owner only).

1. ``POST /v1/admin/models/uploads`` with name, total size, SHA-256 of the archive and the package
   manifest. The server checks the manifest, free disk space and duplicates *before* any bytes are
   sent, reserves a release (status ``uploading``) and returns the upload id and chunk size. Starting
   the same archive again resumes the existing upload.
2. ``PUT …/uploads/{id}/chunks/{n}`` — each chunk carries its own SHA-256 (``X-Chunk-Sha256``);
   re-sending a chunk is harmless.
3. ``GET …/uploads/{id}`` — which chunks the server already has (resume after interruption).
4. ``POST …/uploads/{id}/complete`` — the archive is assembled, its SHA-256 verified, the package
   validated and stored, and evaluation starts automatically.

Incomplete uploads expire after 24 hours of inactivity; their temporary files are removed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from moth_server import models as M
from moth_server.audit import audit
from moth_server.context import Ctx, get_ctx
from moth_server.db import model_releases, now, uploads
from moth_server.deps import Auth, owner_reauthed, require_owner

router = APIRouter(prefix="/v1/admin/models/uploads", tags=["models"])
DEFAULT_CHUNK = 8 * 1024 * 1024
EXPIRE_S = 24 * 3600
MAX_UPLOAD = 64 * 2**30


def upload_dir(ctx: Ctx, uid: str) -> Path:
    return ctx.settings.storage_dir / "uploads" / uid


class StartIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    size: int = Field(gt=0, le=MAX_UPLOAD)
    sha256: str = Field(pattern="^[0-9a-f]{64}$")
    manifest: dict = {}
    chunk_size: int | None = Field(default=None, ge=256 * 1024)


def public(row: dict) -> dict:
    received = json.loads(row["received"])
    total = -(-row["size"] // row["chunk_size"])
    return {"id": row["id"], "name": row["name"], "size": row["size"], "sha256": row["sha256"],
            "chunk_size": row["chunk_size"], "chunks": total, "received": sorted(received),
            "missing": [i for i in range(total) if i not in set(received)], "status": row["status"],
            "error": row["error"], "release_version": row["release_version"], "updated_at": row["updated_at"]}


def _get(ctx: Ctx, uid: str) -> dict:
    row = ctx.db.one(select(uploads).where(uploads.c.id == uid))
    if not row:
        raise HTTPException(404, "Unknown upload (it may have expired). Start the upload again.")
    if row["status"] == "uploading":  # trust the disk, not the record: lost chunks are simply sent again
        received = json.loads(row["received"])
        present = [i for i in received if (upload_dir(ctx, uid) / f"{i:06d}.chunk").exists()]
        if len(present) != len(received):
            upload_dir(ctx, uid).mkdir(parents=True, exist_ok=True)
            with ctx.db.tx() as c:
                c.execute(uploads.update().where(uploads.c.id == uid).values(received=json.dumps(present)))
            row["received"] = json.dumps(present)
    return row


@router.post("")
def start(body: StartIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    m = body.manifest or {}
    problems = []
    if m.get("architecture") != "moth-decoder-v1":
        problems.append("only MOTH models (architecture moth-decoder-v1) can be published")
    if not m.get("sha256"):
        problems.append("the package manifest has no weights checksum")
    if problems:
        raise HTTPException(422, "; ".join(problems))
    dup = ctx.db.one(select(model_releases.c.version, model_releases.c.status)
                     .where(model_releases.c.sha256 == m["sha256"],
                            model_releases.c.status.notin_(("failed", "uploading"))))
    if dup:
        rel = M.release(ctx, dup["version"])
        return {"duplicate": True, "release": rel,
                "message": f"These weights are already on MOTH Cloud as release v{dup['version']} ({dup['status']})."}
    existing = ctx.db.one(select(uploads).where(uploads.c.sha256 == body.sha256, uploads.c.status == "uploading",
                                                uploads.c.user_id == auth.uid))
    if existing:
        return {"duplicate": False, "resumed": True, "upload": public(_get(ctx, existing["id"]))}
    free = shutil.disk_usage(ctx.settings.storage_dir).free
    if free < body.size * 3 + 512 * 2**20:
        raise HTTPException(507, f"MOTH Cloud does not have enough free disk space for this model "
                                 f"({body.size * 3 / 2**30:.1f} GB needed, {free / 2**30:.1f} GB free).")
    chunk = min(body.chunk_size or DEFAULT_CHUNK, ctx.settings.max_upload_chunk)
    uid = uuid.uuid4().hex
    version = M.reserve(ctx, body.name, {"type": "upload"}, auth.uid, sha256=m["sha256"], size=body.size,
                        info={k: m.get(k) for k in ("architecture", "params", "context_length", "tokenizer_fingerprint",
                                                    "dtype")})
    t = now()
    with ctx.db.tx() as c:
        c.execute(uploads.insert().values(id=uid, user_id=auth.uid, name=body.name, size=body.size, sha256=body.sha256,
                                          chunk_size=chunk, received="[]", manifest=json.dumps(m)[:20000],
                                          status="uploading", release_version=version, created_at=t, updated_at=t))
    upload_dir(ctx, uid).mkdir(parents=True, exist_ok=True)
    return {"duplicate": False, "resumed": False, "upload": public(_get(ctx, uid))}


@router.get("/{uid}")
def status(uid: str, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return public(_get(ctx, uid))


@router.put("/{uid}/chunks/{index}")
async def put_chunk(uid: str, index: int, request: Request, x_chunk_sha256: str = Header(...),
                    auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    row = _get(ctx, uid)
    if row["status"] != "uploading":
        raise HTTPException(409, f"This upload is {row['status']}.")
    total = -(-row["size"] // row["chunk_size"])
    if not 0 <= index < total:
        raise HTTPException(422, "Chunk index out of range.")
    expected = row["chunk_size"] if index < total - 1 else row["size"] - row["chunk_size"] * (total - 1)
    h = hashlib.sha256()
    part = upload_dir(ctx, uid) / f"{index:06d}.part"
    size = 0
    with open(part, "wb") as f:
        async for data in request.stream():
            size += len(data)
            if size > expected:
                break
            h.update(data)
            f.write(data)
    if size != expected or h.hexdigest() != x_chunk_sha256.lower():
        part.unlink(missing_ok=True)
        raise HTTPException(422, f"Chunk {index} was damaged in transit (size or checksum mismatch); send it again.")
    part.rename(part.with_suffix(".chunk"))
    with ctx.db.tx() as c:
        fresh = c.execute(select(uploads.c.received).where(uploads.c.id == uid)).first()
        received = sorted(set(json.loads(fresh[0])) | {index})
        c.execute(uploads.update().where(uploads.c.id == uid).values(received=json.dumps(received), updated_at=now()))
    return {"index": index, "received": len(received), "chunks": total}


def _fail(ctx: Ctx, row: dict, msg: str) -> None:
    with ctx.db.tx() as c:
        c.execute(uploads.update().where(uploads.c.id == row["id"]).values(status="failed", error=msg[:2000],
                                                                         updated_at=now()))


_complete_locks: dict[str, threading.Lock] = {}


@router.post("/{uid}/complete")
def complete(uid: str, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    lock = _complete_locks.setdefault(uid, threading.Lock())
    with lock:  # a retried request waits for the first one instead of racing it
        return _complete(uid, auth, ctx)


def _complete(uid: str, auth: Auth, ctx: Ctx):
    row = _get(ctx, uid)
    if row["status"] == "complete":
        return {"upload": public(row), "release": M.release(ctx, row["release_version"])}
    if row["status"] != "uploading":
        raise HTTPException(409, f"This upload is {row['status']}: {row['error'] or 'start the upload again'}")
    pub = public(row)
    if pub["missing"]:
        raise HTTPException(409, f"{len(pub['missing'])} chunk(s) are still missing; resume the upload.")
    d = upload_dir(ctx, uid)
    archive = d / "package.tar"
    h = hashlib.sha256()
    with open(archive, "wb") as out:
        for i in range(pub["chunks"]):
            with open(d / f"{i:06d}.chunk", "rb") as f:
                for data in iter(lambda: f.read(1 << 20), b""):
                    h.update(data)
                    out.write(data)
    if h.hexdigest() != row["sha256"]:
        shutil.rmtree(d, ignore_errors=True)
        _fail(ctx, row, "The assembled upload does not match its SHA-256.")
        M._set(ctx, row["release_version"], "failed", error="Upload was corrupted (checksum mismatch); upload it again.")
        raise HTTPException(422, "The upload was corrupted (checksum mismatch). Please upload the model again.")
    try:
        rel = M.register_upload(ctx, archive, row["name"], auth.uid, version=row["release_version"])
    except M.ReleaseError as e:  # the package itself is invalid: permanent, clean up
        shutil.rmtree(d, ignore_errors=True)
        _fail(ctx, row, str(e))
        raise HTTPException(422, str(e)) from None
    except Exception as e:  # noqa: BLE001 — a server-side problem: keep the chunks so a retry can succeed
        archive.unlink(missing_ok=True)
        M.log.exception("processing upload %s failed", uid)
        M._set(ctx, row["release_version"], error=f"MOTH Cloud could not process the upload yet ({type(e).__name__}); "
                                                  "it is retried automatically.")
        raise HTTPException(503, "MOTH Cloud could not process the upload right now; it will be retried.") from None
    shutil.rmtree(d, ignore_errors=True)
    with ctx.db.tx() as c:
        c.execute(uploads.update().where(uploads.c.id == uid).values(status="complete", updated_at=now()))
    audit(ctx.db, "models.upload_completed", auth.uid, f"release:{rel['version']}", {"size": row["size"]})
    M.evaluate_in_background(ctx, rel["version"], auth.uid)
    return {"upload": public(_get(ctx, uid)), "release": rel}


@router.delete("/{uid}")
def cancel(uid: str, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    row = _get(ctx, uid)
    if row["status"] == "uploading":
        shutil.rmtree(upload_dir(ctx, uid), ignore_errors=True)
        _fail(ctx, row, "Cancelled by the Owner.")
        M._set(ctx, row["release_version"], "failed", error="Upload was cancelled.")
    return {"ok": True}


def expire_stale(ctx: Ctx, max_age: float = EXPIRE_S) -> list[str]:
    cutoff = now() - max_age
    expired = []
    for row in ctx.db.all(select(uploads).where(uploads.c.status == "uploading", uploads.c.updated_at < cutoff)):
        shutil.rmtree(upload_dir(ctx, row["id"]), ignore_errors=True)
        with ctx.db.tx() as c:
            c.execute(uploads.update().where(uploads.c.id == row["id"]).values(
                status="expired", error="No data received for 24 hours; the partial upload was removed.",
                updated_at=now()))
        M._set(ctx, row["release_version"], "failed", error="The upload was not completed and has expired.")
        expired.append(row["id"])
    return expired


def setup(ctx: Ctx) -> None:
    if ctx.extras.get("disable_background"):
        return
    stop = threading.Event()

    def loop() -> None:
        while not stop.wait(3600):
            try:
                expire_stale(ctx)
            except Exception:  # noqa: BLE001
                M.log.exception("upload cleanup failed")

    threading.Thread(target=loop, daemon=True, name="upload-cleanup").start()
