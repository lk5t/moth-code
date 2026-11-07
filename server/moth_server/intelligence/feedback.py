"""Feedback learning with consent.

* Users rate answers (+1 / −1), pick what went wrong (wrong, unhelpful, code error, unsafe, other) and may
  suggest a correction.
* The prompt and the answer are stored **only** when the user has opted in to training use
  (``settings.training_consent``). Without consent only the rating, category and model are kept —
  enough to find weaknesses, never the conversation itself.
* Recurring weaknesses are computed per capability and per model version.
* Only Owner-approved feedback with consent becomes training data (``export_dataset``): corrected answers
  and positively rated answers as conversations. Private conversations are never trained on otherwise.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select

from moth_server.context import Ctx
from moth_server.db import conversation_messages, conversations, feedback, now, users

CATEGORIES = ("wrong", "unhelpful", "code_error", "unsafe", "reasoning_error", "other", "")

CODE_HINT = re.compile(r"```|\bdef |\bclass |\bfunction\b|\bimport |\bpython\b|\bjavascript\b|\bcode\b|\bbug\b|"
                       r"\berror\b|\bcompile|\bregex\b|\bsql\b|\bapi\b", re.I)
MATH_HINT = re.compile(r"\d+\s*[-+*/^=]\s*\d+|\bcalculate\b|\bsolve\b|\bequation\b|\bpercent\b|\bhow many\b|"
                       r"\bsum of\b|\bmath", re.I)
REASON_HINT = re.compile(r"\bwhy\b|\bexplain\b|\bcompare\b|\bwhich is (better|more)\b|\breason\b|\blogic", re.I)
WRITE_HINT = re.compile(r"\bwrite (a|an|me)\b|\bstory\b|\bpoem\b|\bessay\b|\bsummar|\brewrite\b|\bemail\b", re.I)
FACT_HINT = re.compile(r"\bwho (is|was)\b|\bwhat (is|are|was)\b|\bwhen did\b|\bwhere is\b|\bcapital of\b", re.I)


def classify(text: str) -> str:
    """The capability a request mostly needs (used for routing, feedback and weakness tracking)."""
    if CODE_HINT.search(text):
        return "code"
    if MATH_HINT.search(text):
        return "math"
    if WRITE_HINT.search(text):
        return "writing"
    if REASON_HINT.search(text):
        return "reasoning"
    if FACT_HINT.search(text):
        return "knowledge"
    return "conversation"


def consent(user: dict) -> dict[str, bool]:
    s = json.loads(user.get("settings") or "{}")
    return {"training_consent": bool(s.get("training_consent", False)),
            "external_ai": bool(s.get("external_ai", False)),
            "keep_history": bool(s.get("keep_history", True)),
            "use_knowledge": bool(s.get("use_knowledge", True))}


def set_consent(ctx: Ctx, user_id: int, values: dict[str, bool]) -> dict[str, bool]:
    with ctx.db.tx() as c:
        row = c.execute(select(users.c.settings).where(users.c.id == user_id)).first()
        s = json.loads(row[0] or "{}")
        for k in ("training_consent", "external_ai", "keep_history", "use_knowledge"):
            if k in values and values[k] is not None:
                s[k] = bool(values[k])
        c.execute(users.update().where(users.c.id == user_id).values(settings=json.dumps(s)))
        user = c.execute(select(users).where(users.c.id == user_id)).mappings().first()
    return consent(dict(user))


class FeedbackError(ValueError):
    pass


def submit(ctx: Ctx, user: dict, message_id: int | None, rating: int, category: str = "", comment: str = "",
           correction: str = "", prompt: str | None = None, response: str | None = None,
           model: str | None = None, model_version: int | None = None) -> dict[str, Any]:
    if rating not in (1, -1):
        raise FeedbackError("rating must be 1 or -1")
    if category not in CATEGORIES:
        raise FeedbackError(f"unknown category {category!r}")
    if message_id is not None:  # rating a stored cloud answer: it must be the user's own
        m = ctx.db.one(select(conversation_messages, conversations.c.user_id).join(
            conversations, conversations.c.id == conversation_messages.c.conversation_id)
            .where(conversation_messages.c.id == message_id))
        if not m or m["user_id"] != user["id"] or m["role"] != "assistant":
            raise FeedbackError("message not found")
        response = m["content"]
        model, model_version = m["model"], m["model_version"]
        prev = ctx.db.one(select(conversation_messages).where(
            conversation_messages.c.conversation_id == m["conversation_id"], conversation_messages.c.id < message_id,
            conversation_messages.c.role == "user").order_by(conversation_messages.c.id.desc()))
        prompt = prev["content"] if prev else prompt
    ok = consent(user)["training_consent"]
    cap = classify(prompt or "") if prompt else ("code" if category == "code_error" else "conversation")
    with ctx.db.tx() as c:
        if message_id is not None:
            c.execute(feedback.delete().where(feedback.c.user_id == user["id"], feedback.c.message_id == message_id))
        fid = c.execute(feedback.insert().values(
            user_id=user["id"], message_id=message_id, model=(model or "")[:64] or None, model_version=model_version,
            rating=rating, category=category, capability=cap, comment=comment[:2000],
            correction=correction[:8000] if ok else "", prompt=(prompt or "")[:8000] if ok else None,
            response=(response or "")[:8000] if ok else None, consent=ok, status="new", created_at=now())
        ).inserted_primary_key[0]
    return {"id": fid, "stored_conversation": ok, "capability": cap}


def summary(ctx: Ctx, since: float = 0.0) -> dict[str, Any]:
    rows = ctx.db.all(select(feedback.c.capability, feedback.c.rating, feedback.c.category,
                             feedback.c.model_version).where(feedback.c.created_at >= since))
    caps: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = caps.setdefault(r["capability"], {"ratings": 0, "negative": 0, "categories": {}})
        c["ratings"] += 1
        if r["rating"] < 0:
            c["negative"] += 1
            c["categories"][r["category"] or "other"] = c["categories"].get(r["category"] or "other", 0) + 1
    for c in caps.values():
        c["negative_rate"] = round(c["negative"] / c["ratings"], 3) if c["ratings"] else 0.0
    weak = sorted(((k, v) for k, v in caps.items() if v["ratings"] >= 5),
                  key=lambda kv: -kv[1]["negative_rate"])
    return {"capabilities": caps, "recurring_weaknesses": [
        {"capability": k, "negative_rate": v["negative_rate"], "ratings": v["ratings"],
         "top_problem": max(v["categories"], key=v["categories"].get) if v["categories"] else None}
        for k, v in weak if v["negative_rate"] >= 0.3], "total": len(rows)}


def listing(ctx: Ctx, status: str | None = None, limit: int = 100) -> list[dict]:
    q = select(feedback).order_by(feedback.c.id.desc()).limit(limit)
    if status:
        q = q.where(feedback.c.status == status)
    return ctx.db.all(q)


def review(ctx: Ctx, fid: int, approve: bool) -> dict:
    with ctx.db.tx() as c:
        f = c.execute(select(feedback).where(feedback.c.id == fid)).mappings().first()
        if not f:
            raise FeedbackError("feedback not found")
        if approve and not f["consent"]:
            raise FeedbackError("this user did not consent to training use; it cannot become training data")
        c.execute(feedback.update().where(feedback.c.id == fid).values(status="approved" if approve else "rejected"))
    return {"ok": True}


def export_dataset(ctx: Ctx) -> list[dict[str, Any]]:
    """Approved, consented feedback as chat training records (corrections and well-rated answers)."""
    out = []
    for f in ctx.db.all(select(feedback).where(feedback.c.status == "approved", feedback.c.consent.is_(True))):
        if not f["prompt"]:
            continue
        answer = f["correction"] or (f["response"] if f["rating"] > 0 else "")
        if answer.strip():
            out.append({"uid": f"feedback:{f['id']}", "source": "feedback", "domain": f["capability"],
                        "messages": [{"role": "user", "content": f["prompt"]},
                                     {"role": "assistant", "content": answer}]})
    return out


def counts(ctx: Ctx) -> dict[str, int]:
    rows = ctx.db.all(select(feedback.c.status, func.count().label("n")).group_by(feedback.c.status))
    return {r["status"]: r["n"] for r in rows}
