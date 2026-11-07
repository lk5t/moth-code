"""The Knowledge Engine: persistent, searchable, versioned documents with cited retrieval.

* Documents belong to a user (private, visible only to them) or are shared (``owner_id`` NULL), which
  only the Owner can add — the "approved knowledge sources".
* A document has a stable ``key`` (its source or title). Adding the same key with new text creates a
  new version and supersedes the old one (kept for history); adding identical text is a no-op, so
  knowledge is never duplicated. Identical text under another key is also detected.
* Text is split into ~900-character chunks indexed by term frequency; search ranks chunks with BM25.
* ``context_for`` builds the retrieval-augmented prompt: the best chunks with numbered citations.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from typing import Any

from sqlalchemy import and_, delete, func, or_, select

from moth_server.context import Ctx
from moth_server.db import knowledge_chunks, knowledge_docs, knowledge_terms, now

MAX_DOC_CHARS = 2_000_000
MAX_DOCS_PER_USER = 500
CHUNK_CHARS = 900
STOP = frozenset("a an the and or of to in on for is are was were be been it its this that with as at by from "
                 "what which who how why when where do does did can could should would will i you he she we they "
                 "me my your our their there here not no yes".split())
TERM = re.compile(r"[a-z0-9_]{2,40}")


class KnowledgeError(ValueError):
    pass


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ies", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def terms(text: str) -> list[str]:
    return [stem(t) for t in TERM.findall(text.lower()) if t not in STOP]


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur = [], ""
    for p in paras:
        while len(p) > size:  # very long paragraphs are split at sentence boundaries
            cut = p.rfind(". ", 0, size)
            cut = cut + 1 if cut > size // 3 else size
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if len(cur) + len(p) + 2 > size and cur:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
    if cur:
        out.append(cur)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode()).hexdigest()


def public(d: dict) -> dict:
    return {k: d[k] for k in ("id", "key", "title", "source", "license", "version", "status", "chars", "created_at",
                              "updated_at")} | {"shared": d["owner_id"] is None}


def add(ctx: Ctx, owner_id: int | None, title: str, text: str, source: str = "", license_: str = "",
        key: str | None = None) -> dict[str, Any]:
    text = text.replace("\r\n", "\n").strip()
    title = (title or "").strip()[:200] or "Untitled"
    if not text:
        raise KnowledgeError("The document is empty.")
    if len(text) > MAX_DOC_CHARS:
        raise KnowledgeError("The document is too large (limit 2 million characters).")
    key = (key or source or title).strip()[:200]
    sha = _sha(text)
    scope = knowledge_docs.c.owner_id.is_(None) if owner_id is None else knowledge_docs.c.owner_id == owner_id
    with ctx.db.tx() as c:
        same = c.execute(select(knowledge_docs).where(scope, knowledge_docs.c.sha256 == sha,
                                                      knowledge_docs.c.status == "active")).mappings().first()
        if same:
            return {"document": public(dict(same)), "duplicate": True}
        if owner_id is not None:
            n = c.execute(select(func.count()).select_from(knowledge_docs).where(
                scope, knowledge_docs.c.status == "active")).scalar()
            if n >= MAX_DOCS_PER_USER:
                raise KnowledgeError(f"You have reached the limit of {MAX_DOCS_PER_USER} documents.")
        prev = c.execute(select(knowledge_docs).where(scope, knowledge_docs.c.key == key,
                                                      knowledge_docs.c.status == "active")).mappings().first()
        version = (prev["version"] + 1) if prev else 1
        if prev:
            c.execute(knowledge_docs.update().where(knowledge_docs.c.id == prev["id"]).values(
                status="superseded", updated_at=now()))
            _unindex(c, prev["id"])
        did = c.execute(knowledge_docs.insert().values(
            owner_id=owner_id, key=key, title=title, source=source[:500], license=license_[:64], version=version,
            sha256=sha, status="active", chars=len(text), created_at=now(), updated_at=now())).inserted_primary_key[0]
        for i, part in enumerate(chunk(text)):
            ts = terms(f"{title}\n{part}")
            cid = c.execute(knowledge_chunks.insert().values(doc_id=did, ord=i, text=part, length=len(ts))
                            ).inserted_primary_key[0]
            tf = Counter(t[:48] for t in ts)
            if tf:
                c.execute(knowledge_terms.insert(), [{"term": t, "chunk_id": cid, "tf": n} for t, n in tf.items()])
        doc = c.execute(select(knowledge_docs).where(knowledge_docs.c.id == did)).mappings().first()
    return {"document": public(dict(doc)), "duplicate": False, "replaced_version": prev["version"] if prev else None}


def _unindex(c, doc_id: int) -> None:
    ids = [r[0] for r in c.execute(select(knowledge_chunks.c.id).where(knowledge_chunks.c.doc_id == doc_id))]
    if ids:
        c.execute(delete(knowledge_terms).where(knowledge_terms.c.chunk_id.in_(ids)))


def _visible(user_id: int | None):
    shared = knowledge_docs.c.owner_id.is_(None)
    return shared if user_id is None else or_(shared, knowledge_docs.c.owner_id == user_id)


def list_docs(ctx: Ctx, user_id: int | None, include_shared: bool = True) -> list[dict]:
    cond = _visible(user_id) if include_shared else (knowledge_docs.c.owner_id == user_id)
    rows = ctx.db.all(select(knowledge_docs).where(cond, knowledge_docs.c.status == "active")
                      .order_by(knowledge_docs.c.updated_at.desc()))
    return [public(r) for r in rows]


def versions(ctx: Ctx, user_id: int | None, doc_id: int) -> list[dict]:
    d = ctx.db.one(select(knowledge_docs).where(knowledge_docs.c.id == doc_id, _visible(user_id)))
    if not d:
        raise KnowledgeError("Document not found.")
    rows = ctx.db.all(select(knowledge_docs).where(
        knowledge_docs.c.key == d["key"],
        knowledge_docs.c.owner_id.is_(None) if d["owner_id"] is None else knowledge_docs.c.owner_id == d["owner_id"])
        .order_by(knowledge_docs.c.version.desc()))
    return [public(r) for r in rows]


def remove(ctx: Ctx, user_id: int | None, doc_id: int, is_owner: bool = False) -> None:
    with ctx.db.tx() as c:
        d = c.execute(select(knowledge_docs).where(knowledge_docs.c.id == doc_id)).mappings().first()
        if not d or d["status"] != "active":
            raise KnowledgeError("Document not found.")
        if d["owner_id"] is None and not is_owner:
            raise KnowledgeError("Only the Owner can remove shared knowledge.")
        if d["owner_id"] is not None and d["owner_id"] != user_id:
            raise KnowledgeError("Document not found.")  # never reveal other users' documents
        _unindex(c, doc_id)
        c.execute(delete(knowledge_chunks).where(knowledge_chunks.c.doc_id == doc_id))
        c.execute(knowledge_docs.update().where(knowledge_docs.c.id == doc_id).values(status="deleted",
                                                                                        updated_at=now()))


def search(ctx: Ctx, user_id: int | None, query: str, k: int = 5) -> list[dict[str, Any]]:
    q = list(dict.fromkeys(t[:48] for t in terms(query)))[:24]
    if not q:
        return []
    vis = and_(_visible(user_id), knowledge_docs.c.status == "active")
    with ctx.db.tx() as c:
        n_chunks = c.execute(select(func.count()).select_from(
            knowledge_chunks.join(knowledge_docs, knowledge_docs.c.id == knowledge_chunks.c.doc_id)).where(vis)
        ).scalar() or 0
        if not n_chunks:
            return []
        avg_len = c.execute(select(func.avg(knowledge_chunks.c.length)).select_from(
            knowledge_chunks.join(knowledge_docs, knowledge_docs.c.id == knowledge_chunks.c.doc_id)).where(vis)
        ).scalar() or 1.0
        rows = c.execute(
            select(knowledge_terms.c.term, knowledge_terms.c.tf, knowledge_chunks.c.id, knowledge_chunks.c.length)
            .select_from(knowledge_terms.join(knowledge_chunks, knowledge_chunks.c.id == knowledge_terms.c.chunk_id)
                         .join(knowledge_docs, knowledge_docs.c.id == knowledge_chunks.c.doc_id))
            .where(vis, knowledge_terms.c.term.in_(q))).all()
        df = Counter(r[0] for r in rows)
        scores: dict[int, float] = {}
        k1, b = 1.2, 0.75
        for term, tf, cid, length in rows:
            idf = math.log(1 + (n_chunks - df[term] + 0.5) / (df[term] + 0.5))
            scores[cid] = scores.get(cid, 0.0) + idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * length / avg_len))
        best = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        if not best:
            return []
        info = {r["id"]: r for r in c.execute(
            select(knowledge_chunks.c.id, knowledge_chunks.c.text, knowledge_chunks.c.ord, knowledge_docs.c.id.label("doc_id"),
                   knowledge_docs.c.title, knowledge_docs.c.source, knowledge_docs.c.version, knowledge_docs.c.owner_id)
            .select_from(knowledge_chunks.join(knowledge_docs, knowledge_docs.c.id == knowledge_chunks.c.doc_id))
            .where(knowledge_chunks.c.id.in_([cid for cid, _ in best]))).mappings()}
    return [{"chunk_id": cid, "score": round(s, 4), "text": info[cid]["text"], "doc_id": info[cid]["doc_id"],
             "title": info[cid]["title"], "source": info[cid]["source"], "version": info[cid]["version"],
             "shared": info[cid]["owner_id"] is None} for cid, s in best if cid in info]


def context_for(ctx: Ctx, user_id: int | None, question: str, k: int = 3, max_chars: int = 2400,
                min_score: float = 1.0) -> tuple[str | None, list[dict[str, Any]]]:
    """A system message with the best matching sources (or ``None``) and the citations it uses."""
    hits = [h for h in search(ctx, user_id, question, k=k) if h["score"] >= min_score]
    if not hits:
        return None, []
    parts, used, total = [], [], 0
    for i, h in enumerate(hits, 1):
        text = h["text"][: max(200, max_chars - total)]
        total += len(text)
        parts.append(f"[{i}] {h['title']}: {text}")
        used.append({"n": i, "title": h["title"], "source": h["source"], "doc_id": h["doc_id"],
                     "version": h["version"], "shared": h["shared"]})
        if total >= max_chars:
            break
    msg = ("Use the following sources when they are relevant, and cite them like [1]. If they do not contain "
           "the answer, say so.\n\n" + "\n\n".join(parts))
    return msg, used
