"""The autonomous task loop.

1. Gather context: project scan, relevant memories, retrieved code.
2. Ask MOTH for a plan.
3. Loop: MOTH proposes one tool call → validated → permission-checked →
   executed for real → result fed back. Stops on ``finish``/``give_up``,
   cancellation, step limit, or when the model repeatedly produces unusable
   output (reported as a model limitation — never as success).
4. Verify: if files changed and the project has a test command, run it and
   report the real outcome.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from moth.agent.memory import MemoryStore
from moth.agent.protocol import AgentLLM, build_messages, parse_action, parse_plan
from moth.agent.retrieval import CodeIndex
from moth.agent.tools import AgentContext, ToolResult, execute_tool
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams
from moth.workspace.scanner import scan_project


@dataclass
class EngineConfig:
    max_steps: int = 25
    max_invalid_outputs: int = 3
    max_new_tokens: int = 384
    temperature: float = 0.3
    verify: bool = True
    plan: bool = True


@dataclass
class TaskState:
    id: str
    goal: str
    status: str = "queued"
    plan: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    changes: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)


class AgentEngine:
    def __init__(self, llm: AgentLLM, ctx: AgentContext, base_prompt: str, config: EngineConfig | None = None,
                 on_update: Callable[[TaskState], None] | None = None):
        self.llm = llm
        self.ctx = ctx
        self.base_prompt = base_prompt
        self.cfg = config or EngineConfig()
        self.on_update = on_update or (lambda s: None)

    def _emit(self, state: TaskState, kind: str, **data: Any) -> None:
        self.ctx.emit({"kind": kind, "task_id": state.id, **data})

    def _set(self, state: TaskState, status: str) -> None:
        state.status = status
        self._emit(state, "status", status=status)
        self.on_update(state)

    def _params(self, stop_tool_result: bool = True) -> GenerationParams:
        return GenerationParams(max_new_tokens=self.cfg.max_new_tokens, temperature=self.cfg.temperature,
                                top_k=40, top_p=0.95, repetition_penalty=1.05, include_special=True,
                                stop_strings=["<|tool_result|>", "<|user|>"] if stop_tool_result else [])

    def run(self, state: TaskState) -> TaskState:
        try:
            self._run(state)
        except Exception as e:  # infrastructure failure: report honestly
            state.error = f"{type(e).__name__}: {e}"
            self._finish(state, "failed", summary=None)
        return state

    def _run(self, state: TaskState) -> None:
        ctx = self.ctx
        self._set(state, "running")
        summary = scan_project(ctx.workspace.root)
        project_text = summary.describe()
        ctx.memory.upsert(ctx.project_id, "architecture", "Project overview", project_text)
        index_stats = ctx.index.update(ctx.project_id, ctx.workspace.root)
        self._emit(state, "context", indexed=index_stats)
        memories = ctx.memory.search(ctx.project_id, state.goal)
        snippets = ctx.index.search(ctx.project_id, state.goal, limit=4)

        if self.cfg.plan and not state.plan and not state.steps:
            self._emit(state, "planning")
            raw = self.llm.generate(
                [Message("system", self.base_prompt + "\n\nProject:\n" + project_text),
                 Message("user", f"Task: {state.goal}\n\nWrite a short numbered plan (one step per line).")],
                self._params(), ctx.cancel)
            state.plan = parse_plan(raw)
            if not state.plan:
                state.notes.append("MOTH did not produce a usable plan; continuing step by step.")
            self._emit(state, "plan", plan=state.plan, raw=raw[:2000])
            self.on_update(state)

        invalid = 0
        finished_summary: str | None = None
        while len(state.steps) < self.cfg.max_steps:
            if ctx.cancel.is_set():
                return self._finish(state, "cancelled", None)
            msgs = build_messages(self.llm, self.base_prompt, project_text, memories, snippets, state.goal,
                                  state.plan, state.steps, reserve=self.cfg.max_new_tokens)
            self._emit(state, "thinking", step=len(state.steps) + 1)
            raw = self.llm.generate(msgs, self._params(), ctx.cancel)
            if ctx.cancel.is_set():
                return self._finish(state, "cancelled", None)
            action = parse_action(raw)
            if action.error:
                invalid += 1
                self._emit(state, "invalid_output", error=action.error, raw=raw[:1000], count=invalid)
                if invalid >= self.cfg.max_invalid_outputs:
                    state.error = (
                        f"The current MOTH model ({self.llm.name}) could not produce a valid action after "
                        f"{invalid} attempts (last problem: {action.error}). This task is beyond what the "
                        "model can do right now; more training — especially on agent/tool-use data — is needed.")
                    return self._finish(state, "model_incapable", None)
                continue
            invalid = 0
            if action.tool == "finish":
                finished_summary = str(action.args.get("summary", "")).strip() or "(no summary given)"
                break
            if action.tool == "give_up":
                state.error = "MOTH reported it cannot complete this task: " + str(action.args.get("reason", ""))
                return self._finish(state, "model_incapable", None)

            self._emit(state, "tool_call", tool=action.tool, args=action.args, thought=action.thought)
            result = execute_tool(ctx, action.tool, action.args)
            if not result.ok and action.tool == "run_command":
                result = self._investigate_failure(result)
            step = {"i": len(state.steps) + 1, "thought": action.thought, "tool": action.tool, "args": action.args,
                    "ok": result.ok, "result": result.for_model(), "ts": time.time()}
            state.steps.append(step)
            if result.change:
                state.changes.append(result.change)
            self._emit(state, "tool_result", step=step)
            self.on_update(state)
        else:
            state.error = f"Stopped after the step limit ({self.cfg.max_steps}) without MOTH finishing the task."
            return self._finish(state, "incomplete", None)
        self._finish(state, "completed", finished_summary)

    def _investigate_failure(self, result: ToolResult) -> ToolResult:
        """Attach related past errors/solutions from memory, and remember this failure."""
        cmd = result.data.get("command", "")
        tail = result.output[-1500:]
        related = self.ctx.memory.search(self.ctx.project_id, tail, limit=3)
        related = [m for m in related if m["kind"] in ("error", "solution")]
        self.ctx.memory.add(self.ctx.project_id, "error", f"Command failed: {cmd}"[:200], tail)
        if related:
            notes = "\n".join(f"- [{m['kind']}] {m['title']}: {m['content'][:200]}" for m in related)
            result.output += f"\n\nRelated project memory:\n{notes}"
        return result

    def _verify(self, state: TaskState) -> dict[str, Any] | None:
        if not self.cfg.verify or not any(c["type"] != "commit" for c in state.changes):
            return None
        cmd = scan_project(self.ctx.workspace.root).test_command
        if not cmd:
            return {"ran": False, "reason": "no test command detected for this project"}
        self._emit(state, "verifying", command=cmd)
        res = execute_tool(self.ctx, "run_command", {"command": cmd})
        return {"ran": True, "command": cmd, "passed": res.ok, "exit_code": res.data.get("exit_code"),
                "output_tail": res.output[-3000:]}

    def _finish(self, state: TaskState, status: str, summary: str | None) -> None:
        verification = None
        if status == "completed":
            verification = self._verify(state)
            if verification and verification.get("ran") and not verification["passed"]:
                status = "needs_review"
        state.report = {
            "status": status,
            "model_summary": summary,  # MOTH's own words — not verified
            "changes": [{k: v for k, v in c.items() if k not in ("before", "after")} for c in state.changes],
            "commands": [{"command": s["args"].get("command"), "ok": s["ok"]} for s in state.steps
                         if s["tool"] == "run_command"],
            "steps": len(state.steps),
            "verification": verification,
            "error": state.error,
            "notes": state.notes,
        }
        if status == "completed" and verification and verification.get("passed") and summary:
            self.ctx.memory.add(self.ctx.project_id, "solution", state.goal[:200],
                                f"{summary}\nChanged: {', '.join(c.get('path', '') for c in state.changes)}",
                                verified=True)
        self._set(state, status)


def report_text(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2)
