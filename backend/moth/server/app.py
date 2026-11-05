"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import os
import platform
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from moth import __version__
from moth.config import Paths
from moth.security.permissions import PathOutsideWorkspace
from moth.server.services import NotFound, Services
from moth.workspace.files import FileOps, FileTooLarge
from moth.workspace.git import Git, GitError, git_available
from moth.workspace.scanner import file_tree, scan_project

ALLOWED_ORIGINS = [
    "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
    "http://localhost:1420", "http://127.0.0.1:1420",
]


def hardware_info() -> dict[str, Any]:
    info: dict[str, Any] = {
        "platform": platform.platform(), "python": platform.python_version(),
        "cpu_count": os.cpu_count(), "torch": None, "cuda": False, "gpus": [],
    }
    try:
        import torch

        info["torch"] = torch.__version__
        if torch.cuda.is_available():
            info["cuda"] = True
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                info["gpus"].append({"index": i, "name": props.name, "memory_gb": round(props.total_memory / 2**30, 1)})
    except Exception as e:  # torch missing or broken driver: report, never crash
        info["torch_error"] = str(e)
    return info


class ProjectIn(BaseModel):
    path: str


class FileWrite(BaseModel):
    path: str
    content: str


class FsOp(BaseModel):
    op: str  # mkdir | rename | delete
    path: str
    to: str | None = None


class TerminalIn(BaseModel):
    project_id: int | None = None
    cwd: str | None = None


class CommandIn(BaseModel):
    command: str
    timeout: float | None = None


class CommitIn(BaseModel):
    message: str
    paths: list[str] | None = None


class ApprovalIn(BaseModel):
    approved: bool


