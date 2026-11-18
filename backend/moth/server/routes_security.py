"""1.0.18: servers (SSH profiles) and engagements (authorized test scope) for the agent."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from moth.security import engagements as E
from moth.server.services import Services
from moth.workspace import servers as S


class ServerIn(BaseModel):
    name: str
    host: str
    user: str
    port: int = 22
    key_path: str | None = None


class EngagementIn(BaseModel):
    name: str
    scope: list[str]
    starts_at: float | None = None
    ends_at: float | None = None
    notes: str = ""


class ActiveIn(BaseModel):
    id: str | None = None


class CheckIn(BaseModel):
    command: str


def register(app: FastAPI, svc: Services, deps) -> None:
    def bad(fn):
        try:
            return fn()
        except (S.ServerError, ValueError) as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/api/servers", dependencies=deps)
    def list_servers():
        return S.all_()

    @app.post("/api/servers", dependencies=deps)
    def add_server(body: ServerIn):
        row = bad(lambda: S.add(body.name, body.host, body.user, body.port, body.key_path))
        svc.db.log_activity("servers", f"Saved server {row['name']} ({row['user']}@{row['host']})", None)
        return row

    @app.delete("/api/servers/{name}", dependencies=deps)
    def delete_server(name: str):
        S.remove(name)
        return {"ok": True}

    @app.get("/api/engagements", dependencies=deps)
    def list_engagements():
        return E.all_()

    @app.post("/api/engagements", dependencies=deps)
    def create_engagement(body: EngagementIn):
        eng = bad(lambda: E.create(body.name, body.scope, body.starts_at, body.ends_at, body.notes))
        svc.db.log_activity("security", f"Engagement '{eng['name']}' created ({len(eng['scope'])} scope entries)", None)
        return eng

    @app.delete("/api/engagements/{eid}", dependencies=deps)
    def delete_engagement(eid: str):
        E.delete(eid)
        return {"ok": True}

    @app.put("/api/engagements/active", dependencies=deps)
    def set_active(body: ActiveIn):
        bad(lambda: E.activate(body.id))
        eng = E.active()
        svc.db.log_activity("security", f"Engagement '{eng['name']}' is active" if eng else "No engagement active", None)
        return {"active": eng}

    @app.get("/api/engagements/{eid}/log", dependencies=deps)
    def engagement_log(eid: str, limit: int = 500):
        return E.read_log(eid, min(max(limit, 1), 5000))

    @app.post("/api/engagements/check", dependencies=deps)
    def check(body: CheckIn):
        v = E.check(body.command)
        return {"ok": v.ok, "reason": v.reason, "targets": v.targets}
