"""MOTH Cloud routing (cloud-only).

MOTH Code is a cloud service: every chat and agent request goes to the official MOTH model on
MOTH Cloud through the signed-in account's MOTH Server, where it is authenticated and metered.
Local model weights are not used for inference by the desktop app.

Before anything leaves this computer, credentials are redacted. Agent tasks send project file
contents, so each workspace needs the user's explicit consent first.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from moth.inference.cloud import CloudUnavailable, MothCloudClient
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams, GenerationStats
from moth.security.redaction import redact


class NotSignedIn(PermissionError):
    pass


class WorkspaceConsentRequired(PermissionError):
    def __init__(self, project_id: int | None):
        super().__init__("MOTH needs your permission to send files from this workspace to MOTH Cloud.")
        self.project_id = project_id


# Kept for compatibility with earlier imports.
RemoteConsentRequired = WorkspaceConsentRequired


@dataclass
class InferenceSettings:
    """Developer override: an explicit moth-cloud endpoint (e.g. a self-hosted test server)."""

    cloud_url: str = ""
    cloud_api_key: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "InferenceSettings":
        d = d or {}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def public(self) -> dict[str, Any]:
        return {"cloud_url": self.cloud_url, "cloud_api_key": "********" if self.cloud_api_key else ""}


class InferenceRouter:
    def __init__(self, load_settings: Callable[[], InferenceSettings],
                 account: Callable[[], dict | None],
                 consent: Callable[[int | None], bool] = lambda pid: False,
                 client_factory: Callable[[str, str | None], MothCloudClient] | None = None):
        self._load_settings = load_settings
        self.account = account
        self.consent = consent
        self.client_factory = client_factory or (lambda url, key: MothCloudClient(url, key))

    def endpoint(self) -> tuple[str, str | None]:
        s = self._load_settings()
        if s.cloud_url:
            return s.cloud_url, s.cloud_api_key or None
        acct = self.account() or {}
        if not acct.get("token") or not acct.get("server_url"):
            raise NotSignedIn("Sign in to your MOTH account to use MOTH.")
        return acct["server_url"].rstrip("/") + "/cloud", acct["token"]

    def cloud(self) -> MothCloudClient:
        return self.client_factory(*self.endpoint())

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {"signed_in": bool((self.account() or {}).get("token"))}
        try:
            h = self.cloud().health()
            out.update({"reachable": True, "available": True, "model": h["models"][0]})
        except NotSignedIn as e:
            out.update({"reachable": None, "available": False, "error": str(e)})
        except CloudUnavailable as e:
            reason = getattr(e, "reason", "unreachable")
            out.update({"reachable": reason != "unreachable", "available": False, "error": str(e), "reason": reason})
        return out

    @staticmethod
    def _sanitize(messages: list[Message]) -> list[Message]:
        return [Message(m.role, redact(m.content)[0], m.allow_special) for m in messages]

    def chat(self, messages: list[Message], params: GenerationParams, on_text: Callable[[str], None],
             cancel: threading.Event | None = None, project_id: int | None = None,
             project_data: bool = False) -> GenerationStats:
        if project_data and not self.consent(project_id):
            raise WorkspaceConsentRequired(project_id)
        return self.cloud().chat(self._sanitize(messages), params, on_text, cancel)

    def describe(self) -> str:
        try:
            return f"{self.cloud().default_model()['name']} (MOTH Cloud)"
        except (CloudUnavailable, NotSignedIn):
            return "MOTH Cloud"

    def agent_llm(self, project_id: int | None) -> "CloudAgentLLM":
        self.endpoint()  # must be signed in before anything else
        if not self.consent(project_id):
            raise WorkspaceConsentRequired(project_id)
        return CloudAgentLLM(self, project_id)


class CloudAgentLLM:
    """Agent adapter for MOTH Cloud (token budget approximated as bytes/3)."""

    def __init__(self, router: InferenceRouter, project_id: int | None):
        self.router = router
        self.endpoint = router.endpoint()
        self.project_id = project_id
        m = router.cloud().default_model()
        self.name = f"{m['name']} (MOTH Cloud)"
        self.context_length = int(m.get("context_length") or 2048)

    def count_tokens(self, messages: list[Message]) -> int:
        return sum(len(m.content.encode()) for m in messages) // 3 + 4 * len(messages)

    def generate(self, messages: list[Message], params: GenerationParams, cancel: threading.Event) -> str:
        if self.router.endpoint() != self.endpoint:
            raise NotSignedIn("The account changed. Start the coding task again in the selected account.")
        parts: list[str] = []
        self.router.chat(messages, params, parts.append, cancel, project_id=self.project_id, project_data=True)
        return "".join(parts)
