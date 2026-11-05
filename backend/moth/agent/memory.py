"""Persistent per-project memory: architecture, preferences, verified solutions, errors.

Stored in SQLite with an FTS5 index so relevant memories can be retrieved for
each task. Memories never leave the computer.
"""

from __future__ import annotations

import re
import time
from typing import Any

from moth.db import Database

KINDS = ("architecture", "preference", "solution", "error", "note")


def fts_query(text: str, max_terms: int = 12) -> str:
    """Turn free text into a safe FTS5 OR-query of word terms."""
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text)
    seen: list[str] = []
    for w in words:
        lw = w.lower()
        if lw not in seen and lw not in _STOP:
            seen.append(lw)
        if len(seen) >= max_terms:
            break
    return " OR ".join(f'"{w}"' for w in seen)


_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "please", "make", "should", "would", "could",
         "can", "you", "are", "was", "not", "but", "all"}


class MemoryStore:
    def __init__(self, db: Database):
        self.db = db

    def add(self, project_id: int | None, kind: str, title: str, content: str, verified: bool = False) -> int:
        if kind not in KINDS:
            raise ValueError(f"memory kind must be one of {KINDS}")
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO memories(project_id, kind, title, content, verified, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (project_id, kind, title.strip()[:200], content.strip(), int(verified), now, now))
        return int(cur.lastrowid)

    def upsert(self, project_id: int | None, kind: str, title: str, content: str, verified: bool = False) -> int:
        row = self.db.one("SELECT id FROM memories WHERE project_id IS ? AND kind=? AND title=?", (project_id, kind, title))
        if row:
            self.update(row["id"], content=content, verified=verified)
            return row["id"]
        return self.add(project_id, kind, title, content, verified)

    def update(self, memory_id: int, **fields: Any) -> None:
        allowed = {k: v for k, v in fields.items() if k in ("kind", "title", "content", "verified")}
        if not allowed:
            return
        if "verified" in allowed:
            allowed["verified"] = int(bool(allowed["verified"]))
        sets = ", ".join(f"{k}=?" for k in allowed)
        self.db.execute(f"UPDATE memories SET {sets}, updated_at=? WHERE id=?", (*allowed.values(), time.time(), memory_id))

    def delete(self, memory_id: int) -> None:
        self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    def list(self, project_id: int | None, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM memories WHERE (project_id IS ? OR project_id IS NULL)"
        params: list[Any] = [project_id]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        return self.db.query(sql + " ORDER BY updated_at DESC", params)

    def search(self, project_id: int | None, text: str, limit: int = 6) -> list[dict]:
        q = fts_query(text)
        pinned = self.db.query(
            "SELECT * FROM memories WHERE (project_id IS ? OR project_id IS NULL) AND kind IN ('preference','architecture') "
            "ORDER BY updated_at DESC LIMIT 4", (project_id,))
        if not q:
            return pinned
        hits = self.db.query(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.id=f.rowid WHERE memories_fts MATCH ? "
            "AND (m.project_id IS ? OR m.project_id IS NULL) ORDER BY bm25(memories_fts) LIMIT ?",
            (q, project_id, limit))
        seen = {m["id"] for m in pinned}
        return pinned + [h for h in hits if h["id"] not in seen]
