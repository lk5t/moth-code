"""The Intelligence Router: picks the best available model for each request.

Providers:

* ``moth`` — MOTH's own deployed model (native inference on this server). Its per-capability scores
  come from the capability benchmarks recorded for the deployed version.
* ``external`` — an OpenAI-compatible chat endpoint the Owner configured. **Off by default** (flag
  ``external_ai_enabled``) and used only for users who opted in (``settings.external_ai``); its
  capability scores are declared by the Owner. User data never leaves the server otherwise.

For each request the router classifies what the request needs (code, maths, knowledge …), ranks the
available providers by their score for that capability, then by measured latency, and tries them in
order; a provider that fails is skipped and its failure recorded. When no provider can answer, the
error says why in plain words (no model deployed, inference turned off, …).
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import evaluation_reports
from moth_server.intelligence.feedback import classify

CAPABILITIES = ("conversation", "knowledge", "writing", "reasoning", "math", "code")


class NoModelAvailable(RuntimeError):
    def __init__(self, message: str, reasons: list[str]):
        super().__init__(message)
        self.reasons = reasons


@dataclass
class Provider:
    id: str
    kind: str
    name: str
    available: bool
    reason: str = ""
    scores: dict[str, float] = field(default_factory=dict)
    params: int | None = None
    context_length: int | None = None
    requirements: dict[str, Any] = field(default_factory=dict)
    model_version: int | None = None
    generate: Callable[..., dict[str, Any]] | None = None

    def public(self, stats: dict[str, Any]) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "name": self.name, "available": self.available,
                "reason": self.reason, "capabilities": self.scores, "params": self.params,
                "context_length": self.context_length, "requirements": self.requirements,
                "model_version": self.model_version, **stats}


def _stats(ctx: Ctx) -> dict[str, dict[str, Any]]:
    return ctx.extras.setdefault("router_stats", {})


def record(ctx: Ctx, pid: str, ok: bool, seconds: float, tokens: int) -> None:
    lock = ctx.extras.setdefault("router_lock", threading.Lock())
    with lock:
        s = _stats(ctx).setdefault(pid, {"requests": 0, "failures": 0, "latency_ms": None, "tokens_per_second": None})
        s["requests"] += 1
        if not ok:
            s["failures"] += 1
            return
        ms = seconds * 1000
        s["latency_ms"] = round(ms if s["latency_ms"] is None else 0.8 * s["latency_ms"] + 0.2 * ms, 1)
        if tokens and seconds > 0:
            tps = tokens / seconds
            s["tokens_per_second"] = round(tps if s["tokens_per_second"] is None else
                                           0.8 * s["tokens_per_second"] + 0.2 * tps, 2)


def native_scores(ctx: Ctx, version: int | None) -> dict[str, float]:
    """Benchmarked capability scores (0..1) of a model version, from its stored capability reports."""
    if version is None:
        return {}
    out: dict[str, float] = {}
    for r in ctx.db.all(select(evaluation_reports).where(evaluation_reports.c.model_version == version)):
        if not r["suite"].startswith("capability:"):
            continue
        m = json.loads(r["metrics"])
        if not m.get("ok"):
            continue
        cap = r["suite"].split(":", 2)[1]
        if m.get("higher_is_better"):
            out[cap] = round(float(m["value"]), 4)
    # conversation quality is approximated by instruction following until rated feedback accumulates
    if "instruction" in out:
        out.setdefault("conversation", out["instruction"])
        out.setdefault("writing", out["instruction"])
        out.setdefault("knowledge", out["instruction"])
    return out


def _native(ctx: Ctx, user: dict | None = None) -> Provider:
    from moth_server import serving
    from moth_server.routes.admin import flags

    eng, version, why = serving.engine_for(ctx, user)
    if eng is None or not getattr(eng, "manifest", None):
        return Provider("moth", "native", "MOTH", False, "No MOTH model is deployed on this server yet.")
    m = eng.manifest
    name = (m.get("display_name") or m.get("name") or "MOTH")
    if not flags(ctx).get("cloud_inference_enabled"):
        return Provider("moth", "native", name, False, "MOTH Cloud inference is turned off by the Owner.",
                        params=m.get("params"), model_version=version)

    def gen(messages, params, on_text, cancel):
        from moth_server.evolution.compute import activity

        act, t0, ok, st = activity(ctx), time.time(), False, None
        act.start()
        try:
            st = eng.chat(messages, params, on_text, cancel)
            ok = True
        finally:  # the evolution monitor judges each served version by its own traffic
            act.finish(version, ok, time.time() - t0, st.generated_tokens if st else 0)
        return {"prompt_tokens": st.prompt_tokens, "generated_tokens": st.generated_tokens, "seconds": st.seconds,
                "stop_reason": st.stop_reason, "served_as": why}

    return Provider("moth", "native", name, True, scores=native_scores(ctx, version), params=m.get("params"),
                    context_length=m.get("context_length"), model_version=version,
                    requirements={"memory_bytes": (m.get("resources") or {}).get("memory_bytes")}, generate=gen)


def external_config(ctx: Ctx) -> dict[str, Any] | None:
    return ctx.db.get_config("external_provider", None)


def _external(ctx: Ctx, user: dict | None) -> Provider | None:
    from moth_server.intelligence.feedback import consent
    from moth_server.routes.admin import flags

    cfg = external_config(ctx)
    if not cfg:
        return None
    name = cfg.get("name") or cfg.get("model") or "External model"
    if not flags(ctx).get("external_ai_enabled"):
        return Provider("external", "external", name, False, "External AI providers are turned off by the Owner.")
    if user is not None and not consent(user)["external_ai"]:
        return Provider("external", "external", name, False, "You have not allowed external AI providers.")
    key = os.environ.get(cfg.get("api_key_env") or "", "")

    def gen(messages, params, on_text, cancel):
        import httpx

        body = {"model": cfg["model"], "stream": True, "max_tokens": params.max_new_tokens,
                "temperature": params.temperature,
                "messages": [{"role": m.role if m.role in ("system", "user", "assistant") else "user",
                              "content": m.content} for m in messages]}
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        t0, n = time.time(), 0
        with httpx.stream("POST", cfg["base_url"].rstrip("/") + "/chat/completions", json=body, headers=headers,
                          timeout=float(cfg.get("timeout", 60))) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if cancel.is_set():
                    break
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                delta = (json.loads(data).get("choices") or [{}])[0].get("delta", {}).get("content")
                if delta:
                    n += 1
                    on_text(delta)
        return {"prompt_tokens": 0, "generated_tokens": n, "seconds": time.time() - t0, "stop_reason": "eos"}

    scores = {c: float(v) for c, v in (cfg.get("capabilities") or {}).items() if c in CAPABILITIES}
    return Provider("external", "external", name, True, scores=scores, generate=gen,
                    context_length=cfg.get("context_length"))


def providers(ctx: Ctx, user: dict | None = None) -> list[Provider]:
    out = [_native(ctx, user)]
    ext = _external(ctx, user)
    if ext:
        out.append(ext)
    return out


def rank(ctx: Ctx, capability: str, user: dict | None = None, pinned: str | None = None) -> list[Provider]:
    stats = _stats(ctx)
    ps = [p for p in providers(ctx, user) if p.available]
    if pinned:
        ps = [p for p in ps if p.id == pinned]

    def key(p: Provider):
        s = stats.get(p.id, {})
        fail = (s.get("failures", 0) / s["requests"]) if s.get("requests") else 0.0
        native_bonus = 0.01 if p.kind == "native" else 0.0  # prefer MOTH on ties: data stays here
        return (-(p.scores.get(capability, 0.0) + native_bonus - fail), s.get("latency_ms") or 1e9)

    return sorted(ps, key=key)


def explain_unavailable(ctx: Ctx, user: dict | None) -> NoModelAvailable:
    reasons = [p.reason for p in providers(ctx, user) if not p.available and p.reason]
    msg = reasons[0] if reasons else "No AI model is available right now."
    return NoModelAvailable(msg, reasons)


def generate(ctx: Ctx, user: dict | None, messages, params, on_text: Callable[[str], None],
             cancel: threading.Event, pinned: str | None = None) -> tuple[Provider, dict[str, Any], str]:
    """Answer with the best provider; falls back to the next one if a provider fails before any output."""
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    capability = classify(last_user)
    order = rank(ctx, capability, user, pinned)
    if not order:
        raise explain_unavailable(ctx, user)
    errors = []
    for p in order:
        produced = []

        def emit(t: str) -> None:
            produced.append(t)
            on_text(t)

        t0 = time.time()
        try:
            st = p.generate(messages, params, emit, cancel)
            record(ctx, p.id, True, time.time() - t0, int(st.get("generated_tokens") or 0))
            return p, st, capability
        except Exception as e:  # noqa: BLE001 - provider failures fall through to the next provider
            record(ctx, p.id, False, time.time() - t0, 0)
            errors.append(f"{p.name}: {type(e).__name__}")
            if produced:  # partial answer already streamed: do not mix two models in one reply
                raise
    raise NoModelAvailable("Every available model failed to answer: " + "; ".join(errors), errors)
