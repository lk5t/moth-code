"""Prompt construction and output parsing for the agent loop.

Format (all produced by MOTH itself):

    <|assistant|>thinking text<|tool_call|>{"tool": "read_file", "args": {"path": "a.py"}}<|end|>
    <|tool_result|>OK\n...file contents...<|end|>
    <|assistant|>...<|tool_call|>{"tool": "finish", "args": {"summary": "..."}}<|end|>

Tool results are inserted by MOTH Code and encoded without special tokens, so
file contents can never forge control tokens.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from moth.agent.tools import TOOLS
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams

TOOL_CALL = "<|tool_call|>"
CONTROL_TOOLS = {
    "finish": "finish(summary) — the task is complete; summarise what you changed",
    "give_up": "give_up(reason) — you cannot complete the task; explain why",
}


class AgentLLM(Protocol):
    context_length: int
    name: str

    def generate(self, messages: list[Message], params: GenerationParams, cancel: threading.Event) -> str: ...

    def count_tokens(self, messages: list[Message]) -> int: ...


@dataclass
class ParsedAction:
    thought: str
    tool: str | None
    args: dict[str, Any] | None
    error: str | None = None


def _first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def parse_action(raw: str) -> ParsedAction:
    if TOOL_CALL not in raw:
        return ParsedAction(raw.strip(), None, None, "no tool call found (expected <|tool_call|>{...})")
    thought, _, rest = raw.partition(TOOL_CALL)
    blob = _first_json_object(rest)
    if blob is None:
        return ParsedAction(thought.strip(), None, None, "tool call is not a JSON object")
    try:
        obj = json.loads(blob)
    except json.JSONDecodeError as e:
        return ParsedAction(thought.strip(), None, None, f"invalid JSON in tool call: {e.msg}")
    tool = obj.get("tool") if isinstance(obj, dict) else None
    args = obj.get("args", {}) if isinstance(obj, dict) else None
    if not isinstance(tool, str) or not isinstance(args, dict):
        return ParsedAction(thought.strip(), None, None, 'tool call must look like {"tool": "...", "args": {...}}')
    if tool not in TOOLS and tool not in CONTROL_TOOLS:
        return ParsedAction(thought.strip(), tool, args, f"unknown tool {tool!r}")
    return ParsedAction(thought.strip(), tool, args)


_PLAN_LINE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.{3,200})$")


def parse_plan(raw: str, max_steps: int = 12) -> list[str]:
    steps = [m.group(1).strip() for line in raw.splitlines() if (m := _PLAN_LINE.match(line))]
    return steps[:max_steps]


def tool_manual() -> str:
    lines = [f"- {t.signature()}" for t in TOOLS.values()] + [f"- {v}" for v in CONTROL_TOOLS.values()]
    return "\n".join(lines)


def build_system(base_prompt: str, project: str, memories: list[dict], snippets: list[dict]) -> str:
    parts = [
        base_prompt,
        "You are working autonomously on the user's project. Act one step at a time. To use a tool, write a short "
        f"thought, then {TOOL_CALL} followed by a JSON object: {{\"tool\": NAME, \"args\": {{...}}}}. "
        "Only use the tools below. Never invent tool results.",
        "Tools:\n" + tool_manual(),
        "Project:\n" + project,
    ]
    if memories:
        parts.append("Project memory:\n" + "\n".join(f"- [{m['kind']}] {m['title']}: {m['content'][:300]}" for m in memories))
    if snippets:
        parts.append("Relevant code:\n" + "\n\n".join(
            f"{s['path']}:{s['start_line']}-{s['end_line']}\n{s['content']}" for s in snippets))
    return "\n\n".join(parts)


def build_messages(llm: AgentLLM, base_prompt: str, project: str, memories: list[dict], snippets: list[dict],
                   goal: str, plan: list[str], steps: list[dict], reserve: int) -> list[Message]:
    """Fit everything into the context window, dropping the least important context first."""
    budget = max(64, llm.context_length - reserve)
    snippets, memories = list(snippets), list(memories)
    keep_steps = len(steps)
    while True:
        task = goal if not plan else goal + "\n\nPlan:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(plan))
        msgs = [Message("system", build_system(base_prompt, project, memories, snippets)), Message("user", task)]
        dropped = len(steps) - keep_steps
        if dropped:
            msgs.append(Message("user", f"[{dropped} earlier step(s) omitted to fit the context window]"))
        for s in steps[len(steps) - keep_steps:]:
            call = json.dumps({"tool": s["tool"], "args": s["args"]})
            msgs.append(Message("assistant", f"{s.get('thought', '')}{TOOL_CALL}{call}", allow_special=True))
            msgs.append(Message("tool_result", s["result"]))
        if llm.count_tokens(msgs) <= budget:
            return msgs
        if snippets:
            snippets.pop()
        elif keep_steps > 1:
            keep_steps -= 1
        elif memories:
            memories.pop()
        else:
            return msgs  # generation will left-truncate; nothing more to drop
