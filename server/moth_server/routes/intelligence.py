"""0.5.1 INTELLIGENCE API: routed chat with history and knowledge, feedback, consent, knowledge engine,
dataset library, weaknesses and curriculum."""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from moth_server import billing
from moth_server.context import Ctx, get_ctx
from moth_server.db import conversation_messages, conversations, now
from moth_server.deps import Auth, current_auth, owner_reauthed, require_owner
from moth_server.intelligence import curriculum, feedback as FB, knowledge as K, library, router as R, weakness
from moth_server.routes.admin import flags

router = APIRouter(tags=["intelligence"])
MAX_NEW_TOKENS = 1024
HISTORY_MESSAGES = 16


def _policy(ctx: Ctx):
    from moth.policy.engine import PolicyEngine, with_safety_baseline

    p = ctx.db.get_config("content_policy", {}) or {}
    return PolicyEngine(with_safety_baseline(p) if flags(ctx).get("safety_baseline") else p)


# ---- status, consent ------------------------------------------------------------------------------------
@router.get("/v1/intelligence/status")
def status(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    stats = ctx.extras.get("router_stats", {})
    f = flags(ctx)
    return {"models": [p.public(stats.get(p.id, {})) for p in R.providers(ctx, auth.user)],
            "knowledge_enabled": bool(f.get("knowledge_enabled")), "feedback_enabled": bool(f.get("feedback_collection")),
            "external_ai_enabled": bool(f.get("external_ai_enabled")), "consent": FB.consent(auth.user)}


class ConsentIn(BaseModel):
    training_consent: bool | None = None
    external_ai: bool | None = None
    keep_history: bool | None = None
    use_knowledge: bool | None = None


@router.put("/v1/me/consent")
def put_consent(body: ConsentIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    out = FB.set_consent(ctx, auth.uid, body.model_dump())
    if body.keep_history is False:  # turning history off also forgets what was stored
        _delete_conversations(ctx, auth.uid)
    return {"consent": out}


# ---- conversations (memory controls) --------------------------------------------------------------------
def _conv(ctx: Ctx, uid: int, cid: int) -> dict:
    c = ctx.db.one(select(conversations).where(conversations.c.id == cid, conversations.c.user_id == uid))
    if not c:
        raise HTTPException(404, "Conversation not found.")
    return c


@router.get("/v1/conversations")
def list_conversations(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    rows = ctx.db.all(select(conversations).where(conversations.c.user_id == auth.uid)
                      .order_by(conversations.c.updated_at.desc()).limit(200))
    return {"conversations": rows}


@router.get("/v1/conversations/{cid}")
def get_conversation(cid: int, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    c = _conv(ctx, auth.uid, cid)
    msgs = ctx.db.all(select(conversation_messages).where(conversation_messages.c.conversation_id == cid)
                      .order_by(conversation_messages.c.id))
    for m in msgs:
        m["sources"] = json.loads(m["sources"] or "[]")
        m["stats"] = json.loads(m["stats"] or "{}")
    return {"conversation": c, "messages": msgs}


def _delete_conversations(ctx: Ctx, uid: int, cid: int | None = None) -> int:
    with ctx.db.tx() as c:
        q = select(conversations.c.id).where(conversations.c.user_id == uid)
        if cid is not None:
            q = q.where(conversations.c.id == cid)
        ids = [r[0] for r in c.execute(q)]
        if ids:
            c.execute(delete(conversation_messages).where(conversation_messages.c.conversation_id.in_(ids)))
            c.execute(delete(conversations).where(conversations.c.id.in_(ids)))
    return len(ids)


@router.delete("/v1/conversations/{cid}")
def delete_conversation(cid: int, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    _conv(ctx, auth.uid, cid)
    _delete_conversations(ctx, auth.uid, cid)
    return {"ok": True}


@router.delete("/v1/conversations")
def delete_all_conversations(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    return {"deleted": _delete_conversations(ctx, auth.uid)}


# ---- chat ---------------------------------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=32_000)
    conversation_id: int | None = None
    use_knowledge: bool | None = None
    model: str | None = Field(default=None, max_length=32)  # pin a provider ("moth" / "external")
    params: dict[str, Any] | None = None
    # MOTH Code keeps its own history on the computer: it sends recent turns and asks not to store them
    history: list[dict[str, str]] | None = Field(default=None, max_length=40)
    store: bool = True


@router.post("/v1/chat")
def chat(body: ChatIn, request: Request, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    from moth.model.chat_format import Message
    from moth.model.generation import GenerationParams

    if auth.user["email_verified_at"] is None:
        raise HTTPException(403, "Verify your email address first.")
    policy = _policy(ctx)
    decision = policy.check_input(body.message)
    if not decision.allowed:
        raise HTTPException(422, decision.message)
    ranked = R.rank(ctx, FB.classify(body.message), auth.user, body.model)
    if not ranked:
        e = R.explain_unavailable(ctx, auth.user)
        raise HTTPException(503, {"message": str(e), "reasons": e.reasons})
    consent = FB.consent(auth.user)
    history: list[dict] = [{"role": m.get("role"), "content": str(m.get("content", ""))[:32_000]}
                           for m in (body.history or []) if m.get("role") in ("user", "assistant")][-HISTORY_MESSAGES:]
    if body.conversation_id is not None:
        _conv(ctx, auth.uid, body.conversation_id)
        history = ctx.db.all(select(conversation_messages).where(
            conversation_messages.c.conversation_id == body.conversation_id)
            .order_by(conversation_messages.c.id.desc()).limit(HISTORY_MESSAGES))[::-1]
    system = policy.system_prompt
    sources: list[dict] = []
    use_k = body.use_knowledge if body.use_knowledge is not None else consent["use_knowledge"]
    if use_k and flags(ctx).get("knowledge_enabled"):
        extra, sources = K.context_for(ctx, auth.uid, body.message)
        if extra:
            system = f"{system}\n\n{extra}"
    messages = [Message("system", system)] + [Message(m["role"], m["content"]) for m in history] + \
        [Message("user", body.message)]
    params = GenerationParams.from_dict({**policy.generation_defaults, **(body.params or {})})
    params.max_new_tokens = max(1, min(int(params.max_new_tokens), MAX_NEW_TOKENS))
    eng = ctx.extras.get("inference_engine")
    if eng is not None and getattr(eng, "tokenizer", None) is not None:
        from moth.model.chat_format import encode_chat

        prompt_tokens = len(encode_chat(eng.tokenizer, messages)[0])
    else:
        prompt_tokens = sum(len(m.content) for m in messages) // 3 + 8
    request_id = f"{auth.uid}:chat:{(request.headers.get('x-request-id') or uuid.uuid4().hex)[:48]}"
    try:
        billing.reserve(ctx.db, auth.user, request_id, prompt_tokens + params.max_new_tokens,
                        model=ranked[0].name, allow_existing=False)
    except billing.DuplicateRequest:
        raise HTTPException(409, "This request id was already used.") from None
    except billing.InsufficientUsage:
        raise HTTPException(402, "You've used your MOTH Cloud allowance for this period.") from None

    cid = body.conversation_id
    if consent["keep_history"] and body.store and cid is None:
        with ctx.db.tx() as c:
            cid = c.execute(conversations.insert().values(user_id=auth.uid, title=body.message.strip()[:80],
                                                          model=ranked[0].name, created_at=now(), updated_at=now())
                            ).inserted_primary_key[0]
    q: queue.Queue = queue.Queue()
    cancel = threading.Event()
    result: dict[str, Any] = {}

    def work() -> None:
        try:
            p, st, cap = R.generate(ctx, auth.user, messages, params, lambda t: q.put(("delta", t)), cancel, body.model)
            result.update(provider=p, stats=st, capability=cap)
        except Exception as e:  # noqa: BLE001
            result["error"] = str(e) if isinstance(e, R.NoModelAvailable) else f"The model failed: {type(e).__name__}"
        finally:
            q.put(("end", None))

    threading.Thread(target=work, daemon=True, name="chat").start()

    def stream():
        parts: list[str] = []
        yield json.dumps({"type": "start", "conversation_id": cid, "model": ranked[0].name,
                          "sources": sources}) + "\n"
        try:
            while True:
                kind, val = q.get()
                if kind == "end":
                    break
                parts.append(val)
                yield json.dumps({"type": "delta", "text": val}) + "\n"
        except GeneratorExit:  # client went away: stop generating
            cancel.set()
            raise
        finally:
            st = result.get("stats") or {}
            billing.settle(ctx.db, request_id, int(st.get("prompt_tokens") or prompt_tokens) if st else 0,
                           int(st.get("generated_tokens") or 0))
        if "error" in result:
            yield json.dumps({"type": "error", "message": result["error"]}) + "\n"
            return
        text = "".join(parts)
        out = policy.filter_output(text)
        final = out.text if out.allowed else out.message
        p = result["provider"]
        mid = None
        if cid is not None:
            with ctx.db.tx() as c:
                c.execute(conversation_messages.insert().values(
                    conversation_id=cid, role="user", content=body.message, created_at=now()))
                mid = c.execute(conversation_messages.insert().values(
                    conversation_id=cid, role="assistant", content=final, model=p.name, model_version=p.model_version,
                    sources=json.dumps(sources), stats=json.dumps(result["stats"]), created_at=now())
                ).inserted_primary_key[0]
                c.execute(conversations.update().where(conversations.c.id == cid).values(updated_at=now()))
        if final != text:
            yield json.dumps({"type": "replace", "text": final}) + "\n"
        yield json.dumps({"type": "done", "message_id": mid, "conversation_id": cid, "model": p.name,
                          "model_version": p.model_version, "provider": p.id, "capability": result["capability"],
                          "sources": sources, "stats": result["stats"]}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---- feedback ------------------------------------------------------------------------------------------
class FeedbackIn(BaseModel):
    message_id: int | None = None
    rating: int
    category: str = ""
    comment: str = Field(default="", max_length=2000)
    correction: str = Field(default="", max_length=8000)
    prompt: str | None = Field(default=None, max_length=8000)  # for answers not stored in the cloud
    response: str | None = Field(default=None, max_length=8000)
    model: str | None = None


@router.post("/v1/feedback")
def post_feedback(body: FeedbackIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    if not flags(ctx).get("feedback_collection"):
        raise HTTPException(403, "Feedback collection is turned off.")
    try:
        return FB.submit(ctx, auth.user, body.message_id, body.rating, body.category, body.comment, body.correction,
                         body.prompt, body.response, body.model)
    except FB.FeedbackError as e:
        raise HTTPException(400, str(e)) from None


@router.get("/v1/admin/feedback")
def admin_feedback(status: str | None = None, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    rows = FB.listing(ctx, status)
    return {"summary": FB.summary(ctx), "counts": FB.counts(ctx), "feedback": rows}


class ReviewIn(BaseModel):
    approve: bool


@router.post("/v1/admin/feedback/{fid}/review")
def review_feedback(fid: int, body: ReviewIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return FB.review(ctx, fid, body.approve)
    except FB.FeedbackError as e:
        raise HTTPException(400, str(e)) from None


# ---- knowledge -------------------------------------------------------------------------------------------
class DocIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=K.MAX_DOC_CHARS)
    source: str = Field(default="", max_length=500)
    license: str = Field(default="", max_length=64)
    key: str | None = Field(default=None, max_length=200)


def _kerr(e: K.KnowledgeError):
    return HTTPException(404 if "not found" in str(e) else 400, str(e))


@router.get("/v1/knowledge")
def my_knowledge(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    return {"documents": K.list_docs(ctx, auth.uid)}


@router.post("/v1/knowledge")
def add_knowledge(body: DocIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    try:
        return K.add(ctx, auth.uid, body.title, body.text, body.source, body.license, body.key)
    except K.KnowledgeError as e:
        raise _kerr(e) from None


@router.post("/v1/admin/knowledge")
def add_shared_knowledge(body: DocIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return K.add(ctx, None, body.title, body.text, body.source, body.license, body.key)
    except K.KnowledgeError as e:
        raise _kerr(e) from None


@router.get("/v1/knowledge/search")
def search_knowledge(q: str, k: int = 5, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    return {"results": K.search(ctx, auth.uid, q[:500], max(1, min(k, 20)))}


@router.get("/v1/knowledge/{doc_id}/versions")
def knowledge_versions(doc_id: int, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    try:
        return {"versions": K.versions(ctx, auth.uid, doc_id)}
    except K.KnowledgeError as e:
        raise _kerr(e) from None


@router.delete("/v1/knowledge/{doc_id}")
def delete_knowledge(doc_id: int, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    try:
        K.remove(ctx, auth.uid, doc_id, is_owner=auth.is_owner)
    except K.KnowledgeError as e:
        raise _kerr(e) from None
    return {"ok": True}


# ---- dataset library (Owner) ---------------------------------------------------------------------------
@router.get("/v1/admin/library")
def get_library(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return library.status(ctx)


class BuildIn(BaseModel):
    sources: list[str] | None = None


@router.post("/v1/admin/library/build")
def build_library(body: BuildIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    cfg = {"sources": body.sources} if body.sources else {}
    return {"build": library.start_build(ctx, auth.uid, cfg)}


@router.post("/v1/admin/library/check-updates")
def library_updates(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    return {"results": library.check_updates(ctx)}


class PinIn(BaseModel):
    dataset: str
    revision: str = Field(min_length=7, max_length=64)


@router.post("/v1/admin/library/approve-update")
def library_approve(body: PinIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return {"pin": library.approve_update(ctx, body.dataset, body.revision, auth.uid)}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e)) from None


# ---- external provider (Owner; off by default) ------------------------------------------------------------
class ExternalIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=8, max_length=300)
    model: str = Field(min_length=1, max_length=100)
    api_key_env: str = Field(default="", max_length=64)  # name of the environment variable holding the key
    capabilities: dict[str, float] = Field(default_factory=dict)
    context_length: int | None = None


@router.put("/v1/admin/external-provider")
def set_external(body: ExternalIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    if not body.base_url.startswith("https://") and not body.base_url.startswith("http://127.0.0.1"):
        raise HTTPException(400, "Use an https:// endpoint.")
    ctx.db.set_config("external_provider", body.model_dump())
    return {"ok": True}


@router.delete("/v1/admin/external-provider")
def delete_external(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    ctx.db.set_config("external_provider", None)
    return {"ok": True}


# ---- weaknesses and curriculum ---------------------------------------------------------------------------
def _lineage_versions(ctx: Ctx) -> tuple[int | None, int | None, list[int]]:
    from moth_server.evolution import memory as MEM

    v = ctx.extras.get("deployed_version")
    if v is None:
        return None, None, []
    anc = MEM.ancestors(ctx, v)
    parent = anc[1]["version"] if len(anc) > 1 else None
    return v, parent, [a["version"] for a in reversed(anc)] or [v]


@router.get("/v1/intelligence/weaknesses")
def weaknesses(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    v, parent, _ = _lineage_versions(ctx)
    return weakness.analyse(ctx, v, parent, FB.summary(ctx, since=time.time() - 30 * 86400))


@router.get("/v1/intelligence/curriculum")
def get_curriculum(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    v, parent, chain = _lineage_versions(ctx)
    analysis = weakness.analyse(ctx, v, parent, FB.summary(ctx, since=time.time() - 30 * 86400))
    return {"progress": curriculum.progress(ctx, chain),
            "next_mixture": curriculum.plan(ctx, 20_000_000, analysis)}
