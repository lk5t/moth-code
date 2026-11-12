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
            "growth": info.get("growth"), "lineage_totals": info.get("lineage_totals"),
            "datasets": ds_names(_json.loads(row["datasets"]) if isinstance(row["datasets"], str) else row["datasets"]),
            "benchmarks": {k: {"value": v["value"], "metric": v.get("metric"), "higher_is_better": v.get("higher_is_better")}
                           for k, v in reps.items()}})
    dev = next((v for v in reversed(versions) if v["has_dev_checkpoint"]), None)
    lineage_versions = {v['version'] for v in versions}
    cyc = next((c for c in MEM.cycles(ctx, 100) if c['base_version'] in lineage_versions), None)
    s = ES.get(ctx)
    online = [w for w in ctx.db.all(_select(workers).where(workers.c.revoked_at.is_(None)))]
    t = __import__("time").time()
    on = [w for w in online if (w["last_heartbeat_at"] or 0) >= t - 180]
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
    experiment_history = [{"id": e["id"], "status": e["status"], "backend": e["backend"],
                          "device": (e.get("resources") or {}).get("device"),
                          "method": e["config"].get("method"), "growth": e["config"].get("grow"),
                          "requires_approval": bool(e["config"].get("requires_approval") and not e["config"].get("approved_by")),
                          "progress": e.get("progress"), "metrics": e.get("metrics"),
                          "measurement": B.progress(ctx, e)
                          if e.get('backend') == 'local' and e['status'] in ('running', 'paused')
                          else (e.get('metrics') or {}).get('progress') or (e.get('metrics') or {}).get('training') or {},
                          "candidate_version": e.get("candidate_version"), "error": e.get("error"),
                          # 0.6.2 telemetry: when it ran, on what data and at what settings (owner only below)
                          "started_at": e.get("started_at"), "finished_at": e.get("finished_at"),
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
        "network": {"workers_online": len(on), "gpu_online": gpu, "cpu_online": len(on) - gpu,
                    "verified_tokens": int(ctx.db.one(_select(func.coalesce(func.sum(workers.c.trained_tokens), 0)
                                                              .label("t")))["t"]),
                    "verified_jobs": int(ctx.db.one(_select(func.coalesce(func.sum(workers.c.verified_jobs), 0)
                                                            .label("t")))["t"])},
        "measured": "every value is a measurement on held-out data or a recorded count, except fields named *_estimate",
    }


@router.get('/v1/intelligence/activity')
def activity_feed(category:str='all',cursor:str|None=None,limit:int=50,auth:Auth=Depends(current_auth),ctx:Ctx=Depends(get_ctx)):
    from moth_server.intelligence.activity import feed
    try:return feed(ctx,auth.uid,auth.user['role']=='owner',category,cursor,limit)
    except ValueError as error:raise HTTPException(422,str(error)) from None
