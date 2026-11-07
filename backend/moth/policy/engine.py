"""Owner-controlled conversational content policy.

The project owner decides how MOTH behaves in conversation. MOTH ships with
**no topic restrictions** — the default rule list is empty. Owners add rules
in ``policy.json`` (editable in Settings → Content policy):

    {
      "id": "no-profanity",
      "description": "Mask profanity in responses",
      "applies_to": "output",           # input | output | both
      "match": {"type": "keywords", "patterns": ["darn"], "case_sensitive": false},
      "action": "redact",               # block | warn | redact
      "message": "Response edited by the owner policy."
    }

This module deliberately does NOT handle operational security (workspace
boundaries, approvals, credential protection). Those live in
:mod:`moth.security` and cannot be switched off by editing content policy.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_POLICY: dict[str, Any] = {
    "version": 1,
    "assistant_name": "MOTH",
    "system_prompt": (
        "You are MOTH, a coding assistant running locally inside MOTH Code. "
        "Answer clearly and concisely. When you are unsure, say so."
    ),
    "generation_defaults": {
        "temperature": 0.7, "top_k": 50, "top_p": 0.95, "repetition_penalty": 1.1, "max_new_tokens": 256,
    },
    "content_rules": [],
}

VALID_ACTIONS = {"block", "warn", "redact"}
VALID_SCOPES = {"input", "output", "both"}
VALID_MATCH = {"keywords", "regex"}


class PolicyError(ValueError):
    pass


@dataclass
class Rule:
    id: str
    applies_to: str
    action: str
    match_type: str
    patterns: list[str]
    case_sensitive: bool = False
    description: str = ""
    message: str = ""
    enabled: bool = True
    _compiled: list[re.Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        if self.match_type == "keywords":
            self._compiled = [re.compile(r"\b" + re.escape(p) + r"\b", flags) for p in self.patterns if p]
        else:
            self._compiled = [re.compile(p, flags) for p in self.patterns if p]

    def find(self, text: str) -> list[re.Match]:
        return [m for rx in self._compiled for m in rx.finditer(text)]


@dataclass
class PolicyDecision:
    allowed: bool
    text: str
    triggered: list[dict[str, str]] = field(default_factory=list)
    message: str = ""


def validate_policy(data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise PolicyError("policy must be a JSON object")
    merged = copy.deepcopy(DEFAULT_POLICY)
    merged.update({k: v for k, v in data.items() if k in DEFAULT_POLICY})
    if not isinstance(merged["system_prompt"], str):
        raise PolicyError("system_prompt must be a string")
    gd = merged["generation_defaults"]
    if not isinstance(gd, dict):
        raise PolicyError("generation_defaults must be an object")
    for k in ("temperature", "top_p", "repetition_penalty"):
        if k in gd and not isinstance(gd[k], (int, float)):
            raise PolicyError(f"generation_defaults.{k} must be a number")
    seen = set()
    for i, r in enumerate(merged["content_rules"]):
        where = f"content_rules[{i}]"
        if not isinstance(r, dict) or not r.get("id"):
            raise PolicyError(f"{where} needs an id")
        if r["id"] in seen:
            raise PolicyError(f"duplicate rule id {r['id']!r}")
        seen.add(r["id"])
        if r.get("action") not in VALID_ACTIONS:
            raise PolicyError(f"{where}.action must be one of {sorted(VALID_ACTIONS)}")
        if r.get("applies_to", "both") not in VALID_SCOPES:
            raise PolicyError(f"{where}.applies_to must be one of {sorted(VALID_SCOPES)}")
        m = r.get("match") or {}
        if m.get("type") not in VALID_MATCH or not isinstance(m.get("patterns"), list):
            raise PolicyError(f"{where}.match needs type (keywords|regex) and a patterns list")
        if m["type"] == "regex":
            for p in m["patterns"]:
                try:
                    re.compile(p)
                except re.error as e:
                    raise PolicyError(f"{where}: invalid regex {p!r}: {e}") from None
    return merged


class PolicyEngine:
    def __init__(self, data: dict[str, Any] | None = None):
        self.data = validate_policy(data or {})
        self.rules = [
            Rule(id=r["id"], applies_to=r.get("applies_to", "both"), action=r["action"],
                 match_type=r["match"]["type"], patterns=list(r["match"]["patterns"]),
                 case_sensitive=bool(r["match"].get("case_sensitive", False)),
                 description=r.get("description", ""), message=r.get("message", ""),
                 enabled=r.get("enabled", True))
            for r in self.data["content_rules"]
        ]

    @classmethod
    def load(cls, path: Path) -> "PolicyEngine":
        if not path.exists():
            return cls()
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(path)

    @property
    def system_prompt(self) -> str:
        return self.data["system_prompt"]

    @property
    def generation_defaults(self) -> dict[str, Any]:
        return dict(self.data["generation_defaults"])

    def _apply(self, text: str, scope: str) -> PolicyDecision:
        decision = PolicyDecision(True, text)
        for rule in self.rules:
            if not rule.enabled or rule.applies_to not in (scope, "both"):
                continue
            matches = rule.find(decision.text)
            if not matches:
                continue
            decision.triggered.append({"id": rule.id, "action": rule.action})
            if rule.action == "block":
                decision.allowed = False
                decision.message = rule.message or f"Blocked by owner policy rule '{rule.id}'."
                return decision
            if rule.action == "redact":
                for rx in rule._compiled:
                    decision.text = rx.sub(lambda m: "█" * len(m.group(0)), decision.text)
                decision.message = rule.message or decision.message
            if rule.action == "warn":
                decision.message = rule.message or f"Owner policy note: rule '{rule.id}' matched."
        return decision

    def check_input(self, text: str) -> PolicyDecision:
        return self._apply(text, "input")

    def filter_output(self, text: str) -> PolicyDecision:
        return self._apply(text, "output")


# A small baseline for public serving: refuses requests that clearly seek serious harm. Owners keep full
# control (MOTH Cloud has an Owner toggle); the desktop app's local policy is unchanged.
SAFETY_BASELINE_MESSAGE = "MOTH can't help with that request because it could cause serious harm."
SAFETY_BASELINE_RULES: list[dict[str, Any]] = [
    {"id": "baseline-weapons", "description": "Instructions for explosives or illegal weapons", "applies_to": "input",
     "action": "block", "message": SAFETY_BASELINE_MESSAGE,
     "match": {"type": "regex", "patterns": [
         r"\b(make|build|assemble|construct|instructions?|steps?|how to)\b.{0,60}\b(pipe ?bomb|bomb|explosive|ied|napalm|molotov)\b",
         r"\b(buy|get|obtain)\b.{0,40}\bguns?\b.{0,40}\b(illegal(ly)?|without (a )?background check)\b"]}},
    {"id": "baseline-malware", "description": "Writing malware or stealing credentials", "applies_to": "input",
     "action": "block", "message": SAFETY_BASELINE_MESSAGE,
     "match": {"type": "regex", "patterns": [
         r"\b(write|create|code|generate|build|make)\b.{0,60}\b(malware|ransomware|keylogger|trojan|botnet|virus)\b",
         r"\b(steal|exfiltrate|dump)\b.{0,40}\b(passwords?|credentials|cookies|card numbers?)\b",
         r"\bphishing\b.{0,60}\b(email|message|page|site)\b"]}},
    {"id": "baseline-drugs", "description": "Synthesising hard drugs", "applies_to": "input", "action": "block",
     "message": SAFETY_BASELINE_MESSAGE,
     "match": {"type": "regex", "patterns": [
         r"\b(make|cook|synthesi[sz]e|produce|manufacture)\b.{0,40}\b(meth(amphetamine)?|cocaine|heroin|fentanyl)\b"]}},
    {"id": "baseline-violence", "description": "Hurting, poisoning or threatening people", "applies_to": "input",
     "action": "block", "message": SAFETY_BASELINE_MESSAGE,
     "match": {"type": "regex", "patterns": [
         r"\b(poison|kill|murder|hurt)\b.{0,30}\b(someone|somebody|a person|my \w+|him|her|them)\b",
         r"\b(threaten|harass)\w*\b.{0,60}\b(family|coworker|neighbou?r|ex|her|him)\b"]}},
]


def with_safety_baseline(policy: dict[str, Any] | None) -> dict[str, Any]:
    """``policy`` plus the baseline rules (rules with the same id in ``policy`` take precedence)."""
    p = copy.deepcopy(policy or {})
    have = {r.get("id") for r in p.get("content_rules", [])}
    p["content_rules"] = list(p.get("content_rules", [])) + [r for r in SAFETY_BASELINE_RULES if r["id"] not in have]
    return p
