"""Long-lived backend services shared by the API routes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from moth.config import Paths
from moth.db import Database
from moth.events import EventBus
from moth.security.permissions import ApprovalBroker, PermissionEngine, PermissionSettings, Workspace
from moth.workspace.terminal import TerminalManager


class NotFound(LookupError):
    pass


@dataclass
class Services:
    paths: Paths
    db: Database
    bus: EventBus
    terminals: TerminalManager
    approvals: ApprovalBroker
    extras: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, paths: Paths) -> "Services":
        bus = EventBus()
        approvals = ApprovalBroker(notify=lambda req: bus.publish("approval", {"request": req.public()}))
        return cls(paths=paths, db=Database(paths.db), bus=bus, terminals=TerminalManager(), approvals=approvals)

    # ---- projects / workspaces -----------------------------------------
    def add_project(self, path: str) -> dict:
        p = Path(path).expanduser().resolve()
        if not p.is_dir():
            raise NotFound(f"directory does not exist: {p}")
        now = time.time()
        self.db.execute(
            "INSERT INTO projects(path, name, authorized, created_at, last_opened) VALUES (?,?,1,?,?) "
            "ON CONFLICT(path) DO UPDATE SET last_opened=excluded.last_opened, authorized=1",
            (str(p), p.name or str(p), now, now),
        )
        project = self.db.one("SELECT * FROM projects WHERE path=?", (str(p),))
        assert project
        self.db.log_activity("project", f"Opened workspace {p.name}", project["id"])
        return project

    def project(self, project_id: int) -> dict:
        row = self.db.one("SELECT * FROM projects WHERE id=? AND authorized=1", (project_id,))
        if not row:
            raise NotFound(f"project {project_id} not found or not authorised")
        return row

    def workspace(self, project_id: int) -> Workspace:
        return Workspace(Path(self.project(project_id)["path"]))

    def apply_chat_retention(self) -> int:
        """Delete conversations older than the chosen retention period (setting ``chat_retention_days``).

        0 or unset keeps conversations forever; nothing is deleted without this explicit setting.
        Age is measured from the latest message, so active conversations are kept."""
        days = self.db.get_setting("chat_retention_days")
        if type(days) not in (int, float) or days <= 0:
            return 0
        cutoff = time.time() - float(days) * 86400
        ids = [r["id"] for r in self.db.query(
            "SELECT c.id FROM conversations c WHERE COALESCE((SELECT MAX(ts) FROM messages m WHERE m.conversation_id=c.id),"
            " c.created_at) < ?", (cutoff,))]
        for cid in ids:
            self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        if ids:
            self.db.log_activity("chat", f"Deleted {len(ids)} conversation(s) older than {days:g} days (retention setting)")
            self.bus.publish("conversations", {"deleted": ids})
        return len(ids)

    def permission_engine(self) -> PermissionEngine:
        return PermissionEngine(PermissionSettings.from_dict(self.db.get_setting("permissions")))

    def shutdown(self) -> None:
        self.terminals.close_all()
        for ext in self.extras.values():
            stop = getattr(ext, "shutdown", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        self.db.close()
