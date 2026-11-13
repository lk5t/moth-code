"""Knowledge 2.0 (0.8.0): organisation and trust for the Knowledge Engine, kept separate from model weights.

Every document version gets metadata in ``knowledge_meta``:

* ``category`` — ``code``, ``documentation``, ``project``, ``conversation``, ``research`` or ``general``
  (detected from the content and source when not given);
* ``project`` — project-specific memories are preferred when MOTH works on that project;
* ``confidence`` (0–1) and ``verified`` — how much MOTH may rely on it; a person can verify a document;
  research notes start low and unverified;
* ``review_after`` — after this date the document is flagged as possibly outdated (a new version, which
  supersedes the old one, resets it);
* ``near_duplicate_of`` — a very similar active document (word-shingle Jaccard ≥ ``NEAR_DUP``); exact
  duplicates were already refused by the engine.

Updating knowledge never retrains the model: retrieval uses the current documents at answer time.
"""

from __future__ import annotations

import re
import time
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import knowledge_chunks, knowledge_docs, knowledge_meta

CATEGORIES = ("general", "code", "documentation", "project", "conversation", "research")
NEAR_DUP = 0.85
DAY = 86400.0
REVIEW_DAYS = {"code": 365, "documentation": 365, "project": 180, "conversation": 180, "research": 90, "general": 365}
CODE_HINT = re.compile(r"```|^\s*(def |class |import |from \S+ import |function |const |#include)", re.M)


def categorize(title: str, text: str, source: str) -> str:
    s = (source or "").lower()
    if s.startswith("conversation:"):
        return "conversation"
    if s.startswith("research:"):
        return "research"
    if s.startswith("project:"):
        return "project"
    if CODE_HINT.search(text[:20000]):
        return "code"
    if s.startswith(("http://", "https://")) or "docs" in s or "documentation" in (title or "").lower():
        return "documentation"
    return "general"


def default_confidence(category: str, shared: bool, source: str) -> float:
    if category == "research":
        return 0.3  # gathered, not established
    if shared:
        return 0.8 if source else 0.7  # Owner-approved knowledge
    return 0.6


def _shingles(text: str, n: int = 5) -> set[int]:
    w = re.findall(r"\w+", text.lower())[:4000]
    return {hash(" ".join(w[i:i + n])) for i in range(max(1, len(w) - n + 1))}


def _doc_text(c, doc_id: int) -> str:
    return "\n".join(r[0] for r in c.execute(select(knowledge_chunks.c.text).where(knowledge_chunks.c.doc_id == doc_id)
                                              .order_by(knowledge_chunks.c.ord)).all())


def on_added(ctx: Ctx, doc: dict, text: str, category: str | None = None, project: str | None = None,
             confidence: float | None = None, previous_id: int | None = None) -> dict[str, Any]:
    """Record metadata for a newly added document version (and find a near-duplicate)."""
    shared = doc["shared"]
    with ctx.db.tx() as c:
        prev = c.execute(select(knowledge_meta).where(knowledge_meta.c.doc_id == previous_id)).mappings().first() \
            if previous_id else None
        cat = category if category in CATEGORIES else (prev["category"] if prev else categorize(doc["title"], text, doc["source"]))
        proj = (project if project is not None else (prev["project"] if prev else None)) or None
        conf = confidence if confidence is not None else default_confidence(cat, shared, doc["source"])
        mine = _shingles(text)
        dup = None
        scope = knowledge_docs.c.owner_id.is_(None) if shared else knowledge_docs.c.owner_id == ctx.db.one(
            select(knowledge_docs.c.owner_id).where(knowledge_docs.c.id == doc["id"]))["owner_id"]
        for other in c.execute(select(knowledge_docs.c.id).where(scope, knowledge_docs.c.status == "active",
                                                                 knowledge_docs.c.id != doc["id"])
                               .order_by(knowledge_docs.c.id.desc()).limit(200)).all():
            theirs = _shingles(_doc_text(c, other[0]))
            if mine and theirs and len(mine & theirs) / len(mine | theirs) >= NEAR_DUP:
                dup = other[0]
                break
        values = dict(category=cat, project=(proj or None) and proj[:200], confidence=max(0.0, min(1.0, float(conf))),
                      verified=False, review_after=time.time() + REVIEW_DAYS[cat] * DAY, near_duplicate_of=dup)
        c.execute(knowledge_meta.insert().values(doc_id=doc["id"], **values))
    return values


def meta_for(ctx: Ctx, doc_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not doc_ids:
        return {}
    t = time.time()
    out = {}
    for r in ctx.db.all(select(knowledge_meta).where(knowledge_meta.c.doc_id.in_(doc_ids))):
        out[r["doc_id"]] = {"category": r["category"], "project": r["project"], "confidence": r["confidence"],
                            "verified": bool(r["verified"]), "review_after": r["review_after"],
                            "stale": bool(r["review_after"] and r["review_after"] < t),
                            "near_duplicate_of": r["near_duplicate_of"]}
    return out


def update(ctx: Ctx, user_id: int | None, doc_id: int, changes: dict[str, Any], is_owner: bool = False) -> dict:
    from moth_server.intelligence.knowledge import KnowledgeError

    d = ctx.db.one(select(knowledge_docs).where(knowledge_docs.c.id == doc_id, knowledge_docs.c.status == "active"))
    if not d or (d["owner_id"] is not None and d["owner_id"] != user_id):
        raise KnowledgeError("Document not found.")
    if d["owner_id"] is None and not is_owner:
        raise KnowledgeError("Only the Owner can change shared knowledge.")
    values: dict[str, Any] = {}
    if "category" in changes:
        if changes["category"] not in CATEGORIES:
            raise KnowledgeError(f"category must be one of {', '.join(CATEGORIES)}")
        values["category"] = changes["category"]
    if "project" in changes:
        values["project"] = (str(changes["project"] or "").strip()[:200]) or None
    if "confidence" in changes:
        values["confidence"] = max(0.0, min(1.0, float(changes["confidence"])))
    if "verified" in changes:
        values["verified"] = bool(changes["verified"])
        if values["verified"]:  # a person checked it now: not outdated, and at least fairly reliable
            cat = values.get("category") or (meta_for(ctx, [doc_id]).get(doc_id) or {}).get("category", "general")
            values["review_after"] = time.time() + REVIEW_DAYS.get(cat, 365) * DAY
    if "review_days" in changes:
        values["review_after"] = time.time() + max(1, int(changes["review_days"])) * DAY
    with ctx.db.tx() as c:
        if c.execute(select(knowledge_meta.c.doc_id).where(knowledge_meta.c.doc_id == doc_id)).first() is None:
            c.execute(knowledge_meta.insert().values(doc_id=doc_id, category="general", confidence=0.5, verified=False))
        if values:
            c.execute(knowledge_meta.update().where(knowledge_meta.c.doc_id == doc_id).values(**values))
    return meta_for(ctx, [doc_id])[doc_id]


def weight(meta: dict | None, project: str | None) -> float:
    """Ranking factor: reliable, current and same-project knowledge first."""
    if not meta:
        return 1.0
    w = 0.6 + 0.4 * float(meta.get("confidence") or 0.5)
    if meta.get("verified"):
        w *= 1.15
    if meta.get("stale"):
        w *= 0.7
    if project and meta.get("project") == project:
        w *= 1.4
    return w
