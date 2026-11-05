"""SQLite persistence (settings, projects, chat, tasks, activity, memory, runs).

A single connection per :class:`Database` guarded by a lock keeps things simple
and safe across the server's worker threads. Schema changes are applied as
ordered migrations recorded in ``schema_version``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

MIGRATIONS: list[str] = [
    # 1: core tables
    """
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        authorized INTEGER NOT NULL DEFAULT 1,
        created_at REAL NOT NULL,
        last_opened REAL NOT NULL
    );
    CREATE TABLE activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        project_id INTEGER,
        kind TEXT NOT NULL,
        message TEXT NOT NULL,
        data TEXT
    );
    CREATE TABLE conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        title TEXT NOT NULL,
        created_at REAL NOT NULL
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        meta TEXT,
        ts REAL NOT NULL
    );
    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        project_id INTEGER,
        goal TEXT NOT NULL,
        status TEXT NOT NULL,
        plan TEXT,
        steps TEXT,
        result TEXT,
        error TEXT,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE TABLE memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER,
        kind TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        verified INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL
    );
    CREATE VIRTUAL TABLE memories_fts USING fts5(title, content, content='memories', content_rowid='id');
    CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
    END;
    CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
    END;
    CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
        INSERT INTO memories_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
    END;
    CREATE TABLE code_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        path TEXT NOT NULL,
        start_line INTEGER NOT NULL,
        end_line INTEGER NOT NULL,
        mtime REAL NOT NULL,
        content TEXT NOT NULL
    );
    CREATE INDEX code_chunks_project_path ON code_chunks(project_id, path);
    CREATE VIRTUAL TABLE code_chunks_fts USING fts5(path, content, content='code_chunks', content_rowid='id');
    CREATE TRIGGER code_chunks_ai AFTER INSERT ON code_chunks BEGIN
        INSERT INTO code_chunks_fts(rowid, path, content) VALUES (new.id, new.path, new.content);
    END;
    CREATE TRIGGER code_chunks_ad AFTER DELETE ON code_chunks BEGIN
        INSERT INTO code_chunks_fts(code_chunks_fts, rowid, path, content) VALUES ('delete', old.id, old.path, old.content);
    END;
    CREATE TABLE training_runs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        config TEXT NOT NULL,
        out_dir TEXT NOT NULL,
        step INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        error TEXT
    );
    CREATE TABLE training_metrics (
        run_id TEXT NOT NULL,
        step INTEGER NOT NULL,
        split TEXT NOT NULL,
        loss REAL NOT NULL,
        lr REAL,
        tokens_per_sec REAL,
        ts REAL NOT NULL
    );
    CREATE INDEX training_metrics_run ON training_metrics(run_id, step);
    """,
]


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
            row = self._conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
            current = row["v"] or 0
            for i, sql in enumerate(MIGRATIONS, start=1):
                if i <= current:
                    continue
                self._conn.execute("BEGIN")
                try:
                    for stmt in _split_sql(sql):
                        self._conn.execute(stmt)
                    self._conn.execute("INSERT INTO schema_version(version) VALUES (?)", (i,))
                    self._conn.execute("COMMIT")
                except Exception:
                    self._conn.execute("ROLLBACK")
                    raise

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def transaction(self):
        return _Tx(self)

    # ---- settings -------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )

    # ---- activity -------------------------------------------------------
    def log_activity(self, kind: str, message: str, project_id: int | None = None, data: Any = None) -> int:
        cur = self.execute(
            "INSERT INTO activity(ts, project_id, kind, message, data) VALUES (?,?,?,?,?)",
            (time.time(), project_id, kind, message, json.dumps(data) if data is not None else None),
        )
        return int(cur.lastrowid)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self):
        self.db._lock.acquire()
        self.db._conn.execute("BEGIN")
        return self.db

    def __exit__(self, exc_type, exc, tb):
        try:
            self.db._conn.execute("ROLLBACK" if exc_type else "COMMIT")
        finally:
            self.db._lock.release()
        return False


def _split_sql(sql: str) -> list[str]:
    """Split a migration into statements, keeping trigger bodies intact."""
    statements, buf, depth = [], [], 0
    for line in sql.strip().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        buf.append(line)
        upper = stripped.upper()
        if upper.endswith("BEGIN"):
            depth += 1
        if upper.startswith("END;"):
            depth -= 1
        if depth == 0 and stripped.endswith(";"):
            statements.append("\n".join(buf))
            buf = []
    if buf:
        statements.append("\n".join(buf))
    return statements
