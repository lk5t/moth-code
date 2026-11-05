"""Autonomous agent tasks and project memory routes."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from moth.agent.engine import EngineConfig
from moth.agent.manager import TaskManager
from moth.inference.local import NoModelLoaded
from moth.policy.engine import PolicyEngine
from moth.server.services import NotFound, Services


class TaskIn(BaseModel):
    project_id: int
    goal: str
    max_steps: int = 25
    verify: bool = True


class MemoryIn(BaseModel):
    project_id: int | None = None
    kind: str = "note"
    title: str
    content: str


class MemoryPatch(BaseModel):
    kind: str | None = None
    title: str | None = None
    content: str | None = None
    verified: bool | None = None


def register(app: FastAPI, svc: Services, deps) -> None:
    manager = TaskManager(svc.db, svc.bus, svc.approvals)
    svc.extras["tasks"] = manager

    def agent_llm():
        router = svc.extras.get("inference_router")
        if router is not None:
            return router.agent_llm()
        from moth.inference.local import LocalAgentLLM

        return LocalAgentLLM(svc.extras["local_inference"])

    @app.get("/api/tasks", dependencies=deps)
    def tasks(project_id: int):
        return manager.list(project_id)

    @app.get("/api/tasks/{task_id}", dependencies=deps)
    def task(task_id: str):
        try:
            return manager.get(task_id)
        except LookupError:
            raise NotFound("task not found") from None

    def _start(project_id: int, goal: str, cfg: EngineConfig, task_id: str | None = None):
        if not goal.strip():
            raise HTTPException(422, "describe the task")
        pol = PolicyEngine.load(svc.paths.policy)
        decision = pol.check_input(goal)
        if not decision.allowed:
            raise HTTPException(422, decision.message)
        try:
            llm = agent_llm()
        except NoModelLoaded as e:
            raise HTTPException(409, str(e)) from None
        except PermissionError as e:
            raise HTTPException(403, str(e)) from None
        try:
            tid = manager.start(project_id, svc.workspace(project_id), goal, llm, svc.permission_engine(),
                                pol.system_prompt, cfg, task_id=task_id)
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None
        return manager.get(tid)

    @app.post("/api/tasks", dependencies=deps)
    def start(body: TaskIn):
        svc.project(body.project_id)
        return _start(body.project_id, body.goal, EngineConfig(max_steps=body.max_steps, verify=body.verify))

    @app.post("/api/tasks/{task_id}/resume", dependencies=deps)
    def resume(task_id: str):
        t = task(task_id)
        return _start(t["project_id"], t["goal"], EngineConfig(), task_id=task_id)

    @app.post("/api/tasks/{task_id}/cancel", dependencies=deps)
    def cancel(task_id: str):
        return {"cancelled": manager.cancel(task_id)}

    @app.post("/api/tasks/{task_id}/revert", dependencies=deps)
    def revert(task_id: str):
        t = task(task_id)
        try:
            files = manager.revert(task_id, svc.workspace(t["project_id"]))
        except RuntimeError as e:
            raise HTTPException(409, str(e)) from None
        for f in files:
            svc.bus.publish("files", {"project_id": t["project_id"], "path": f, "change": "revert"})
        return {"reverted": files}

    # ---- memory ----------------------------------------------------------------------
    @app.get("/api/memory", dependencies=deps)
    def memories(project_id: int | None = None, kind: str | None = None, q: str | None = None):
        if q:
            return manager.memory.search(project_id, q, limit=20)
        return manager.memory.list(project_id, kind)

    @app.post("/api/memory", dependencies=deps)
    def add_memory(body: MemoryIn):
        try:
            mid = manager.memory.add(body.project_id, body.kind, body.title, body.content, verified=True)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        return {"id": mid}

    @app.patch("/api/memory/{memory_id}", dependencies=deps)
    def patch_memory(memory_id: int, body: MemoryPatch):
        manager.memory.update(memory_id, **body.model_dump(exclude_none=True))
        return {"ok": True}

    @app.delete("/api/memory/{memory_id}", dependencies=deps)
    def delete_memory(memory_id: int):
        manager.memory.delete(memory_id)
        return {"ok": True}

    @app.post("/api/projects/{pid}/index", dependencies=deps)
    def reindex(pid: int):
        return manager.index.update(pid, svc.workspace(pid).root)

    @app.get("/api/projects/{pid}/search", dependencies=deps)
    def search(pid: int, q: str):
        svc.project(pid)
        return manager.index.search(pid, q, limit=20)
