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
from moth_server import models as _M

router = APIRouter(tags=["intelligence"])
MAX_NEW_TOKENS = 1024
HISTORY_MESSAGES = 16


def setup(ctx: Ctx) -> None:
    library.recover(ctx)


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


# ---- 2.1 app preferences that follow the account to other computers --------------------------------------
PREF_KEYS = {"ui_size": ("compact", "normal", "large"), "motion": (True, False), "quiet_alerts": (True, False),
             "sounds": (True, False), "theme": ("dark", "midnight", "graphite", "light"),
             "accent": ("red", "blue", "green", "purple", "orange", "pink")}
LIST_PREFS = {"saved_prompts": (30, 2000)}  # 2.4: name → (max items, max characters each)


class PrefsIn(BaseModel):
    ui_size: str | None = None
    motion: bool | None = None
    quiet_alerts: bool | None = None
    sounds: bool | None = None
    theme: str | None = None
    accent: str | None = None
    saved_prompts: list[str] | None = Field(default=None, max_length=30)


def _prefs(user: dict) -> dict:
    ui = json.loads(user.get("settings") or "{}").get("ui") or {}
    return {k: ui[k] for k in (*PREF_KEYS, *LIST_PREFS) if k in ui}


@router.get("/v1/me/preferences")
def get_prefs(auth: Auth = Depends(current_auth)):
    return {"preferences": _prefs(auth.user)}


@router.put("/v1/me/preferences")
def put_prefs(body: PrefsIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    from moth_server.db import users

    values = {k: v for k, v in body.model_dump().items() if v is not None}
    for k, v in values.items():
        if k in LIST_PREFS:
            n, size = LIST_PREFS[k]
            if len(v) > n or any(len(x) > size for x in v):
                raise HTTPException(422, f"Too many or too long items in {k}.")
            continue
        if v not in PREF_KEYS[k]:
            raise HTTPException(422, f"Unknown value for {k}.")
    with ctx.db.tx() as c:
        row = c.execute(select(users.c.settings).where(users.c.id == auth.uid)).first()
        s = json.loads(row[0] or "{}")
        s["ui"] = {**(s.get("ui") or {}), **values}
        c.execute(users.update().where(users.c.id == auth.uid).values(settings=json.dumps(s)))
    return {"preferences": {k: s["ui"][k] for k in (*PREF_KEYS, *LIST_PREFS) if k in s["ui"]}}


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
    # 2.0 tools: exact arithmetic instead of a guess
    from moth.inference.tools import calculate

    calc = calculate(body.message)
    if calc:
        system = f"{system}\n\nCalculator (exact, already computed): {calc[0]} = {calc[1]}. Use this value."
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
    except billing.InsufficientUsage as e:
        raise HTTPException(402, e.user_message()) from None

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
    category: str | None = Field(default=None, max_length=40)       # 0.8.0 Knowledge 2.0
    project: str | None = Field(default=None, max_length=200)


class DocMetaIn(BaseModel):
    category: str | None = Field(default=None, max_length=40)
    project: str | None = Field(default=None, max_length=200)
    confidence: float | None = Field(default=None, ge=0, le=1)
    verified: bool | None = None
    review_days: int | None = Field(default=None, ge=1, le=3650)


class ResearchIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)
    project: str | None = Field(default=None, max_length=200)
    save: bool = False


def _kerr(e: K.KnowledgeError):
    return HTTPException(404 if "not found" in str(e) else 400, str(e))


