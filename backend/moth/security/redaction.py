"""Credential redaction (operational security, always on).

Applied to anything that could leave the machine (remote inference requests,
community contributions) and to text shown in logs. Independent of the owner
content policy.
"""

from __future__ import annotations

import re

SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    ("aws_access_key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{40,})\b")),
    ("slack_token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe_key", re.compile(r"\b(sk|rk)_(live|test)_[0-9A-Za-z]{16,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("generic_secret_assignment", re.compile(
        r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|API_?KEY|ACCESS_?KEY)[A-Z0-9_]*)\s*[:=]\s*"
        r"(['\"]?)([^\s'\"]{8,})\2")),
]


def redact(text: str) -> tuple[str, list[str]]:
    found: list[str] = []

    def sub(name: str):
        def inner(m: re.Match) -> str:
            found.append(name)
            if name == "generic_secret_assignment":
                return f"{m.group(1)}={m.group(2)}[REDACTED]{m.group(2)}"
            return f"[REDACTED:{name}]"
        return inner

    for name, rx in SECRET_PATTERNS:
        if _could_match(name, text):  # 0.9.1: skip patterns whose required literal is absent (same result)
            text = rx.sub(sub(name), text)
    return text, found


_GENERIC_WORDS = ("secret", "password", "passwd", "token", "api", "access")


def _could_match(name: str, text: str) -> bool:
    """A cheap necessary condition for each pattern: every match contains these literals."""
    if name == "private_key":
        return "PRIVATE KEY-----" in text
    if name == "aws_access_key":
        return "AKIA" in text or "ASIA" in text
    if name == "github_token":
        return "gh" in text or "github_pat_" in text
    if name == "slack_token":
        return "xox" in text
    if name == "google_api_key":
        return "AIza" in text
    if name == "stripe_key":
        return "_live_" in text or "_test_" in text
    if name == "jwt":
        return "eyJ" in text
    if name == "generic_secret_assignment":
        if ":" not in text and "=" not in text:
            return False
        low = text.lower()
        return any(w in low for w in _GENERIC_WORDS)
    return True
