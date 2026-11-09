"""Code retrieval for large projects: chunked, incrementally updated FTS5 index."""

from __future__ import annotations

from pathlib import Path

from moth.agent.memory import fts_query
from moth.db import Database
from moth.security.permissions import is_secret_path
from moth.workspace.scanner import LANGUAGES, iter_files

CHUNK_LINES = 40
OVERLAP = 8
MAX_FILE_BYTES = 400_000
INDEXED_EXT = set(LANGUAGES) | {".txt", ".rst", ".cfg", ".ini"}


def chunk_text(text: str, size: int = CHUNK_LINES, overlap: int = OVERLAP) -> list[tuple[int, int, str]]:
    lines = text.splitlines()
    if not lines:
        return [(1, 1, "")]  # still recorded, so unchanged empty files are not re-indexed
    out, start = [], 0
    while start < len(lines):
        end = min(len(lines), start + size)
        out.append((start + 1, end, "\n".join(lines[start:end])))
        if end == len(lines):
            break
        start = end - overlap
    return out


class CodeIndex:
    def __init__(self, db: Database):
        self.db = db

    def update(self, project_id: int, root: Path, paths=None) -> dict:
        """Index new/changed files, drop deleted ones. Returns counts."""
        root = Path(root).resolve()
        known = {r["path"]: r["mtime"] for r in self.db.query(
            "SELECT path, MAX(mtime) AS mtime FROM code_chunks WHERE project_id=? GROUP BY path", (project_id,))}
        seen, added, updated = set(), 0, 0
        for rel, path in (iter_files(root) if paths is None else paths):
            if path.suffix.lower() not in INDEXED_EXT or is_secret_path(rel):
                continue
            try:
                if path.is_symlink() or root not in path.resolve().parents:
                    continue
                st = path.stat()
                if st.st_size > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            seen.add(rel)
            if rel in known and abs(known[rel] - st.st_mtime) < 1e-6:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            with self.db.transaction():
                self.db.execute("DELETE FROM code_chunks WHERE project_id=? AND path=?", (project_id, rel))
                for s, e, content in chunk_text(text):
                    self.db.execute("INSERT INTO code_chunks(project_id, path, start_line, end_line, mtime, content) "
                                    "VALUES (?,?,?,?,?,?)", (project_id, rel, s, e, st.st_mtime, content))
            updated += rel in known
            added += rel not in known
        removed = [p for p in known if p not in seen]
        for p in removed:
            self.db.execute("DELETE FROM code_chunks WHERE project_id=? AND path=?", (project_id, p))
        return {"added": added, "updated": updated, "removed": len(removed), "files": len(seen)}

    def search(self, project_id: int, text: str, limit: int = 6) -> list[dict]:
        q = fts_query(text)
        if not q:
            return []
        return self.db.query(
            "SELECT c.path, c.start_line, c.end_line, c.content, bm25(code_chunks_fts) AS score "
            "FROM code_chunks_fts f JOIN code_chunks c ON c.id=f.rowid "
            "WHERE code_chunks_fts MATCH ? AND c.project_id=? ORDER BY score LIMIT ?", (q, project_id, limit))
