"""1.0.18: servers (SSH profiles) and engagements (authorized test scope) for the agent."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import time

from moth.security import engagements as E
from moth.security import scanner as SC
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


class ScanAsk(BaseModel):
    message: str


class ScanStart(BaseModel):
    message: str
    confirmed: bool = False


class StrongerIn(BaseModel):
    step_id: str
    confirmed: bool = False


class AuditIn(BaseModel):
    message: str
    project_id: int | None = None
    files: list[dict] = []          # attached files: [{"path": ..., "content": ...}]
    conversation_id: int | None = None
    save: bool = True


class ToChatIn(BaseModel):
    conversation_id: int | None = None
    question: str = ""


def _plan_out(plan: SC.ScanPlan) -> dict:
    return {"target": plan.target, "hosts": len(plan.hosts), "ports": plan.ports[:50], "port_count": len(plan.ports),
            "default_ports": plan.default_ports, "describe": plan.describe()}


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

    # ---- 2.0 chat pentesting -------------------------------------------------------------------------
    scans = SC.ScanManager(svc.paths.home, lambda e: svc.bus.publish("scan", e))
    svc.extras["scans"] = scans

    def found(fn):
        try:
            return fn()
        except KeyError:
            raise HTTPException(404, "scan not found") from None
        except SC.ScanRefused as e:
            raise HTTPException(400, str(e)) from None

    @app.post("/api/scans/parse", dependencies=deps)
    def parse_scan(body: ScanAsk):
        """Is this chat message asking for a scan? Nothing is contacted here."""
        try:
            plan = SC.parse_request(body.message)
        except SC.ScanRefused as e:
            return {"plan": None, "refused": str(e)}
        return {"plan": _plan_out(plan) if plan else None, "refused": None}

    @app.post("/api/scans", dependencies=deps)
    def start_scan(body: ScanStart):
        plan = found(lambda: SC.parse_request(body.message))
        if plan is None:
            raise HTTPException(400, "no scan target found in that message")
        row = found(lambda: scans.start(plan, body.confirmed))
        svc.db.log_activity("security", f"Scan of {plan.describe()} confirmed and started", None)
        return row

    @app.get("/api/scans", dependencies=deps)
    def list_scans():
        return scans.list()

    @app.get("/api/scans/{sid}", dependencies=deps)
    def get_scan(sid: str):
        return found(lambda: scans.get(sid))

    @app.post("/api/scans/{sid}/stop", dependencies=deps)
    def stop_scan(sid: str):
        return {"stopped": scans.stop(sid)}

    @app.post("/api/scans/stop-all", dependencies=deps)
    def stop_all_scans():
        return {"stopped": scans.stop()}

    @app.delete("/api/scans/{sid}", dependencies=deps)
    def delete_scan(sid: str):
        scans.delete(sid)
        return {"ok": True}

    @app.post("/api/scans/{sid}/stronger", dependencies=deps)
    def stronger(sid: str, body: StrongerIn):
        return found(lambda: scans.run_stronger(sid, body.step_id, body.confirmed))

    # ---- 2.1 security checks on your own files (nothing is contacted) -----------------------------------
    @app.post("/api/security/parse", dependencies=deps)
    def security_parse(body: ScanAsk):
        from moth.security import audit
        return {"tool": audit.parse_request(body.message)}

    @app.post("/api/security/audit", dependencies=deps)
    def security_audit(body: AuditIn):
        import json as _json

        from moth.security import audit
        tool = audit.parse_request(body.message)
        if tool is None:
            raise HTTPException(400, "Ask for a code, dependency or configuration check")
        files = [(str(f.get("path", ""))[:300], str(f.get("content", ""))) for f in body.files[:50]]
        root = svc.workspace(body.project_id).root if body.project_id is not None else None
        if tool == "config_audit" and (files or root):
            report = audit.config_audit(files or audit.project_configs(root))
        elif root is None:
            what = {"code_audit": "your code", "deps_audit": "your dependencies", "config_audit": "your configuration files"}[tool]
            raise HTTPException(409, f"Open the project in Projects (or attach the files) so MOTH can check {what}.")
        elif tool == "code_audit":
            report = audit.code_audit(root)
        elif tool == "deps_audit":
            report = audit.deps_audit(root)
        else:
            report = audit.config_audit(audit.project_configs(root))
        out = {"report": report, "conversation_id": body.conversation_id}
        if body.save:
            cid, now = body.conversation_id, time.time()
            if cid is None or not svc.db.one("SELECT id FROM conversations WHERE id=?", (cid,)):
                cid = int(svc.db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (?,?,?)",
                                         (body.project_id, report["kind"], now)).lastrowid)
            svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                           (cid, "user", body.message.strip()[:4000], None, now))
            svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                           (cid, "assistant", audit.report_markdown(report),
                            _json.dumps({"model": "MOTH security check", "report": report}), now + 0.001))
            svc.bus.publish("conversations", {"changed": [cid]})
            out["conversation_id"] = cid
        svc.db.log_activity("security", f"{report['kind']}: {report['total']} finding(s)", body.project_id)
        return out

    @app.post("/api/scans/{sid}/to-chat", dependencies=deps)
    def scan_to_chat(sid: str, body: ToChatIn):
        """Put the scan's summary into a conversation so follow-up questions have it as context."""
        scan = found(lambda: scans.get(sid, with_log=False))
        cid = body.conversation_id
        now = time.time()
        if cid is None or not svc.db.one("SELECT id FROM conversations WHERE id=?", (cid,)):
            cid = int(svc.db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (NULL,?,?)",
                                     (f"Scan of {scan['target']}"[:60], now)).lastrowid)
        if body.question.strip():
            svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                           (cid, "user", body.question.strip()[:4000], None, now))
        mid = svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                             (cid, "assistant", SC.summary_markdown(scan), '{"model": "MOTH scanner", "scan_id": "%s"}' % sid, now + 0.001)).lastrowid
        svc.bus.publish("conversations", {"changed": [cid]})
        return {"conversation_id": cid, "message_id": mid}

    @app.post("/api/engagements/check", dependencies=deps)
    def check(body: CheckIn):
        v = E.check(body.command)
        return {"ok": v.ok, "reason": v.reason, "targets": v.targets}
