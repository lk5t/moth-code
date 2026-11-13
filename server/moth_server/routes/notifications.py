"""Owner notifications (0.7.1): the events the Owner needs to know about, from real evolution events.

Only the Owner can read or acknowledge them — enforced here by ``require_owner`` (HTTP 403 for any
other account), not only hidden in the interface. Nothing is stored twice: notifications are a
filtered view of ``evolution_events``; the Owner's read position is kept in ``server_config``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import desc, select

from moth_server.context import Ctx, get_ctx
from moth_server.db import evolution_events
from moth_server.deps import Auth, require_owner

router = APIRouter(prefix="/v1/admin/notifications", tags=["notifications"])

# event kind → (category, title)
KINDS: dict[str, tuple[str, str]] = {
    "cycle.completed": ("promotion", "New MOTH version promoted"),
    "deploy.verified": ("deployment", "Deployment verified"),
    "deploy.done": ("deployment", "New version deployed for monitoring"),
    "deploy.rollback": ("rollback", "Deployment rolled back"),
    "deploy.failed": ("deployment", "Deployment failed"),
    "cycle.rejected": ("training", "Training cycle finished without an improvement"),
    "model.milestone": ("improvement", "Capability milestone reached"),
    "growth.passed": ("improvement", "Larger architecture passed evaluation"),
    "experiment.failed": ("attention", "Experiment failed"),
    "worker.disconnected": ("worker", "Worker stopped reporting"),
    "engine.paused": ("attention", "Evolution paused itself"),
    "engine.stalled": ("infrastructure", "Training stalled and was repaired"),
    "engine.error": ("infrastructure", "Evolution engine error"),
    "storage.retention_failed": ("infrastructure", "Old model cleanup did not finish"),
    "data.failed": ("attention", "Dataset preparation failed"),
}


def _key(uid: int) -> str:
    return f"notifications_read:{uid}"


def items(ctx: Ctx, uid: int, limit: int = 50) -> dict[str, Any]:
    rows = ctx.db.all(select(evolution_events).where(evolution_events.c.kind.in_(tuple(KINDS)))
                      .order_by(desc(evolution_events.c.id)).limit(max(1, min(200, limit))))
    read = int(ctx.db.get_config(_key(uid), 0) or 0)
    out = [{"id": r["id"], "ts": r["ts"], "kind": r["kind"], "category": KINDS[r["kind"]][0],
            "title": KINDS[r["kind"]][1], "message": r["message"], "level": r["level"],
            "unread": r["id"] > read} for r in rows]
    return {"items": out, "unread": sum(1 for n in out if n["unread"]), "read_up_to": read}


@router.get("")
def list_notifications(limit: int = 50, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return items(ctx, auth.uid, limit)


class ReadIn(BaseModel):
    up_to_id: int = Field(ge=0)


@router.post("/read")
def mark_read(body: ReadIn, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    cur = int(ctx.db.get_config(_key(auth.uid), 0) or 0)
    ctx.db.set_config(_key(auth.uid), max(cur, body.up_to_id))
    return items(ctx, auth.uid)
