"""Permission decisions for agent and tool actions.

Rules (summarised):

* Every file operation must resolve inside an authorised workspace root.
  Paths outside it are denied unless the user explicitly approves.
* Reading/writing ordinary files inside the workspace is allowed.
* Deleting files, running destructive commands, publishing (``git push``,
  package uploads) and network-reaching commands require approval.
* Files that look like credentials (``.env``, private keys, cloud credential
  files) require approval to read and are never uploaded anywhere.
"""

from __future__ import annotations

import enum
import fnmatch
import re
import shlex
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePath
from typing import Any, Callable


class Decision(str, enum.Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class ActionKind(str, enum.Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    GIT = "git"
    PUBLISH = "publish"
    NETWORK = "network"
    REMOTE_INFERENCE = "remote_inference"


@dataclass
class PermissionResult:
    decision: Decision
    reason: str
    risk: str = "low"  # low | medium | high

    @property
    def allowed(self) -> bool:
        return self.decision == Decision.ALLOW


class PathOutsideWorkspace(PermissionError):
    pass


SECRET_PATTERNS = [
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "id_ecdsa*",
    "credentials", "credentials.json", "*.keystore", ".npmrc", ".pypirc", ".netrc", "secrets.*",
    "*.kdbx", "service-account*.json",
]
SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".azure", ".kube", ".docker"}


def is_secret_path(path: str | PurePath) -> bool:
    p = PurePath(path)
    name = p.name.lower()
    if name in {".env.example", ".env.sample", ".env.template"}:
        return False
    if any(part.lower() in SECRET_DIRS for part in p.parts):
        return True
    return any(fnmatch.fnmatch(name, pat) for pat in SECRET_PATTERNS)


# Commands considered destructive. Matched against a normalised, lowercase command line.
_DESTRUCTIVE = [
    r"(^|[;&|]\s*)(sudo\s+)?rm\s+(-[a-z]*r|-[a-z]*f|--recursive|--force)",
    r"(^|[;&|]\s*)rmdir\s",
    r"(^|[;&|]\s*)(del|erase)\s",
    r"(^|[;&|]\s*)rd\s+/s",
    r"remove-item\b.*-recurse",
    r"(^|[;&|]\s*)format(\.com)?\s+[a-z]:",
    r"\bmkfs(\.\w+)?\b",
    r"\bdd\s+.*of=",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[a-z]*f",
    r"\bgit\s+checkout\s+--\s",
    r"\bgit\s+push\b.*(--force|-f\b|--delete|\s:)",
    r"\bgit\s+branch\s+-d\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\breg\s+delete\b",
    r"\bdiskpart\b",
    r"\bchmod\s+-r\s+777\s+/",
    r":\(\)\s*\{\s*:\|:&\s*\};:",  # fork bomb
    r"\bdrop\s+(table|database)\b",
]
_PUBLISH = [
    r"\bgit\s+push\b",
    r"\bnpm\s+publish\b",
    r"\byarn\s+(npm\s+)?publish\b",
    r"\bpnpm\s+publish\b",
    r"\btwine\s+upload\b",
    r"\bcargo\s+publish\b",
    r"\bgh\s+(release|pr|repo)\s+create\b",
    r"\bdocker\s+push\b",
    r"\bpoetry\s+publish\b",
]
_NETWORK = [
    r"\b(curl|wget|invoke-webrequest|iwr|invoke-restmethod|irm)\b",
    r"\bscp\b",
    r"\brsync\b.*:",
    r"\bssh\b",
    r"\bftp\b",
]
_DESTRUCTIVE_RE = [re.compile(p) for p in _DESTRUCTIVE]
_PUBLISH_RE = [re.compile(p) for p in _PUBLISH]
_NETWORK_RE = [re.compile(p) for p in _NETWORK]


def classify_command(command: str) -> PermissionResult:
    norm = " ".join(command.strip().lower().split())
    if not norm:
        return PermissionResult(Decision.DENY, "empty command")
    for rx in _DESTRUCTIVE_RE:
        if rx.search(norm):
            return PermissionResult(Decision.ASK, f"destructive command (matches {rx.pattern!r})", "high")
    for rx in _PUBLISH_RE:
        if rx.search(norm):
            return PermissionResult(Decision.ASK, "publishes data outside this computer", "high")
    for rx in _NETWORK_RE:
        if rx.search(norm):
            return PermissionResult(Decision.ASK, "contacts the network", "medium")
    # Reading secret files through the shell (cat .env, type id_rsa ...)
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for tok in tokens[1:]:
        if is_secret_path(tok):
            return PermissionResult(Decision.ASK, f"touches a credentials file ({tok})", "high")
    return PermissionResult(Decision.ALLOW, "ordinary command inside workspace")


@dataclass
class Workspace:
    root: Path
    extra_allowed: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()
        self.extra_allowed = [Path(p).resolve() for p in self.extra_allowed]

    def contains(self, path: Path) -> bool:
        p = Path(path).resolve()
        return any(_is_relative_to(p, r) for r in (self.root, *self.extra_allowed))

    def resolve(self, rel: str | Path) -> Path:
        """Resolve a user/agent supplied path and enforce the boundary.

        Relative paths are interpreted relative to the workspace root. Symlinks
        are resolved so a link pointing outside the workspace is rejected.
        """
        candidate = Path(rel)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = candidate.resolve()
        if not self.contains(resolved):
            raise PathOutsideWorkspace(f"{rel} resolves outside the authorised workspace {self.root}")
        return resolved

    def relative(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()


def _is_relative_to(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass
class PermissionSettings:
    """User-adjustable autonomy level. Defaults are conservative."""

    auto_write: bool = True  # write/create files inside workspace without asking
    auto_execute: bool = True  # run ordinary (non-destructive) commands without asking
    auto_git_commit: bool = False  # local commits without asking

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "PermissionSettings":
        d = d or {}
        return cls(**{k: bool(v) for k, v in d.items() if k in cls.__dataclass_fields__})


class PermissionEngine:
    def __init__(self, settings: PermissionSettings | None = None):
        self.settings = settings or PermissionSettings()

    def check(self, kind: ActionKind, workspace: Workspace, target: str = "") -> PermissionResult:
        if kind in (ActionKind.READ, ActionKind.WRITE, ActionKind.DELETE):
            try:
                path = workspace.resolve(target)
            except PathOutsideWorkspace as e:
                return PermissionResult(Decision.DENY, str(e), "high")
            if is_secret_path(path):
                return PermissionResult(Decision.ASK, f"{target} looks like a credentials file", "high")
            if kind == ActionKind.READ:
                return PermissionResult(Decision.ALLOW, "read inside workspace")
            if kind == ActionKind.WRITE:
                if self.settings.auto_write:
                    return PermissionResult(Decision.ALLOW, "write inside workspace")
                return PermissionResult(Decision.ASK, "file writes require approval (settings)", "medium")
            return PermissionResult(Decision.ASK, "deleting files requires approval", "high")
        if kind == ActionKind.EXECUTE:
            result = classify_command(target)
            if result.decision == Decision.ALLOW and not self.settings.auto_execute:
                return PermissionResult(Decision.ASK, "command execution requires approval (settings)", "medium")
            return result
        if kind == ActionKind.GIT:
            if self.settings.auto_git_commit:
                return PermissionResult(Decision.ALLOW, "local git operation")
            return PermissionResult(Decision.ASK, "git commits require approval (settings)", "medium")
        if kind in (ActionKind.PUBLISH, ActionKind.NETWORK, ActionKind.REMOTE_INFERENCE):
            return PermissionResult(Decision.ASK, f"{kind.value} sends data off this computer", "high")
        return PermissionResult(Decision.DENY, f"unknown action {kind}")


@dataclass
class ApprovalRequest:
    id: str
    kind: str
    target: str
    reason: str
    risk: str
    context: dict[str, Any]
    created_at: float
    status: str = "pending"  # pending | approved | denied | expired
    _event: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


class ApprovalBroker:
    """Blocks a worker thread until the user approves/denies an action in the UI."""

    def __init__(self, notify: Callable[[ApprovalRequest], None] | None = None):
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._notify = notify

    def request(self, kind: str, target: str, reason: str, risk: str = "medium",
                context: dict[str, Any] | None = None, timeout: float = 600.0,
                cancel_event: threading.Event | None = None) -> bool:
        req = ApprovalRequest(uuid.uuid4().hex, kind, target, reason, risk, context or {}, time.time())
        with self._lock:
            self._pending[req.id] = req
        if self._notify:
            self._notify(req)
        deadline = time.time() + timeout
        while not req._event.wait(0.1):
            if (cancel_event and cancel_event.is_set()) or time.time() > deadline:
                req.status = "expired"
                break
        with self._lock:
            self._pending.pop(req.id, None)
        return req.status == "approved"

    def resolve(self, request_id: str, approved: bool) -> bool:
        with self._lock:
            req = self._pending.get(request_id)
        if not req:
            return False
        req.status = "approved" if approved else "denied"
        req._event.set()
        return True

    def pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r.public() for r in self._pending.values()]
