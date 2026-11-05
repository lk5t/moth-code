"""Append-only security/administration audit log."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.engine import Connection

from moth_server.db import Database, audit_log, now


def audit(db: Database, action: str, actor_id: int | None = None, target: str | None = None,
          detail: dict[str, Any] | None = None, ip: str | None = None, conn: Connection | None = None) -> None:
    values = dict(ts=now(), actor_id=actor_id, action=action, target=target,
                  detail=json.dumps(detail or {}), ip=ip)
    if conn is not None:
        conn.execute(audit_log.insert().values(**values))
    else:
        with db.tx() as c:
            c.execute(audit_log.insert().values(**values))
