"""Hybrid inference routing: Local, MOTH Cloud or Automatic.

* **local** — always on this PC.
* **cloud** — MOTH Cloud endpoint (requires the user's consent).
* **auto** — local when a model is loaded, otherwise MOTH Cloud if it is
  configured, reachable and consented to.

Before anything is sent remotely: the user must have granted consent, project
data (agent tasks) needs its own explicit permission, and credentials are
redacted from every message.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from moth.inference.cloud import CloudUnavailable, MothCloudClient
from moth.inference.local import LocalAgentLLM, LocalInference, NoModelLoaded
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams, GenerationStats
from moth.security.redaction import redact

MODES = ("local", "cloud", "auto")


class RemoteConsentRequired(PermissionError):
    pass


@dataclass
class InferenceSettings:
    mode: str = "local"
    cloud_url: str = ""
    cloud_api_key: str = ""
    consent_remote_chat: bool = False
    consent_remote_project_data: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "InferenceSettings":
        d = d or {}
        s = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        if s.mode not in MODES:
            s.mode = "local"
        return s

    def public(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["cloud_api_key"] = "********" if self.cloud_api_key else ""
        return d


class InferenceRouter:
    def __init__(self, local: LocalInference, load_settings: Callable[[], InferenceSettings],
                 client_factory: Callable[[InferenceSettings], MothCloudClient] | None = None):
        self.local = local
        self.load_settings = load_settings
        self.client_factory = client_factory or (lambda s: MothCloudClient(s.cloud_url, s.cloud_api_key or None))

    def cloud(self, s: InferenceSettings | None = None) -> MothCloudClient:
        s = s or self.load_settings()
        if not s.cloud_url:
            raise CloudUnavailable("No MOTH Cloud endpoint is configured. MOTH-operated servers are not available yet.")
        return self.client_factory(s)

    def status(self) -> dict[str, Any]:
        s = self.load_settings()
        out: dict[str, Any] = {"mode": s.mode, "local": self.local.status(), "cloud": {"configured": bool(s.cloud_url)}}
        if s.cloud_url:
            try:
                h = self.cloud(s).health()
                out["cloud"].update({"reachable": True, "models": h["models"]})
            except CloudUnavailable as e:
                out["cloud"].update({"reachable": False, "error": str(e)})
        return out

    def select(self, project_data: bool) -> str:
        """Return 'local' or 'cloud', or raise an explanatory error."""
        s = self.load_settings()
        if s.mode == "local" or (s.mode == "auto" and self.local.available()):
            if not self.local.available():
                raise NoModelLoaded("No MOTH model is loaded locally. Load one under Models, or choose MOTH Cloud.")
            return "local"
        if not s.cloud_url:
            raise CloudUnavailable("No local model is loaded and no MOTH Cloud endpoint is configured "
                                   "(MOTH-operated servers are not available yet).")
        if not s.consent_remote_chat:
            raise RemoteConsentRequired("Sending messages to MOTH Cloud needs your permission (Models → Inference).")
        if project_data and not s.consent_remote_project_data:
            raise RemoteConsentRequired("Agent tasks send project files to MOTH Cloud. Allow project data in "
                                        "Models → Inference first, or load a local model.")
        return "cloud"

    @staticmethod
    def _sanitize(messages: list[Message]) -> list[Message]:
        return [Message(m.role, redact(m.content)[0], m.allow_special) for m in messages]

    def chat(self, messages: list[Message], params: GenerationParams, on_text: Callable[[str], None],
             cancel: threading.Event | None = None, project_data: bool = False) -> tuple[str, GenerationStats]:
        target = self.select(project_data)
        if target == "local":
            return "local", self.local.chat(messages, params, on_text, cancel)
        return "cloud", self.cloud().chat(self._sanitize(messages), params, on_text, cancel)

    def describe(self, target: str) -> str:
        if target == "local":
            return self.local.status().get("name", "local")
        try:
            return f"{self.cloud().default_model()['name']} (MOTH Cloud)"
        except CloudUnavailable:
            return "MOTH Cloud"

    def agent_llm(self):
        if self.select(project_data=True) == "local":
            return LocalAgentLLM(self.local)
        return CloudAgentLLM(self)


class CloudAgentLLM:
    """Agent adapter for MOTH Cloud (token counts approximated by bytes/3 for budgeting)."""

    def __init__(self, router: InferenceRouter):
        self.router = router
        m = router.cloud().default_model()
        self.name = f"{m['name']} (cloud)"
        self.context_length = int(m.get("context_length") or 2048)

    def count_tokens(self, messages: list[Message]) -> int:
        return sum(len(m.content.encode()) for m in messages) // 3 + 4 * len(messages)

    def generate(self, messages: list[Message], params: GenerationParams, cancel: threading.Event) -> str:
        parts: list[str] = []
        self.router.chat(messages, params, parts.append, cancel, project_data=True)
        return "".join(parts)
