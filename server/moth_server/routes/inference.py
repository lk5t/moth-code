"""Metered MOTH Cloud inference (protocol ``moth-cloud/1`` under ``/cloud``).

Serves only MOTH's own exported models. Disabled until the owner enables the
``cloud_inference_enabled`` flag on a server with MOTH-operated GPU capacity and a model
(``MOTH_SERVER_INFERENCE_MODEL`` = exported model directory). Every request is metered:
the maximum possible tokens are reserved up front and the actual count is settled after.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from moth_server import billing
from moth_server.context import Ctx, get_ctx
from moth_server.deps import Auth, current_auth
from moth_server.routes.admin import flags

router = APIRouter(prefix="/cloud/v1", tags=["cloud"])
MAX_NEW_TOKENS = 2048


def setup(ctx: Ctx) -> None:
    from moth_server.evolution.native_reset import fenced, state
    if fenced(ctx) or state(ctx).get('generation',0):return  # reset retires the legacy environment fallback; registry activation remains explicit
    model_dir = os.environ.get("MOTH_SERVER_INFERENCE_MODEL")
    if model_dir:
        from moth.inference.local import LocalInference

        d = Path(model_dir).resolve()
        engine = LocalInference(d.parent)
        engine.load(d.name, os.environ.get("MOTH_SERVER_INFERENCE_DEVICE", "auto"))
        ctx.extras["inference_engine"] = engine


def engine_or_503(ctx: Ctx):
    engine = ctx.extras.get("inference_engine")
    if not flags(ctx).get("cloud_inference_enabled") or engine is None or engine.manifest is None:
        raise HTTPException(503, "MOTH Cloud inference is not available yet. Use a local model.")
    return engine


@router.get("/health")
def health(ctx: Ctx = Depends(get_ctx)):
    engine = ctx.extras.get("inference_engine")
    enabled = bool(flags(ctx).get("cloud_inference_enabled"))
    models = []
    if engine is None or not engine.manifest:
        status, message = "no_model_deployed", ("MOTH has no model yet. The Owner creates and trains one in "
                                                 "Intelligence.")
    elif not enabled:
        status, message = "inference_disabled", ("A model is deployed, but MOTH Cloud inference is turned off. The Owner "
                                                 "turns it on in Settings → Administration → Policy & flags.")
    else:
        status, message = "ready", "ready"
        m = engine.manifest
        models.append({k: m.get(k) for k in ("name", "architecture", "params", "context_length", "sha256")})
    return {"service": "moth-cloud", "protocol": 1, "models": models, "metered": True, "status": status,
            "message": message, "routed_chat": "/v1/chat"}


@router.post("/chat")
def chat(request: Request, body: dict, auth: Auth = Depends(current_auth), ctx: Ctx = Depends(get_ctx)):
    from moth.model.chat_format import Message, encode_chat
    from moth.model.generation import GenerationParams

    engine = engine_or_503(ctx)
    if body.get("model") != engine.manifest["name"]:
        raise HTTPException(404, "Model not available.")
    if auth.user["email_verified_at"] is None:
        raise HTTPException(403, "Verify your email address first.")
    from moth.policy.engine import PolicyEngine

    policy = PolicyEngine(ctx.db.get_config("content_policy", {}) or {})
    messages = [Message(m["role"], str(m["content"]), bool(m.get("trusted")) and m["role"] == "assistant")
                for m in body.get("messages", [])][:200]
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    decision = policy.check_input(last_user)
    if not decision.allowed:
        raise HTTPException(422, decision.message)
    # The Owner's system prompt always leads; client system text (e.g. agent tool instructions) follows it.
    if messages and messages[0].role == "system":
        messages[0] = Message("system", f"{policy.system_prompt}\n\n{messages[0].content}")
    else:
        messages.insert(0, Message("system", policy.system_prompt))
    params = GenerationParams.from_dict(body.get("params"))
    params.max_new_tokens = max(1, min(int(params.max_new_tokens), MAX_NEW_TOKENS))
    prompt_tokens = len(encode_chat(engine.tokenizer, messages)[0])
    request_id = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:64]
    try:
        billing.reserve(ctx.db, auth.user, f"{auth.uid}:{request_id}", prompt_tokens + params.max_new_tokens,
                        model=engine.manifest["name"], allow_existing=False)
    except billing.DuplicateRequest:
        raise HTTPException(409, "This request id was already used.") from None
    except billing.InsufficientUsage:
        raise HTTPException(402, "You've used your MOTH Cloud allowance for this period. Upgrade, use credits, or "
                                 "switch to local inference.") from None
    cancel = threading.Event()

    from moth_server.evolution.compute import activity

    act, version, t_start = activity(ctx), ctx.extras.get("deployed_version"), time.time()
    act.start()

    def stream():
        chunks: list[str] = []
        stats = None
        ok = False
        try:
            stats = engine.chat(messages, params, chunks.append, cancel)
            out = policy.filter_output("".join(chunks))
            yield json.dumps({"text": out.text if out.allowed else out.message}) + "\n"
            yield json.dumps({"done": True, "stats": {
                "prompt_tokens": stats.prompt_tokens, "generated_tokens": stats.generated_tokens,
                "seconds": stats.seconds, "stop_reason": stats.stop_reason}}) + "\n"
            ok = True
        except Exception as e:  # noqa: BLE001
            yield json.dumps({"error": f"{type(e).__name__}"}) + "\n"
        finally:
            act.finish(version, ok, time.time() - t_start, stats.generated_tokens if stats else 0)
            used_in = stats.prompt_tokens if stats else 0
            used_out = stats.generated_tokens if stats else 0
            billing.settle(ctx.db, f"{auth.uid}:{request_id}", used_in, used_out)

    return StreamingResponse(stream(), media_type="application/x-ndjson")
