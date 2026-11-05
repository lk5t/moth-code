"""Agent tools. Each tool validates arguments, passes the permission engine
(asking the user when required) and returns the real outcome — never a
simulated one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from moth.agent.memory import KINDS, MemoryStore
from moth.agent.retrieval import CodeIndex
from moth.security.permissions import (
    ActionKind, ApprovalBroker, Decision, PathOutsideWorkspace, PermissionEngine, Workspace,
)
from moth.workspace.files import FileOps
from moth.workspace.git import Git, GitError
from moth.workspace.scanner import file_tree
from moth.workspace.terminal import run_command

MAX_RESULT_CHARS = 6000


class ToolError(Exception):
    pass


class PermissionDenied(ToolError):
    pass


@dataclass
class ToolResult:
    ok: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    change: dict[str, Any] | None = None  # recorded file/git change, for the verified report

    def for_model(self) -> str:
        text = self.output if len(self.output) <= MAX_RESULT_CHARS else (
            self.output[: MAX_RESULT_CHARS // 2] + "\n…[truncated]…\n" + self.output[-MAX_RESULT_CHARS // 2:])
        return ("OK\n" if self.ok else "ERROR\n") + text


@dataclass
class AgentContext:
    workspace: Workspace
    project_id: int
    permissions: PermissionEngine
    approvals: ApprovalBroker
    memory: MemoryStore
    index: CodeIndex
    cancel: threading.Event
    emit: Callable[[dict[str, Any]], None]
    task_id: str = ""
    command_timeout: float = 600.0

    def authorize(self, kind: ActionKind, target: str, detail: str = "") -> None:
        result = self.permissions.check(kind, self.workspace, target)
        if result.decision == Decision.ALLOW:
            return
        if result.decision == Decision.DENY:
            raise PermissionDenied(f"not permitted: {result.reason}")
        self.emit({"kind": "approval_wait", "action": kind.value, "target": target})
        approved = self.approvals.request(kind.value, target, result.reason, result.risk,
                                          {"task_id": self.task_id, "detail": detail[:2000]},
                                          cancel_event=self.cancel)
        self.emit({"kind": "approval_result", "action": kind.value, "target": target, "approved": approved})
        if not approved:
            raise PermissionDenied(f"the user did not approve: {kind.value} {target}")


ToolFn = Callable[[AgentContext, dict[str, Any]], ToolResult]


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, str]  # name -> "type: description" ("?" prefix = optional)
    fn: ToolFn

    def signature(self) -> str:
        args = ", ".join(f"{k}{'?' if v.startswith('?') else ''}" for k, v in self.params.items())
        return f"{self.name}({args}) — {self.description}"

    def validate(self, args: Any) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise ToolError("args must be a JSON object")
        unknown = set(args) - set(self.params)
        if unknown:
            raise ToolError(f"unknown argument(s) for {self.name}: {', '.join(sorted(unknown))}")
        for k, spec in self.params.items():
            if not spec.startswith("?") and k not in args:
                raise ToolError(f"{self.name} requires argument '{k}'")
        for k, v in args.items():
            want = self.params[k].lstrip("?").split(":")[0].strip()
            if want == "string" and not isinstance(v, str):
                raise ToolError(f"argument '{k}' must be a string")
            if want == "integer" and not (isinstance(v, int) and not isinstance(v, bool)):
                raise ToolError(f"argument '{k}' must be an integer")
        return args


# ---- implementations ---------------------------------------------------------------
def _list_files(ctx: AgentContext, a: dict) -> ToolResult:
    prefix = a.get("path", "").strip("/").replace("\\", "/")
    entries = [e for e in file_tree(ctx.workspace.root) if not prefix or e["path"].startswith(prefix)]
    lines = [e["path"] + ("/" if e["dir"] else "") for e in entries[:400]]
    more = f"\n… {len(entries) - 400} more" if len(entries) > 400 else ""
    return ToolResult(True, "\n".join(lines) + more or "(empty)")


def _read_file(ctx: AgentContext, a: dict) -> ToolResult:
    path = a["path"]
    ctx.authorize(ActionKind.READ, path)
    text = FileOps(ctx.workspace).read(path)
    lines = text.splitlines()
    start = max(1, int(a.get("start_line", 1)))
    end = min(len(lines), int(a.get("end_line", start + 299)))
    body = "\n".join(f"{i:5d}  {lines[i - 1]}" for i in range(start, end + 1)) if lines else "(empty file)"
    suffix = f"\n[showing lines {start}-{end} of {len(lines)}]" if end < len(lines) or start > 1 else ""
    return ToolResult(True, body + suffix)


def _search_code(ctx: AgentContext, a: dict) -> ToolResult:
    ctx.index.update(ctx.project_id, ctx.workspace.root)
    hits = ctx.index.search(ctx.project_id, a["query"], limit=int(a.get("limit", 6)))
    if not hits:
        return ToolResult(True, "no matches")
    return ToolResult(True, "\n\n".join(f"{h['path']}:{h['start_line']}-{h['end_line']}\n{h['content']}" for h in hits))


def _write_file(ctx: AgentContext, a: dict) -> ToolResult:
    path = a["path"]
    ctx.authorize(ActionKind.WRITE, path, a["content"][:500])
    ops = FileOps(ctx.workspace)
    before = None
    try:
        before = ops.read(path)
    except (FileNotFoundError, ValueError):
        pass
    res = ops.write(path, a["content"])
    return ToolResult(True, f"{'created' if res['created'] else 'updated'} {path} ({res['bytes']} bytes)",
                      change={"type": "create" if res["created"] else "modify", "path": path, "before": before,
                              "after": a["content"]})


def _edit_file(ctx: AgentContext, a: dict) -> ToolResult:
    path = a["path"]
    ctx.authorize(ActionKind.WRITE, path, f"replace:\n{a['old'][:300]}\nwith:\n{a['new'][:300]}")
    ops = FileOps(ctx.workspace)
    before = ops.read(path)
    try:
        ops.edit(path, a["old"], a["new"])
    except ValueError as e:
        return ToolResult(False, str(e))
    return ToolResult(True, f"edited {path}", change={"type": "modify", "path": path, "before": before,
                                                      "after": ops.read(path)})


def _delete_file(ctx: AgentContext, a: dict) -> ToolResult:
    path = a["path"]
    ctx.authorize(ActionKind.DELETE, path)
    ops = FileOps(ctx.workspace)
    before = None
    try:
        before = ops.read(path)
    except (ValueError, IsADirectoryError, FileNotFoundError):
        pass
    ops.delete(path)
    return ToolResult(True, f"deleted {path}", change={"type": "delete", "path": path, "before": before})


def _run_command(ctx: AgentContext, a: dict) -> ToolResult:
    cmd = a["command"]
    ctx.authorize(ActionKind.EXECUTE, cmd)
    timeout = min(float(a.get("timeout", ctx.command_timeout)), 3600.0)
    ctx.emit({"kind": "command_start", "command": cmd})
    res = run_command(cmd, ctx.workspace.root,
                      on_output=lambda t: ctx.emit({"kind": "command_output", "data": t}),
                      timeout=timeout, cancel_event=ctx.cancel)
    status = "cancelled" if res.cancelled else "timed out" if res.timed_out else f"exit code {res.exit_code}"
    return ToolResult(res.ok, f"$ {cmd}\n{res.output}\n[{status}, {res.duration:.1f}s]",
                      data={"exit_code": res.exit_code, "command": cmd, "duration": res.duration})


def _git_status(ctx: AgentContext, a: dict) -> ToolResult:
    g = Git(ctx.workspace.root)
    if not g.is_repo():
        return ToolResult(False, "not a git repository")
    entries = g.status()
    return ToolResult(True, "\n".join(f"{e['status']:10s} {e['path']}" for e in entries) or "clean")


def _git_diff(ctx: AgentContext, a: dict) -> ToolResult:
    return ToolResult(True, Git(ctx.workspace.root).diff(a.get("path")) or "(no unstaged changes)")


def _git_commit(ctx: AgentContext, a: dict) -> ToolResult:
    ctx.authorize(ActionKind.GIT, f"git commit -m {a['message']!r}")
    g = Git(ctx.workspace.root)
    g.add()
    sha = g.commit(a["message"])
    return ToolResult(True, f"committed {sha[:10]}", change={"type": "commit", "hash": sha, "message": a["message"]})


def _remember(ctx: AgentContext, a: dict) -> ToolResult:
    kind = a.get("kind", "note")
    if kind not in KINDS:
        return ToolResult(False, f"kind must be one of {KINDS}")
    mid = ctx.memory.add(ctx.project_id, kind, a["title"], a["content"])
    return ToolResult(True, f"saved memory #{mid}")


TOOLS: dict[str, Tool] = {t.name: t for t in [
    Tool("list_files", "list project files", {"path": "?string: directory prefix"}, _list_files),
    Tool("read_file", "read a file with line numbers",
         {"path": "string", "start_line": "?integer", "end_line": "?integer"}, _read_file),
    Tool("search_code", "search the project index", {"query": "string", "limit": "?integer"}, _search_code),
    Tool("write_file", "create or overwrite a file", {"path": "string", "content": "string"}, _write_file),
    Tool("edit_file", "replace exact text in a file", {"path": "string", "old": "string", "new": "string"}, _edit_file),
    Tool("delete_file", "delete a file (asks the user)", {"path": "string"}, _delete_file),
    Tool("run_command", "run a shell command in the project root", {"command": "string", "timeout": "?integer"},
         _run_command),
    Tool("git_status", "show changed files", {}, _git_status),
    Tool("git_diff", "show a diff", {"path": "?string"}, _git_diff),
    Tool("git_commit", "commit all changes", {"message": "string"}, _git_commit),
    Tool("remember", "save a project memory", {"kind": "?string", "title": "string", "content": "string"}, _remember),
]}


def execute_tool(ctx: AgentContext, name: str, args: Any) -> ToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(False, f"unknown tool {name!r}. Available: {', '.join(TOOLS)}")
    try:
        tool.validate(args)
        return tool.fn(ctx, args)
    except PermissionDenied as e:
        return ToolResult(False, str(e), data={"denied": True})
    except PathOutsideWorkspace as e:
        return ToolResult(False, f"not permitted: {e}", data={"denied": True})
    except (ToolError, GitError, FileNotFoundError, IsADirectoryError, ValueError, PermissionError, OSError) as e:
        return ToolResult(False, f"{type(e).__name__}: {e}")
