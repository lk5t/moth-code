"""Owner model tools (list/delete local training outputs) and cloud chat routes."""

from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from moth.model.chat_format import Message
from moth.model.generation import GenerationParams
from moth.model.registry import delete_model, list_models
from moth.server.services import NotFound, Services


class ChatIn(BaseModel):
    message: str
    conversation_id: int | None = None
    project_id: int | None = None
    params: dict[str, Any] | None = None


class PolicyTestIn(BaseModel):
    text: str


HISTORY_MESSAGES = 12


def register(app: FastAPI, svc: Services, deps) -> None:
    active: dict[int, threading.Event] = {}

    # ---- models -------------------------------------------------------------
    @app.get("/api/models", dependencies=deps)
    def models():
        return list_models(svc.paths.models)

    @app.delete("/api/models/{model_id}", dependencies=deps)
    def remove(model_id: str):
        try:
            delete_model(svc.paths.models, model_id)
        except FileNotFoundError:
            raise NotFound(f"model {model_id} not found") from None
        return {"ok": True}

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
        """Chat with the official MOTH model on MOTH Cloud (cloud-only; metered by the MOTH Server).

        The Owner's content policy and persona are applied server-side, not here."""
        from moth.inference.router import NotSignedIn

        router = svc.extras["inference_router"]
        try:
            router.endpoint()
        except NotSignedIn as e:
            raise HTTPException(401, str(e)) from None
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
        msgs = [Message(h["role"], h["content"]) for h in history] + [Message("user", body.message)]
        params = GenerationParams.from_dict({"max_new_tokens": 256, "temperature": 0.7, **(body.params or {})})
        cancel = threading.Event()
        active[cid] = cancel
        msg_key = uuid.uuid4().hex[:10]

        def work() -> None:
            text = ""
            model_name = "MOTH Cloud"
            try:
                model_name = router.describe()
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "start",
                                         "model": model_name})

                def on_text(piece: str) -> None:
                    nonlocal text
                    text += piece
                    svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "token",
                                             "text": piece})

                stats = router.chat(msgs, params, on_text, cancel)
                meta = {"model": model_name, "via": "cloud", "tokens": stats.generated_tokens,
                        "tokens_per_sec": round(stats.tokens_per_sec, 1), "stop_reason": stats.stop_reason}
                svc.db.execute("INSERT INTO messages(conversation_id, role, content, meta, ts) VALUES (?,?,?,?,?)",
                               (cid, "assistant", text, json.dumps(meta), time.time()))
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "done",
                                         "text": text, "meta": meta})
            except Exception as e:  # cloud outage, limits, sign-in: reported, never crashes the app
                svc.bus.publish("chat", {"conversation_id": cid, "message_key": msg_key, "kind": "error",
                                         "error": str(e) or type(e).__name__})
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
