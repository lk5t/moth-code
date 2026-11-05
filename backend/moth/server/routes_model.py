"""Model management, chat (streamed through MOTH) and owner policy routes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from moth.inference.local import LocalInference, NoModelLoaded
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams
from moth.model.registry import delete_model, list_models
from moth.policy.engine import PolicyEngine, PolicyError
from moth.server.services import NotFound, Services


class LoadIn(BaseModel):
    id: str
    device: str = "auto"


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None
    project_id: int | None = None
    params: dict[str, Any] | None = None


class PolicyTestIn(BaseModel):
    text: str


HISTORY_MESSAGES = 12


def register(app: FastAPI, svc: Services, deps) -> None:
    local = LocalInference(svc.paths.models)
    svc.extras["local_inference"] = local
    policy_lock = threading.Lock()
    active: dict[int, threading.Event] = {}

    def policy() -> PolicyEngine:
        return PolicyEngine.load(svc.paths.policy)

    # ---- models -------------------------------------------------------------
    @app.get("/api/models", dependencies=deps)
    def models():
        return list_models(svc.paths.models)

    @app.get("/api/model/status", dependencies=deps)
    def model_status():
        return local.status()

    @app.post("/api/models/load", dependencies=deps)
    def load(body: LoadIn):
        try:
            st = local.load(body.id, body.device)
        except FileNotFoundError:
            raise NotFound(f"model {body.id} not found") from None
        except Exception as e:
            raise HTTPException(400, f"could not load model: {e}") from None
        svc.db.set_setting("active_model", {"id": body.id, "device": body.device})
        svc.db.log_activity("model", f"Loaded model {st['name']} on {st['device']}")
        svc.bus.publish("model", {"status": st})
        return st

    @app.post("/api/models/unload", dependencies=deps)
    def unload():
        local.unload()
        svc.db.set_setting("active_model", None)
        svc.bus.publish("model", {"status": local.status()})
        return local.status()

    @app.delete("/api/models/{model_id}", dependencies=deps)
    def remove(model_id: str):
        if local.model_id == model_id:
            local.unload()
            svc.bus.publish("model", {"status": local.status()})
        try:
            delete_model(svc.paths.models, model_id)
        except FileNotFoundError:
            raise NotFound(f"model {model_id} not found") from None
        return {"ok": True}

    # Restore the previously active model (failures are reported, not fatal).
    active_model = svc.db.get_setting("active_model")
    if active_model:
        try:
            local.load(active_model["id"], active_model.get("device", "auto"))
        except Exception as e:
            svc.db.log_activity("model", f"Could not reload model {active_model['id']}: {e}")

    # ---- conversations ------------------------------------------------------
    @app.get("/api/conversations", dependencies=deps)
    def conversations(project_id: int | None = None):
        if project_id is None:
            return svc.db.query("SELECT * FROM conversations ORDER BY id DESC LIMIT 100")
        return svc.db.query("SELECT * FROM conversations WHERE project_id=? ORDER BY id DESC LIMIT 100", (project_id,))

    @app.get("/api/conversations/{cid}/messages", dependencies=deps)
    def messages(cid: int):
        rows = svc.db.query("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
        for r in rows:
            r["meta"] = json.loads(r["meta"]) if r["meta"] else None
        return rows

    @app.delete("/api/conversations/{cid}", dependencies=deps)
    def delete_conversation(cid: int):
        svc.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
        return {"ok": True}

    @app.post("/api/chat", dependencies=deps)
    def chat(body: ChatIn):
        pol = policy()
        decision = pol.check_input(body.message)
        if not decision.allowed:
            raise HTTPException(422, decision.message)
        if not local.available():
            raise HTTPException(409, "No MOTH model is loaded. Train a model and load it under Models first.")
        cid = body.conversation_id
        now = time.time()
        if cid is None:
            title = body.message.strip().splitlines()[0][:60] or "New conversation"
            cid = int(svc.db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (?,?,?)",
                                     (body.project_id, title, now)).lastrowid)
        elif not svc.db.one("SELECT id FROM conversations WHERE id=?", (cid,)):
            raise NotFound("conversation not found")
        if cid in active:
            raise HTTPException(409, "MOTH is still answering in this conversation")
        history = svc.db.query("SELECT role, content FROM messages WHERE conversation_id=? AND role IN "
                               "('user','assistant') ORDER BY id DESC LIMIT ?", (cid, HISTORY_MESSAGES))[::-1]
        svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                       (cid, "user", body.message, None, now))
        msgs = [Message("system", pol.system_prompt)] + [Message(h["role"], h["content"]) for h in history]
        msgs.append(Message("user", body.message))
        params = GenerationParams.from_dict({**pol.generation_defaults, **(body.params or {})})
        cancel = threading.Event()
        active[cid] = cancel
        msg_key = uuid.uuid4().hex[:10]
        has_output_rules = any(r.enabled and r.applies_to in ("output", "both") for r in pol.rules)

        def work() -> None:
            text = ""
            try:
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "start",
                                         "model": local.status().get("name")})

                def on_text(piece: str) -> None:
                    nonlocal text
                    text += piece
                    if has_output_rules:
                        d = pol.filter_output(text)
                        if not d.allowed:
                            cancel.set()
                        svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "replace",
                                                 "text": d.text if d.allowed else d.message})
                    else:
                        svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "token",
                                                 "text": piece})

                stats = local.chat(msgs, params, on_text, cancel)
                final = pol.filter_output(text)
                content = final.text if final.allowed else final.message
                meta = {"model": local.status().get("name"), "tokens": stats.generated_tokens,
                        "tokens_per_sec": round(stats.tokens_per_sec, 1), "stop_reason": stats.stop_reason,
                        "policy": final.triggered or None}
                svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                               (cid, "assistant", content, json.dumps(meta), time.time()))
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "done",
                                         "text": content, "meta": meta})
            except NoModelLoaded as e:
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "error", "error": str(e)})
            except Exception as e:
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "error",
                                         "error": f"{type(e).__name__}: {e}"})
            finally:
                active.pop(cid, None)

        threading.Thread(target=work, daemon=True, name=f"chat-{cid}").start()
        return {"conversation_id": cid, "message_key": msg_key}

    @app.post("/api/chat/{cid}/cancel", dependencies=deps)
    def cancel_chat(cid: int):
        ev = active.get(cid)
        if ev:
            ev.set()
        return {"cancelled": bool(ev)}

    # ---- owner policy ----------------------------------------------------------
    @app.get("/api/policy", dependencies=deps)
    def get_policy():
        return policy().data

    @app.put("/api/policy", dependencies=deps)
    def put_policy(data: dict[str, Any]):
        with policy_lock:
            try:
                engine = PolicyEngine(data)
            except PolicyError as e:
                raise HTTPException(422, str(e)) from None
            engine.save(svc.paths.policy)
        svc.db.log_activity("policy", "Owner content policy updated")
        return engine.data

    @app.post("/api/policy/reset", dependencies=deps)
    def reset_policy():
        engine = PolicyEngine()
        engine.save(svc.paths.policy)
        return engine.data

    @app.post("/api/policy/test", dependencies=deps)
    def test_policy(body: PolicyTestIn):
        pol = policy()
        i, o = pol.check_input(body.text), pol.filter_output(body.text)
        return {"input": i.__dict__, "output": o.__dict__}
