"""MOTH Cloud: client for remote inference on MOTH-operated servers.

No MOTH Cloud service is operated yet, so **no endpoint is configured by
default** and nothing pretends one exists. The protocol below is implemented
by :mod:`moth.inference.cloud_server`, which anyone can run to host their own
MOTH model (and which MOTH-operated servers will use).

Protocol ``moth-cloud/1``:

* ``GET  /v1/health`` → ``{"service": "moth-cloud", "protocol": 1, "models": [manifest, ...]}``
* ``POST /v1/chat``   → body ``{"model", "messages": [{"role","content"}], "params"}``;
  response is NDJSON lines ``{"text": "..."}`` … ``{"done": true, "stats": {...}}``
  or ``{"error": "..."}``.

The client refuses servers that do not identify as ``moth-cloud`` or whose
models are not MOTH architecture models.
"""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any, Callable

import httpx

from moth.model.chat_format import Message
from moth.model.generation import GenerationParams, GenerationStats

PROTOCOL = 1
MOTH_ARCHITECTURES = {"moth-decoder-v1"}


class CloudUnavailable(RuntimeError):
    """``reason``: unreachable | not_moth | no_model_deployed | inference_disabled | …"""

    reason = "unreachable"


def _explain(e: Exception) -> str:
    """A readable reason for a failed request (the address, TLS, a proxy or tunnel, or the server)."""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code in (502, 503, 504, 520, 521, 522, 523, 524, 530):
            return (f"MOTH Cloud's address answered with HTTP {code}: the proxy or tunnel in front of the server "
                    "can't reach it right now. MOTH Code keeps retrying.")
        return f"MOTH Cloud answered with HTTP {code}."
    if isinstance(e, httpx.ConnectError) and "SSL" in str(e).upper():
        return "MOTH Cloud's HTTPS certificate could not be verified for this address."
    if isinstance(e, httpx.TimeoutException):
        return "MOTH Cloud did not answer in time. MOTH Code keeps retrying."
    return f"MOTH Cloud endpoint unreachable: {e}"


class MothCloudClient:
    name = "cloud"

    def __init__(self, base_url: str, api_key: str | None = None, http: httpx.Client | None = None,
                 timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.http = http or httpx.Client(timeout=timeout)
        self._health: dict[str, Any] | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _url(self, path: str) -> str:
        return path if not self.base_url else self.base_url + path

    def health(self) -> dict[str, Any]:
        if not self.base_url and not hasattr(self.http, "app"):
            raise CloudUnavailable("No MOTH Cloud endpoint is configured. MOTH-operated servers are not available yet.")
        try:
            r = self.http.get(self._url("/v1/health"), headers=self._headers())
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            err = CloudUnavailable(_explain(e))
            err.reason = "unreachable"
            raise err from None
        if data.get("service") != "moth-cloud" or data.get("protocol") != PROTOCOL:
            err = CloudUnavailable("endpoint is not a MOTH Cloud server (protocol mismatch)")
            err.reason = "not_moth"
            raise err
        bad = [m.get("name") for m in data.get("models", []) if m.get("architecture") not in MOTH_ARCHITECTURES]
        if bad:
            raise CloudUnavailable(f"server offers non-MOTH models {bad}; refusing to use it")
        if not data.get("models"):
            err = CloudUnavailable(data.get("message") or (
                "MOTH Cloud is connected but has no model serving yet: either no model is deployed or inference is "
                "turned off. The Owner fixes this in Owner Dashboard → AI models and → Policy & flags."))
            err.reason = data.get("status") or "no_model_deployed"
            raise err
        self._health = data
        return data

    def default_model(self) -> dict[str, Any]:
        health = self._health or self.health()
        return health["models"][0]

    def chat(self, messages: list[Message], params: GenerationParams, on_text: Callable[[str], None],
             cancel_event: threading.Event | None = None, model: str | None = None) -> GenerationStats:
        body = {"model": model or self.default_model()["name"],
                "messages": [{"role": m.role, "content": m.content, "trusted": m.allow_special} for m in messages],
                "params": {k: v for k, v in params.__dict__.items()}}
        stats = GenerationStats()
        headers = {**self._headers(), "X-Request-Id": uuid.uuid4().hex}  # one charge per request, never reused
        try:
            with self.http.stream("POST", self._url("/v1/chat"), json=body, headers=headers) as r:
                if r.status_code >= 400:
                    r.read()
                    try:
                        detail = r.json().get("detail")
                    except ValueError:
                        detail = None
                    raise CloudUnavailable(detail or f"MOTH Cloud returned HTTP {r.status_code}")
                for line in r.iter_lines():
                    if cancel_event is not None and cancel_event.is_set():
                        stats.stop_reason = "cancelled"
                        break
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if "error" in msg:
                        raise CloudUnavailable(msg["error"])
                    if "text" in msg:
                        on_text(msg["text"])
                    if msg.get("done"):
                        s = msg.get("stats", {})
                        stats.prompt_tokens = s.get("prompt_tokens", 0)
                        stats.generated_tokens = s.get("generated_tokens", 0)
                        stats.seconds = s.get("seconds", 0.0)
                        stats.stop_reason = s.get("stop_reason", "")
        except httpx.HTTPError as e:
            raise CloudUnavailable(f"MOTH Cloud request failed: {e}") from None
        return stats
