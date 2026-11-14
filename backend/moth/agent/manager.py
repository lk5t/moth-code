"""Task lifecycle: persistence, background execution, cancellation, resume, revert."""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

from moth.agent.engine import AgentEngine, EngineConfig, TaskState
from moth.agent.memory import MemoryStore
from moth.agent.protocol import AgentLLM
from moth.agent.retrieval import CodeIndex
from moth.agent.tools import AgentContext
from moth.db import Database
from moth.events import EventBus
from moth.security.permissions import ApprovalBroker, PermissionEngine, Workspace
from moth.workspace.files import FileOps

ACTIVE = {"queued", "running"}
RESUMABLE = {"interrupted", "cancelled", "incomplete", "model_incapable", "failed", "needs_review", "plan_ready"}


class TaskManager:
    def __init__(self, db: Database, bus: EventBus, approvals: ApprovalBroker):
        self.db = db
        self.bus = bus
        self.approvals = approvals
        self.memory = MemoryStore(db)
        self.index = CodeIndex(db)
        self._cancel: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        # Recovery: tasks that were running when the backend stopped can be resumed.
        db.execute("UPDATE tasks SET status='interrupted', updated_at=? WHERE status IN ('queued','running')",
                   (time.time(),))

    # ---- persistence --------------------------------------------------------------
    def _save(self, project_id: int, s: TaskState) -> None:
        now = time.time()
        payload = (json.dumps(s.plan), json.dumps({"steps": s.steps, "changes": s.changes, "notes": s.notes,
                                                    "plan_approved": s.plan_approved}),
                   json.dumps(s.report) if s.report else None, s.error, s.status, now, s.id)
        cur = self.db.execute("UPDATE tasks SET plan=?, steps=?, result=?, error=?, status=?, updated_at=? WHERE id=?",
                              payload)
        if cur.rowcount == 0:
            self.db.execute("INSERT INTO tasks(id, project_id, goal, status, plan, steps, result, error, created_at, "
                            "updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (s.id, project_id, s.goal, s.status, payload[0], payload[1], payload[2], s.error, now, now))

    def _load(self, task_id: str) -> tuple[int, TaskState]:
        row = self.db.one("SELECT * FROM tasks WHERE id=?", (task_id,))
        if not row:
            raise LookupError("task not found")
        extra = json.loads(row["steps"] or "{}")
        s = TaskState(row["id"], row["goal"], row["status"], json.loads(row["plan"] or "[]"),
                      extra.get("steps", []), extra.get("changes", []), json.loads(row["result"]) if row["result"] else None,
                      row["error"], extra.get("notes", []), bool(extra.get("plan_approved")))
        return row["project_id"], s

    def get(self, task_id: str) -> dict[str, Any]:
        pid, s = self._load(task_id)
        return {"id": s.id, "project_id": pid, "goal": s.goal, "status": s.status, "plan": s.plan, "steps": s.steps,
                "changes": [{k: v for k, v in c.items() if k not in ("before", "after")} for c in s.changes],
                "report": s.report, "error": s.error, "notes": s.notes, "plan_approved": s.plan_approved}

    def list(self, project_id: int | None) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT id, project_id, goal, status, error, created_at, updated_at FROM tasks "
                             "WHERE project_id IS ? ORDER BY created_at DESC LIMIT 100", (project_id,))
        return rows

    # ---- execution -----------------------------------------------------------------
    def start(self, project_id: int, workspace: Workspace, goal: str, llm: AgentLLM, permissions: PermissionEngine,
              base_prompt: str, config: EngineConfig | None = None, task_id: str | None = None,
              memory: MemoryStore | None = None, index: CodeIndex | None = None) -> str:
        if any(t.is_alive() for t in self._threads.values()):
            raise RuntimeError("another task is running; cancel it or wait for it to finish")
        if task_id:
            pid, state = self._load(task_id)
            if state.status not in RESUMABLE:
                raise RuntimeError(f"task is {state.status}; only stopped tasks can be resumed")
            state.error = None
            state.report = None
        else:
            state = TaskState(uuid.uuid4().hex[:12], goal.strip())
        cancel = threading.Event()
        self._cancel[state.id] = cancel

        def emit(event: dict[str, Any]) -> None:
            self.bus.publish("task", {"project_id": project_id, **event, "task_id": state.id})

        ctx = AgentContext(workspace, project_id, permissions, self.approvals, memory or self.memory, index or self.index, cancel, emit,
                           task_id=state.id)
        engine = AgentEngine(llm, ctx, base_prompt, config, on_update=lambda s: self._save(project_id, s))
        state.status = "queued"
        self._save(project_id, state)
        self.db.log_activity("task", f"{'Resumed' if task_id else 'Started'} task: {state.goal[:120]}", project_id)

        def work() -> None:
            engine.run(state)
            self._save(project_id, state)
            self.db.log_activity("task", f"Task {state.status}: {state.goal[:120]}", project_id)
            self._cancel.pop(state.id, None)

        t = threading.Thread(target=work, daemon=True, name=f"task-{state.id}")
        self._threads[state.id] = t
        t.start()
        return state.id

    def cancel(self, task_id: str) -> bool:
        ev = self._cancel.get(task_id)
        if not ev:
            return False
        ev.set()
        return True

    def wait(self, task_id: str, timeout: float | None = None) -> None:
        t = self._threads.get(task_id)
        if t:
            t.join(timeout)

    def set_plan(self, task_id: str, plan: list[str]) -> None:
        """1.0 plan first: the user approves (and may edit) the plan before MOTH changes anything."""
        pid, state = self._load(task_id)
        if state.status != "plan_ready":
            raise RuntimeError(f"task is {state.status}; only a plan waiting for approval can be changed")
        state.plan = [p.strip() for p in plan if p.strip()][:30]
        state.plan_approved = True
        self._save(pid, state)

    def checkpoints(self, project_id: int) -> list[dict[str, Any]]:
        """1.0 undo anything: every finished task that changed files is a point the project can go back to."""
        out = []
        for row in self.db.query("SELECT id, goal, status, steps, updated_at FROM tasks WHERE project_id IS ? "
                                 "ORDER BY created_at DESC LIMIT 200", (project_id,)):
            changes = json.loads(row["steps"] or "{}").get("changes") or []
            if changes and row["status"] != "reverted":
                out.append({"task_id": row["id"], "goal": row["goal"], "status": row["status"], "at": row["updated_at"],
                            "files": sorted({c.get("path", "") for c in changes if c.get("path")})})
        return out

    def restore(self, project_id: int, task_id: str, workspace: Workspace, memory: MemoryStore | None = None) -> list[str]:
        """Go back to just before ``task_id``: undo it and every later task, newest first."""
        points = self.checkpoints(project_id)
        ids = [p["task_id"] for p in points]
        if task_id not in ids:
            raise RuntimeError("that change can no longer be undone")
        files: list[str] = []
        for tid in ids[: ids.index(task_id) + 1]:
            files += self.revert(tid, workspace, memory)
        return sorted(set(files))

    def revert(self, task_id: str, workspace: Workspace, memory: MemoryStore | None = None) -> list[str]:
        """Undo the file changes a task made (in reverse order)."""
        if task_id in self._cancel:
            raise RuntimeError("cannot revert a running task")
        pid, state = self._load(task_id)
        ops = FileOps(workspace)
        reverted = []
        for c in reversed(state.changes):
            if c["type"] == "create":
                try:
                    ops.delete(c["path"])
                except FileNotFoundError:
                    pass
            elif c["type"] in ("modify", "delete") and c.get("before") is not None:
                ops.write(c["path"], c["before"])
            else:
                continue
            reverted.append(c["path"])
        state.notes.append(f"Reverted changes to: {', '.join(reverted) or 'nothing'}")
        if reverted:  # 1.0 learns from your fixes: an undone change is remembered for later tasks
            try:
                (memory or self.memory).add(pid, "error", f"The user undid MOTH's change: {state.goal[:150]}",
                                            "The user reverted these changes, so this approach was not wanted: "
                                            + ", ".join(reverted))
            except Exception:  # noqa: BLE001 — remembering is best effort
                pass
        state.changes = []
        state.status = "reverted"
        self._save(pid, state)
        self.db.log_activity("task", f"Reverted task changes: {state.goal[:100]}", pid)
        return reverted

    def shutdown(self) -> None:
        for ev in self._cancel.values():
            ev.set()