@router.get("/v1/knowledge")
def my_knowledge(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    return {"documents": K.list_docs(ctx, auth.uid)}


@router.post("/v1/knowledge")
def add_knowledge(body: DocIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    try:
        return K.add(ctx, auth.uid, body.title, body.text, body.source, body.license, body.key,
                     category=body.category, project=body.project)
    except K.KnowledgeError as e:
        raise _kerr(e) from None


@router.post("/v1/admin/knowledge")
def add_shared_knowledge(body: DocIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    try:
        return K.add(ctx, None, body.title, body.text, body.source, body.license, body.key,
                     category=body.category, project=body.project)
    except K.KnowledgeError as e:
        raise _kerr(e) from None


@router.get("/v1/knowledge/search")
def search_knowledge(q: str, k: int = 5, project: str | None = None, auth: Auth = Depends(current_auth),
                     ctx: Ctx = Depends(get_ctx)):
    return {"results": K.search(ctx, auth.uid, q[:500], max(1, min(k, 20)), project=project)}


@router.patch("/v1/knowledge/{doc_id}")
def update_knowledge(doc_id: int, body: DocMetaIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """Category, project, confidence, verification and review date of a document (Knowledge 2.0)."""
    from moth_server.intelligence import knowledge2 as K2

    try:
        return {"meta": K2.update(ctx, auth.uid, doc_id, body.model_dump(exclude_none=True), is_owner=auth.is_owner)}
    except K.KnowledgeError as e:
        raise _kerr(e) from None


@router.post("/v1/research")
def research(body: ResearchIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """A cited, extractive research report over the knowledge this account may see (Research Engine)."""
    from moth_server.intelligence import research as R

    try:
        report = R.run(ctx, auth.uid, body.question, body.project)
        if body.save and report["findings"]:
            report["saved"] = R.save(ctx, auth.uid, report)["document"]
    except K.KnowledgeError as e:
        raise _kerr(e) from None
    return report


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


class DiscoveryIn(BaseModel):
    changes: dict[str, Any]


@router.get("/v1/admin/library/discovery")
def discovery_status(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    from moth_server.intelligence import discovery
    return discovery.status(ctx)


@router.put("/v1/admin/library/discovery")
def discovery_policy(body: DiscoveryIn, auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.intelligence import discovery
    try:
        result = discovery.update(ctx, body.changes)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    from moth_server.audit import audit
    audit(ctx.db, "library.discovery_policy", auth.uid, "library", body.changes)
    return result


@router.post("/v1/admin/library/discovery/prepare")
def discovery_prepare(auth: Auth = Depends(owner_reauthed), ctx: Ctx = Depends(get_ctx)):
    from moth_server.intelligence import discovery
    return discovery.ensure_data(ctx)


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


# ---- 0.5.4: progress dashboard and timeline (every signed-in user; measurements only) ------------------------
def _data_status(ctx: Ctx) -> dict:
    from moth_server.evolution import autopilot as AP
    try:
        return AP.data_status(ctx)
    except Exception:  # noqa: BLE001 — the rest of the page does not depend on it
        return {}


@router.get("/v1/intelligence/progress")
def progress(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """MOTH's lineage, benchmarks per version, training state, datasets and contributions.

    Every number is a stored measurement; the only estimate (time to the next cycle) is labelled."""
    import json as _json

    from sqlalchemy import func, select as _select

    from moth_server import models as M
    from moth_server import serving
    from moth_server.db import workers, audit_log, evolution_experiments
    from moth_server.evolution import engine as EN
    from moth_server.evolution import backends as B
    from moth_server.evolution import memory as MEM
    from moth_server.evolution import settings as ES
    from moth_server.intelligence import curriculum as CU
    from moth_server.intelligence.weakness import capability_reports

    rels = {r["version"]: r for r in M.list_releases(ctx)}
    lineage = MEM.lineage(ctx)
    deployed = ctx.extras.get("deployed_version") if ctx.extras.get("inference_engine") is not None else None
    st = EN.state(ctx)
    stable = st.get("stable_version") or deployed
    active_lineage = (rels.get(deployed) or {}).get('info', {}).get('lineage_id')
    builds = {}
    for b in library.status(ctx)["builds"]:
        if b["status"] == "ready" and b["content_sha256"]:
            builds[b["content_sha256"]] = b

    def ds_names(shas):
        out = []
        for s in shas or []:
            b = builds.get(s)
            out.append({"build": b["id"], "sources": [x["id"] for x in b["sources"]]} if b else {"sha256": s[:12]})
        return out

    versions = []
    for row in lineage:
        r = rels.get(row["version"])
        if not r:
            continue
        info = r["info"] or {}
        if deployed and info.get('lineage_id') != active_lineage:
            continue  # archived lineages stay in the registry, not in the active MOTH timeline
        reps = capability_reports(ctx, row["version"])
        versions.append({
            "version": row["version"], "model_version": info.get("model_version"),
            "revision": info.get("revision"), "milestone": info.get("milestone"), "deployed_at": r.get("deployed_at"),
            "name": info.get("display_name") or r["name"], "params": info.get("params"), "params_verified": _M.params_verified(info), "method": row["method"],
            "architecture": info.get("architecture"), "tokenizer_fingerprint": info.get("tokenizer_fingerprint"),
            "config": info.get("config"), "initialization": info.get("initialization"),
            "training": {k: (info.get("training") or {}).get(k) for k in
                         ("step", "steps", "best_val", "val_loss", "train_loss", "tokens", "backend")},
            "parent": row["parent_version"], "created_at": row["created_at"], "status": r["status"],
            "deployed": row["version"] == deployed, "stable": row["version"] == stable,
            "has_dev_checkpoint": bool((info.get("dev_checkpoint") or {}).get("path")),
            "retained": bool(r.get("path")) and __import__("pathlib").Path(r["path"]).exists(),
            "growth": info.get("growth"), "lineage_totals": info.get("lineage_totals"),
            "datasets": ds_names(_json.loads(row["datasets"]) if isinstance(row["datasets"], str) else row["datasets"]),
            "benchmarks": {k: {"value": v["value"], "metric": v.get("metric"), "higher_is_better": v.get("higher_is_better"),
                               "bits_per_byte": v.get("bits_per_byte"),
                               "evaluated_at": v.get("evaluated_at"), "skills": v.get("skills"),
                               "context_retention": v.get("context_retention")}
                           for k, v in reps.items()},
            "performance": (info.get("serving") or {}).get("performance")})
    # 2.3: why each version was or was not promoted, and its side-by-side replies (from its experiment)
    by_version = {}
    if versions:
        for row in ctx.db.all(_select(evolution_experiments.c.candidate_version, evolution_experiments.c.status,
                                      evolution_experiments.c.error, evolution_experiments.c.metrics)
                              .where(evolution_experiments.c.candidate_version.in_([v["version"] for v in versions]))):
            met = _json.loads(row["metrics"] or "{}") if isinstance(row["metrics"], str) else (row["metrics"] or {})
            failed = [g.get("name") or g["gate"] for g in met.get("gates") or [] if not g.get("passed")]
            by_version[row["candidate_version"]] = {
                "outcome": row["status"], "decision": met.get("decision") or row["error"],
                "failed": failed[:6], "trade_offs": (met.get("trade_offs") or [])[:6],
                "improvement": met.get("primary_improvement"), "compare": met.get("compare")}
    for v in versions:
        if v["version"] in by_version:
            v["promotion"] = by_version[v["version"]]
    dev = next((v for v in reversed(versions) if v["has_dev_checkpoint"]), None)
    lineage_versions = {v['version'] for v in versions}
    cyc = next((c for c in MEM.cycles(ctx, 100) if c['base_version'] in lineage_versions), None)
    s = ES.get(ctx)
    online = [w for w in ctx.db.all(_select(workers).where(workers.c.revoked_at.is_(None)))]
    t = __import__("time").time()
    on = [w for w in online if (w["last_heartbeat_at"] or 0) >= t - 180]
    # 2.1: MOTH Cloud's own built-in worker is not "a worker online": count only other computers
    cloud_on = [w for w in on if _json.loads(w["hardware"] or "{}").get("worker_kind") == "cloud"]
    on = [w for w in on if w not in cloud_on]
    gpu = sum(1 for w in on if _json.loads(w["hardware"] or "{}").get("compute") == "gpu")
    latest = library.latest_ready(ctx)
    lib = None
    if latest:
        m = _json.loads(latest["manifest"] or "{}")
        lib = {"build": latest["id"], "domains": m.get("domains"),
               "sources": [{"id": x["id"], "name": x["name"], "license": x["license"], "records": (x.get("stats") or {}).get("kept")}
                           for x in m.get("sources", [])]}
    exp = next((e for e in MEM.experiments(ctx, cyc["id"])), None) if cyc else None
    # Prefer the currently executing experiment over a later, merely planned variant.
    experiments = MEM.experiments(ctx, cyc["id"]) if cyc else []
    exp = next((e for e in experiments if e["status"] == "running"), exp)
    from moth_server.evolution import distributed as D
    experiment_history = [{"id": e["id"], "status": e["status"], "backend": e["backend"],
                          "device": (e.get("resources") or {}).get("device"),
                          "method": e["config"].get("method"), "growth": e["config"].get("grow"),
                          "successor": {k: (e["config"].get("rebirth") or {}).get(k) for k in
                                        ("params_before", "params_after", "architecture", "planned_hours")}
                          if e["config"].get("rebirth") else None,
                          # 0.10.0: what one loss unit covers, so the live view can say how well it writes
                          "loss_per": "token" if ((e["config"].get("rebirth") or {}).get("tokenizer")
                                                  or int((((e["config"].get("rebirth") or {}).get("architecture") or {})
                                                          .get("vocab_size")) or _base_vocab(ctx, e)) > 512) else "byte",
                          "requires_approval": bool(e["config"].get("requires_approval") and not e["config"].get("approved_by")),
                          # 2.1: why a run trains on MOTH Cloud alone (e.g. "no other computer is online")
                          "not_shared_reason": (e.get("resources") or {}).get("handoff_reason"),
                          "progress": e.get("progress"), "metrics": e.get("metrics"),
                          "measurement": B.progress(ctx, e)
                          if e.get('backend') == 'local' and e['status'] in ('running', 'paused')
                          else (B.worker_report(ctx, e) if e.get('backend') == 'worker' and e['status'] == 'running'
                                else D.report(e) if e.get('backend') == 'distributed' and e['status'] == 'running' else {})
                          or (e.get('metrics') or {}).get('progress') or (e.get('metrics') or {}).get('training') or {},
                          "candidate_version": e.get("candidate_version"), "error": e.get("error"),
                          # 0.6.2 telemetry: when it ran, on what data and at what settings (owner only below)
                          "started_at": e.get("started_at"), "finished_at": e.get("finished_at"),
                          # 0.8.1: measured by MOTH Cloud's clock from when the compute actually took the work
                          # (a worker experiment can wait in the queue long before a worker leases it)
                          "elapsed_seconds": _elapsed(e),
                          "compute_seconds": e.get("compute_seconds"), "worker_id": e.get("worker_id"),
                          "data": {"stage": ((e["config"] or {}).get("mixture") or {}).get("stage"),
                                   "domains": ((e["config"] or {}).get("mixture") or {}).get("weights") or {},
                                   "dataset_id": e.get("dataset_id")},
                          "plan": {k: (e["config"] or {}).get(k) for k in ("steps", "lr", "batch_size", "seq_len")},
                          "rationale": e.get("rationale") if auth.user["role"] == "owner" else None}
                         for e in experiments]
    current = next((v for v in versions if v["deployed"]), None)
    loaded = rels.get(deployed)
    # Legacy uploads may predate lineage registration. The loaded engine remains authoritative.
    if loaded and not current:
        info = loaded['info'] or {}
        current = {"version": loaded['version'], "model_version": info.get('model_version'),
                   "revision": info.get('revision'), "name": info.get('display_name') or loaded['name'],
                   "params": info.get('params'), "params_verified": _M.params_verified(info), "config": info.get('config'), "training": info.get('training') or {},
                   "tokenizer_fingerprint": info.get('tokenizer_fingerprint'), "deployed_at": loaded.get('deployed_at'),
                   "benchmarks": capability_reports(ctx, loaded['version']), "deployed": True, "stable": True}
        versions.append(current)
    checkpoint = None
    if loaded and current:
        from pathlib import Path
        info = loaded['info'] or {}
        current['model_id'] = getattr(ctx.extras.get('inference_engine'), 'model_id', loaded['name'])
        dev_checkpoint = info.get('dev_checkpoint') or {}
        if dev_checkpoint.get('path'):
            checkpoint = {'available': Path(dev_checkpoint['path']).is_file(),
                          'step': (info.get('training') or {}).get('step'), 'sha256': dev_checkpoint.get('sha256')}
    improvement = None
    measured = ctx.db.one(_select(evolution_experiments.c.id, evolution_experiments.c.metrics)
        .where(evolution_experiments.c.candidate_version == deployed, evolution_experiments.c.status == 'passed')
        .order_by(evolution_experiments.c.id.desc()).limit(1)) if deployed else None
    if measured:
        metrics = _json.loads(measured.get('metrics') or '{}')
        gates = metrics.get('gates') or []
        value = metrics.get('primary_improvement')
        import math
        if gates and all(g.get('passed') for g in gates) and type(value) in (int,float) and math.isfinite(value):
            improvement = {'verified': True, 'primary_improvement': value, 'experiment_id': measured['id']}
    from moth_server.intelligence.activity import feed as recent_activity
    from moth_server.evolution import native_reset as NR
    reset_fenced=NR.fenced(ctx)
    accepting = bool(loaded and flags(ctx).get('cloud_inference_enabled') and not reset_fenced)
    return {
        "observed_at": now(), "serving": {'loaded': bool(loaded), 'accepting_requests': accepting,
            'reason': 'Native reset recovery is required' if reset_fenced else 'Ready to answer' if accepting else 'Cloud answering is turned off' if loaded else 'No native model is loaded'},
        "checkpoint": checkpoint, "improvement": improvement,
        # 0.7.1: exactly one active model and one rollback model keep their weights
        "lifecycle": _lifecycle(ctx, current),
        "activity": recent_activity(ctx,auth.uid,auth.user["role"]=="owner",limit=25),
        "current": current, "stable": next((v for v in versions if v["stable"]), None),
        "development": dev, "rollout": serving.loaded_versions(ctx), "timeline": versions,
        "deployment_events": ctx.db.all(_select(audit_log.c.ts, audit_log.c.action, audit_log.c.target)
            .where(audit_log.c.action.in_(("models.deployed", "models.rollback", "evolution.rollback")))
            .order_by(audit_log.c.id.desc()).limit(30)),
        "training": {"enabled": s["enabled"], "paused": s["paused"], "cycle": {
            "id": cyc["id"], "status": cyc["status"], "waiting_reason": (cyc.get("result") or {}).get("waiting_reason")}
            if cyc else None, "experiment_progress": exp.get("progress") if exp else None,
            "experiments": experiment_history,
            "next_cycle_at_estimate": st.get("next_cycle_at") or None, "curriculum": CU.state(ctx).get("stage")},
        "datasets": lib,
        "data_status": _data_status(ctx),  # 2.5: distinct tokens prepared vs needed, data passes
        "network": {"workers_online": len(on), "gpu_online": gpu, "cpu_online": len(on) - gpu,
                    "cloud_worker_online": bool(cloud_on),
                    "workers_registered": sum(1 for w in online if _json.loads(w["hardware"] or "{}").get("worker_kind") != "cloud"),
                    "verified_tokens": int(ctx.db.one(_select(func.coalesce(func.sum(workers.c.trained_tokens), 0)
                                                              .label("t")))["t"]),
                    "verified_jobs": int(ctx.db.one(_select(func.coalesce(func.sum(workers.c.verified_jobs), 0)
                                                            .label("t")))["t"])},
        "measured": "every value is a measurement on held-out data or a recorded count, except fields named *_estimate",
    }


def _elapsed(e: dict) -> float | None:
    """Seconds of actual work on an experiment, measured on the server (never the viewer's clock)."""
    import time as _t

    res = e.get("resources") or {}
    done = float(e.get("compute_seconds") or 0.0)
    if e.get("status") != "running":
        return round(done, 1) if done > 0 else None
    if e.get("backend") == "worker":
        start = res.get("leased_at")
        return round(max(0.0, _t.time() - float(start)), 1) if start else None
    start = res.get("started")
    return round(done + max(0.0, _t.time() - float(start)), 1) if start else (round(done, 1) if done else None)


def _lifecycle(ctx, current):
    from moth_server.evolution import storage as ST
    from moth_server import models as M

    try:
        rollback = ST.rollback_target(ctx) if current else None
        r = M.release(ctx, rollback) if rollback else None
    except Exception:  # noqa: BLE001 — never breaks the progress page
        rollback, r = None, None
    return {"active": current["version"] if current else None, "rollback": rollback,
            "rollback_name": ((r or {}).get("info") or {}).get("display_name") if r else None,
            "policy": "one active model and one rollback model keep their weights; older versions keep history only"}


@router.get('/v1/intelligence/activity')
def activity_feed(category:str='all',cursor:str|None=None,limit:int=50,auth:Auth=Depends(current_auth),ctx:Ctx=Depends(get_ctx)):
    from moth_server.intelligence.activity import feed
    try:return feed(ctx,auth.uid,auth.user['role']=='owner',category,cursor,limit)
    except ValueError as error:raise HTTPException(422,str(error)) from None


def _base_vocab(ctx: Ctx, e: dict) -> int:
    from moth_server import models as M

    try:
        return int((M.release(ctx, e["base_version"])["info"].get("config") or {}).get("vocab_size") or 0)
    except Exception:  # noqa: BLE001 — a missing release only loses the label
        return 0


# ---- 2.3.1: Home summary — this week's progress, example answers and your computers' share ----------------
@router.get("/v1/intelligence/summary")
def week_summary(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """What MOTH did in the last 7 days, in plain numbers, for every signed-in user. Measurements only."""
    from sqlalchemy import func, select as _select

    from moth_server.db import evolution_experiments as EX, training_jobs as TJ, workers as W

    t = time.time()
    since = t - 7 * 86400
    rels = _M.list_releases(ctx)
    current = next((r for r in rels if r["status"] == "deployed"), None)
    promoted = [{"version": r["version"], "model_version": r["info"].get("model_version"),
                 "params": r["info"].get("params"), "at": r["deployed_at"]}
                for r in rels if (r.get("deployed_at") or 0) >= since]
    outcomes: dict[str, int] = {}
    for row in ctx.db.all(_select(EX.c.status, func.count().label("n")).where(EX.c.finished_at >= since).group_by(EX.c.status)):
        outcomes[row["status"]] = int(row["n"])
    mine = [w["id"] for w in ctx.db.all(_select(W.c.id).where(W.c.user_id == auth.uid, W.c.revoked_at.is_(None)))]
    mine_seconds = mine_jobs = 0
    if mine:
        r = ctx.db.one(_select(func.coalesce(func.sum(EX.c.compute_seconds), 0.0).label("s"))
                       .where(EX.c.worker_id.in_(mine), EX.c.finished_at >= since))
        mine_seconds = float((r or {}).get("s") or 0)
        r = ctx.db.one(_select(func.count().label("n")).where(TJ.c.worker_id.in_(mine), TJ.c.status == "completed",
                                                             TJ.c.updated_at >= since))
        mine_jobs = int((r or {}).get("n") or 0)
    examples = None
    if current:
        row = ctx.db.one(_select(EX.c.metrics).where(EX.c.candidate_version == current["version"])
                         .order_by(EX.c.id.desc()).limit(1))
        if row:
            met = json.loads(row["metrics"] or "{}") if isinstance(row["metrics"], str) else (row["metrics"] or {})
            examples = met.get("compare")
    first = min((r for r in rels if (r.get("deployed_at") or 0) >= since), key=lambda r: r["version"], default=None)
    return {"since": since,
            "current": {"version": current["version"], "model_version": current["info"].get("model_version"),
                        "params": current["info"].get("params")} if current else None,
            "params_at_start": (first or {}).get("info", {}).get("params") if first else None,
            "promoted": promoted, "experiments": outcomes,
            "your_computers": {"count": len(mine), "jobs": mine_jobs, "hours": round(mine_seconds / 3600, 1)},
            "examples": examples}


# ---- 2.4: leaderboard — whose computers trained MOTH most this week -------------------------------------
@router.get("/v1/intelligence/leaderboard")
def leaderboard(auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    """Usernames and measured training time of the last 7 days (finished experiments and verified jobs).
    MOTH Cloud's own worker is not a person and is left out."""
    from sqlalchemy import func, select as _select

    from moth_server.db import evolution_experiments as EX, training_jobs as TJ, users as U, workers as W

    since = time.time() - 7 * 86400
    owners = {w["id"]: w["user_id"] for w in ctx.db.all(_select(W.c.id, W.c.user_id, W.c.hardware))
              if json.loads(w["hardware"] or "{}").get("worker_kind") != "cloud"}
    secs: dict[int, float] = {}
    jobs: dict[int, int] = {}
    if owners:
        for r in ctx.db.all(_select(EX.c.worker_id, func.coalesce(func.sum(EX.c.compute_seconds), 0.0).label("s"))
                            .where(EX.c.finished_at >= since, EX.c.worker_id.in_(list(owners))).group_by(EX.c.worker_id)):
            secs[owners[r["worker_id"]]] = secs.get(owners[r["worker_id"]], 0.0) + float(r["s"] or 0)
        for r in ctx.db.all(_select(TJ.c.worker_id, func.count().label("n"))
                            .where(TJ.c.status == "completed", TJ.c.updated_at >= since, TJ.c.worker_id.in_(list(owners)))
                            .group_by(TJ.c.worker_id)):
            jobs[owners[r["worker_id"]]] = jobs.get(owners[r["worker_id"]], 0) + int(r["n"])
    people = set(secs) | set(jobs)
    names = {u["id"]: u["username"] for u in ctx.db.all(_select(U.c.id, U.c.username).where(U.c.id.in_(list(people))))} if people else {}
    ranked = sorted(people, key=lambda uid: (-jobs.get(uid, 0), -secs.get(uid, 0.0)))
    rows = [{"rank": i + 1, "username": names.get(uid, "someone"), "jobs": jobs.get(uid, 0),
             "hours": round(secs.get(uid, 0.0) / 3600, 1), "you": uid == auth.uid} for i, uid in enumerate(ranked)]
    mine = next((r for r in rows if r["you"]), None)
    return {"since": since, "top": rows[:10], "you": mine}


# ---- 2.4: "Report a problem" — the app sends its recent logs to the Owner ---------------------------------
class ProblemIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    app_version: str | None = Field(default=None, max_length=40)
    details: dict = Field(default_factory=dict)  # logs and status the app gathered (size-checked below)


REPORTS_KEPT = 200


def _reports_dir(ctx: Ctx):
    from pathlib import Path

    d = Path(ctx.settings.data_dir) / "problem-reports"
    d.mkdir(parents=True, exist_ok=True)
    return d


@router.post("/v1/problem-reports", status_code=201)
def report_problem(body: ProblemIn, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    from moth_server.ratelimit import RateLimited

    try:
        ctx.limiter.hit(f"problem-report:{auth.uid}", 10, 3600)
    except RateLimited:
        raise HTTPException(429, "Too many reports in the last hour; please try again later.") from None
    details = json.dumps(body.details, default=str)
    if len(details) > 400_000:
        raise HTTPException(413, "The report is too large.")
    rid = f"{int(time.time())}-{auth.uid}-{uuid.uuid4().hex[:6]}"
    (_reports_dir(ctx) / f"{rid}.json").write_text(json.dumps({
        "id": rid, "at": time.time(), "user_id": auth.uid, "username": auth.user.get("username"),
        "message": body.message, "app_version": body.app_version, "details": json.loads(details)}))
    for old in sorted(_reports_dir(ctx).glob("*.json"))[:-REPORTS_KEPT]:
        old.unlink(missing_ok=True)
    return {"id": rid}


@router.get("/v1/admin/problem-reports")
def list_problem_reports(auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    out = []
    for f in sorted(_reports_dir(ctx).glob("*.json"), reverse=True)[:100]:
        try:
            r = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        out.append({k: r.get(k) for k in ("id", "at", "username", "message", "app_version")})
    return out


@router.get("/v1/admin/problem-reports/{rid}")
def get_problem_report(rid: str, auth: Auth = Depends(require_owner), ctx: Ctx = Depends(get_ctx)):
    import re

    if not re.fullmatch(r"\d+-\d+-[0-9a-f]{6}", rid):
        raise HTTPException(404, "Unknown report.")
    f = _reports_dir(ctx) / f"{rid}.json"
    if not f.exists():
        raise HTTPException(404, "Unknown report.")
    return json.loads(f.read_text())
