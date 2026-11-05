"""Reference MOTH Cloud server (protocol ``moth-cloud/1``).

Serves exported MOTH models over HTTP. Run with::

    moth cloud-serve --model ~/.moth/models/my-model --port 8800 [--api-key KEY]
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from moth.inference.cloud import PROTOCOL
from moth.inference.local import LocalInference
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams


def create_cloud_app(engine: LocalInference, api_key: str | None = None) -> FastAPI:
    app = FastAPI(title="MOTH Cloud")

    def check(request: Request) -> None:
        if api_key and not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {api_key}"):
            raise HTTPException(401, "invalid API key")

    @app.get("/v1/health")
    def health(request: Request):
        check(request)
        models = []
        if engine.manifest:
            m = engine.manifest
            models.append({k: m.get(k) for k in ("name", "architecture", "params", "context_length", "sha256")})
        return {"service": "moth-cloud", "protocol": PROTOCOL, "models": models}

    @app.post("/v1/chat")
    def chat(request: Request, body: dict):
        check(request)
        if engine.manifest is None or body.get("model") != engine.manifest["name"]:
            raise HTTPException(404, "model not available")
        messages = [Message(m["role"], m["content"], bool(m.get("trusted")) and m["role"] == "assistant")
                    for m in body.get("messages", [])]
        params = GenerationParams.from_dict(body.get("params"))
        cancel = threading.Event()

        def stream():
            chunks: list[str] = []
            try:
                stats = engine.chat(messages, params, chunks.append, cancel)
                for c in chunks:
                    yield json.dumps({"text": c}) + "\n"
                yield json.dumps({"done": True, "stats": {
                    "prompt_tokens": stats.prompt_tokens, "generated_tokens": stats.generated_tokens,
                    "seconds": stats.seconds, "stop_reason": stats.stop_reason}}) + "\n"
            except Exception as e:
                yield json.dumps({"error": f"{type(e).__name__}: {e}"}) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    return app


def main(argv: list[str] | None = None) -> None:
    import uvicorn
    from pathlib import Path

    p = argparse.ArgumentParser(prog="moth cloud-serve")
    p.add_argument("--model", required=True, help="exported model directory")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8800)
    p.add_argument("--device", default="auto")
    p.add_argument("--api-key", default=None)
    a = p.parse_args(argv)
    model_dir = Path(a.model).resolve()
    engine = LocalInference(model_dir.parent)
    engine.load(model_dir.name, a.device)
    uvicorn.run(create_cloud_app(engine, a.api_key), host=a.host, port=a.port)