def create_app(paths: Paths, token: str | None = None, services: Services | None = None) -> FastAPI:
    svc = services or Services.create(paths)
    api_token = token if token is not None else os.environ.get("MOTH_API_TOKEN") or ""
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        svc.shutdown()

    app = FastAPI(title="MOTH Code backend", version=__version__, lifespan=lifespan)
    app.state.services = svc
    app.add_middleware(
        CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    def auth(request: Request) -> None:
        if not api_token:
            return
        header = request.headers.get("authorization", "")
        if not secrets.compare_digest(header, f"Bearer {api_token}"):
            raise HTTPException(401, "invalid or missing API token")

    @app.exception_handler(NotFound)
    async def _nf(_: Request, exc: NotFound):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(PathOutsideWorkspace)
    async def _pow(_: Request, exc: PathOutsideWorkspace):
        return JSONResponse({"detail": str(exc)}, status_code=403)

    @app.exception_handler(GitError)
    async def _git(_: Request, exc: GitError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(FileTooLarge)
    async def _big(_: Request, exc: FileTooLarge):
        return JSONResponse({"detail": str(exc)}, status_code=413)

    A = [Depends(auth)]

    # ---- system ---------------------------------------------------------
    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__, "home": str(paths.home)}

    @app.get("/api/system", dependencies=A)
    def system():
        return {**hardware_info(), "git": git_available()}

    @app.get("/api/settings", dependencies=A)
    def get_settings():
        rows = svc.db.query("SELECT key, value FROM settings")
        import json

        return {r["key"]: json.loads(r["value"]) for r in rows}

    @app.put("/api/settings", dependencies=A)
    def put_settings(values: dict[str, Any]):
        for k, v in values.items():
            svc.db.set_setting(k, v)
        svc.bus.publish("settings", {"keys": list(values)})
        return get_settings()

    @app.get("/api/activity", dependencies=A)
    def activity(project_id: int | None = None, limit: int = 200):
        if project_id is None:
            return svc.db.query("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,))
        return svc.db.query("SELECT * FROM activity WHERE project_id=? ORDER BY id DESC LIMIT ?", (project_id, limit))

    # ---- projects & files ------------------------------------------------
    @app.get("/api/projects", dependencies=A)
    def projects():
        return svc.db.query("SELECT * FROM projects WHERE authorized=1 ORDER BY last_opened DESC")

    @app.post("/api/projects", dependencies=A)
    def add_project(body: ProjectIn):
        return svc.add_project(body.path)

    @app.delete("/api/projects/{pid}", dependencies=A)
    def remove_project(pid: int):
        svc.project(pid)
        svc.db.execute("UPDATE projects SET authorized=0 WHERE id=?", (pid,))
        return {"ok": True}

    @app.get("/api/projects/{pid}/tree", dependencies=A)
    def tree(pid: int):
        return file_tree(svc.workspace(pid).root)

    @app.get("/api/projects/{pid}/scan", dependencies=A)
    def scan(pid: int):
        s = scan_project(svc.workspace(pid).root)
        return {**s.__dict__, "description": s.describe()}

    @app.get("/api/projects/{pid}/file", dependencies=A)
    def read_file(pid: int, path: str):
        ops = FileOps(svc.workspace(pid))
        try:
            return {"path": path, "content": ops.read(path)}
        except FileNotFoundError:
            raise NotFound(f"file not found: {path}") from None
        except ValueError as e:
            raise HTTPException(415, str(e)) from None

    @app.put("/api/projects/{pid}/file", dependencies=A)
    def write_file(pid: int, body: FileWrite):
        result = FileOps(svc.workspace(pid)).write(body.path, body.content)
        svc.db.log_activity("file", f"Saved {body.path}", pid)
        svc.bus.publish("files", {"project_id": pid, "path": body.path, "change": "write"})
        return result

    @app.post("/api/projects/{pid}/fs", dependencies=A)
    def fs_op(pid: int, body: FsOp):
        ops = FileOps(svc.workspace(pid))
        if body.op == "mkdir":
            result = ops.mkdir(body.path)
        elif body.op == "rename" and body.to:
            result = ops.rename(body.path, body.to)
        elif body.op == "delete":  # user-initiated from the explorer (UI confirms first)
            result = ops.delete(body.path)
        else:
            raise HTTPException(400, f"unsupported operation {body.op}")
        svc.db.log_activity("file", f"{body.op} {body.path}", pid)
        svc.bus.publish("files", {"project_id": pid, "path": body.path, "change": body.op})
        return result

    # ---- git --------------------------------------------------------------
    @app.get("/api/projects/{pid}/git/status", dependencies=A)
    def git_status(pid: int):
        g = Git(svc.workspace(pid).root)
        if not git_available():
            return {"available": False, "repo": False, "entries": []}
        if not g.is_repo():
            return {"available": True, "repo": False, "entries": []}
        return {"available": True, "repo": True, "branch": g.branch(), "entries": g.status()}

    @app.get("/api/projects/{pid}/git/diff", dependencies=A)
    def git_diff(pid: int, path: str | None = None, staged: bool = False):
        return {"diff": Git(svc.workspace(pid).root).diff(path, staged)}

    @app.get("/api/projects/{pid}/git/log", dependencies=A)
    def git_log(pid: int, limit: int = 30):
        return Git(svc.workspace(pid).root).log(limit)

    @app.post("/api/projects/{pid}/git/init", dependencies=A)
    def git_init(pid: int):
        Git(svc.workspace(pid).root).init()
        return {"ok": True}

    @app.post("/api/projects/{pid}/git/commit", dependencies=A)
    def git_commit(pid: int, body: CommitIn):
        g = Git(svc.workspace(pid).root)
        g.add(body.paths)
        sha = g.commit(body.message)
        svc.db.log_activity("git", f"Committed {sha[:8]}: {body.message}", pid)
        return {"hash": sha}

    # ---- terminal -----------------------------------------------------------
    @app.post("/api/terminals", dependencies=A)
    def new_terminal(body: TerminalIn):
        if body.project_id is not None:
            root = svc.workspace(body.project_id).root
            session = svc.terminals.create(body.cwd or root)
        else:
            session = svc.terminals.create(body.cwd or Path.home())
        return {"id": session.id, "cwd": str(session.cwd)}

    @app.post("/api/terminals/{sid}/run", dependencies=A)
    def run_in_terminal(sid: str, body: CommandIn):
        session = svc.terminals.get(sid)
        if not session:
            raise NotFound("terminal session not found")

        def out(text: str) -> None:
            svc.bus.publish("terminal", {"session": sid, "kind": "output", "data": text})

        def done(result) -> None:
            svc.bus.publish("terminal", {
                "session": sid, "kind": "exit", "code": result.exit_code, "cwd": str(session.cwd),
                "cancelled": result.cancelled, "timed_out": result.timed_out, "duration": result.duration,
            })

        if not session.execute(body.command, out, done, body.timeout):
            raise HTTPException(409, "a command is already running in this terminal")
        return {"ok": True}

    @app.post("/api/terminals/{sid}/cancel", dependencies=A)
    def cancel_terminal(sid: str):
        session = svc.terminals.get(sid)
        if not session:
            raise NotFound("terminal session not found")
        return {"cancelled": session.cancel()}

    @app.delete("/api/terminals/{sid}", dependencies=A)
    def close_terminal(sid: str):
        svc.terminals.close(sid)
        return {"ok": True}

    # ---- approvals ----------------------------------------------------------
    @app.get("/api/approvals", dependencies=A)
    def approvals():
        return svc.approvals.pending()

    @app.post("/api/approvals/{rid}", dependencies=A)
    def resolve_approval(rid: str, body: ApprovalIn):
        if not svc.approvals.resolve(rid, body.approved):
            raise NotFound("approval request not found or already resolved")
        return {"ok": True}

    # ---- events -------------------------------------------------------------
    @app.websocket("/ws/events")
    async def events(ws: WebSocket, token: str = Query(default="")):
        if api_token and not secrets.compare_digest(token, api_token):
            await ws.close(code=4401)
            return
        await ws.accept()
        queue = svc.bus.subscribe_async()
        try:
            await ws.send_json({"topic": "hello", "version": __version__})
            while True:
                event = await queue.get()
                await ws.send_json(event)
        except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
            pass
        finally:
            svc.bus.unsubscribe_async(queue)

    # Later phases register their routers here (model, training, agent, ...).
    from moth.server import extensions

    extensions.register_all(app, svc, A)
    return app
