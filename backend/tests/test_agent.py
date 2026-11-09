"""Agent engine tests.

``ScriptedLLM`` is a TEST DOUBLE that replays fixed outputs so the engine's
mechanics (parsing, permissions, execution, cancellation, recovery) can be
tested deterministically. The product never uses it: in the app, tasks run on
the loaded MOTH model only. ``test_real_untrained_model_*`` exercises the loop
with a genuine (untrained) MOTH network.
"""

import json
import sys
import threading
import time

import pytest

from moth.agent.engine import AgentEngine, EngineConfig, TaskState
from moth.agent.manager import TaskManager
from moth.agent.memory import MemoryStore
from moth.agent.protocol import parse_action, parse_plan
from moth.agent.retrieval import CodeIndex, chunk_text
from moth.agent.tools import AgentContext
from moth.db import Database
from moth.events import EventBus
from moth.security.permissions import ApprovalBroker, PermissionEngine, PermissionSettings, Workspace

TC = "<|tool_call|>"


def call(tool, **args):
    return f"thinking{TC}" + json.dumps({"tool": tool, "args": args})


class ScriptedLLM:
    name = "scripted-test-double"
    context_length = 100_000

    def __init__(self, outputs, delay=0.0):
        self.outputs = list(outputs)
        self.prompts = []
        self.delay = delay

    def count_tokens(self, messages):
        return sum(len(m.content) for m in messages) // 4

    def generate(self, messages, params, cancel):
        self.prompts.append(messages)
        if self.delay:
            cancel.wait(self.delay)
        return self.outputs.pop(0) if self.outputs else "no idea"


@pytest.fixture
def env(tmp_path, project):
    db = Database(tmp_path / "a.db")
    events = []
    broker = ApprovalBroker()
    cancel = threading.Event()
    ctx = AgentContext(Workspace(project), 1, PermissionEngine(PermissionSettings(auto_write=True)), broker, MemoryStore(db), CodeIndex(db), cancel,
                       events.append, task_id="t")
    return {"db": db, "ctx": ctx, "events": events, "broker": broker, "project": project}


def run(env, outputs, **cfg):
    llm = ScriptedLLM(outputs)
    state = TaskState("t", "add a multiply function")
    AgentEngine(llm, env["ctx"], "You are MOTH.", EngineConfig(**{"plan": False, **cfg})).run(state)
    return state, llm


def test_parse_action_and_plan():
    a = parse_action('I will read it<|tool_call|>{"tool": "read_file", "args": {"path": "a.py"}} trailing')
    assert a.tool == "read_file" and a.args == {"path": "a.py"} and a.thought == "I will read it"
    assert parse_action("just text").error
    assert parse_action(TC + "{not json").error
    assert "unknown tool" in parse_action(TC + '{"tool": "rm_rf", "args": {}}').error
    nested = parse_action(TC + '{"tool": "write_file", "args": {"path": "x", "content": "a = {\\"k\\": 1}"}}')
    assert nested.args["content"] == 'a = {"k": 1}'
    assert parse_plan("Plan:\n1. read code\n2) add function\n- run tests\nnoise") == ["read code", "add function", "run tests"]


def test_completes_real_edit_and_verifies_with_tests(env):
    p = env["project"]
    (p / "tests").mkdir()
    (p / "tests" / "test_math.py").write_text(
        "from demo.math_utils import multiply\n\ndef test_mul():\n    assert multiply(3, 4) == 12\n")
    state, llm = run(env, [
        call("read_file", path="demo/math_utils.py"),
        call("edit_file", path="demo/math_utils.py", old="    return a + b\n",
             new="    return a + b\n\n\ndef multiply(a, b):\n    return a * b\n"),
        call("run_command", command=f'"{sys.executable}" -m pytest -q tests'),
        call("finish", summary="Added multiply()."),
    ])
    assert state.status == "completed", state.report
    assert "def multiply" in (p / "demo/math_utils.py").read_text()
    assert [s["tool"] for s in state.steps] == ["read_file", "edit_file", "run_command"]
    assert state.steps[2]["ok"]
    v = state.report["verification"]
    assert v["ran"] and v["passed"] and v["command"] == "python -m pytest"
    assert state.report["changes"] == [{"type": "modify", "path": "demo/math_utils.py"}]
    # tool output was really fed back to the model
    assert "return a + b" in llm.prompts[1][-1].content
    # verified solution stored in memory
    assert any(m["kind"] == "solution" and m["verified"] for m in MemoryStore(env["db"]).list(1))


def test_failed_verification_needs_review(env):
    p = env["project"]
    (p / "tests").mkdir()
    (p / "tests" / "test_fail.py").write_text("def test_x():\n    assert False\n")
    state, _ = run(env, [call("write_file", path="x.py", content="x = 1\n"), call("finish", summary="done")])
    assert state.status == "needs_review" and state.report["verification"]["passed"] is False


def test_repeated_invalid_output_reports_model_limitation(env):
    state, _ = run(env, ["I don't know", "maybe", "hmm"])
    assert state.status == "model_incapable"
    assert "could not produce a valid action" in state.error
    assert state.report["changes"] == [] and state.report["model_summary"] is None


def test_give_up_is_reported_honestly(env):
    state, _ = run(env, [call("give_up", reason="too complex")])
    assert state.status == "model_incapable" and "too complex" in state.error


def test_outside_workspace_denied_and_reported_to_model(env, tmp_path):
    state, llm = run(env, [call("write_file", path="../evil.py", content="x"), call("finish", summary="ok")])
    assert not (tmp_path / "evil.py").exists()
    assert state.steps[0]["ok"] is False and "not permitted" in state.steps[0]["result"]


def test_destructive_actions_wait_for_approval(env):
    p = env["project"]
    broker = env["broker"]

    def approver(approve):
        def loop():
            for _ in range(200):
                pend = broker.pending()
                if pend:
                    broker.resolve(pend[0]["id"], approve)
                    return
                time.sleep(0.02)
        threading.Thread(target=loop, daemon=True).start()

    approver(False)
    state, _ = run(env, [call("delete_file", path="README.md"), call("finish", summary="x")], verify=False)
    assert (p / "README.md").exists() and "did not approve" in state.steps[0]["result"]

    approver(True)
    state, _ = run(env, [call("delete_file", path="README.md"), call("finish", summary="x")], verify=False)
    assert not (p / "README.md").exists() and state.steps[0]["ok"]


def test_step_limit(env):
    state, _ = run(env, [call("list_files")] * 5, max_steps=3)
    assert state.status == "incomplete" and len(state.steps) == 3


def test_failed_command_is_remembered_and_recalled(env):
    bad = f'"{sys.executable}" -c "import nonexistent_module_xyz"'
    run(env, [call("run_command", command=bad), call("finish", summary="x")], verify=False)
    mem = MemoryStore(env["db"]).list(1, "error")
    assert mem and "nonexistent_module_xyz" in mem[0]["content"]
    state, _ = run(env, [call("run_command", command=bad), call("finish", summary="x")], verify=False)
    assert "Related project memory" in state.steps[0]["result"]


def test_manager_cancel_resume_revert(tmp_path, project):
    db = Database(tmp_path / "m.db")
    bus = EventBus()
    mgr = TaskManager(db, bus, ApprovalBroker())
    ws = Workspace(project)
    llm = ScriptedLLM([call("write_file", path="new.py", content="a = 1\n")] + [call("list_files")] * 50, delay=0.2)
    tid = mgr.start(1, ws, "make new.py", llm, PermissionEngine(PermissionSettings(auto_write=True)), "sys", EngineConfig(plan=False, max_steps=50))
    for _ in range(100):
        if (project / "new.py").exists():
            break
        time.sleep(0.05)
    assert mgr.cancel(tid)
    mgr.wait(tid, 10)
    t = mgr.get(tid)
    assert t["status"] == "cancelled" and (project / "new.py").exists()

    # resume continues with the prior history in the prompt
    llm2 = ScriptedLLM([call("finish", summary="done")])
    mgr.start(1, ws, "", llm2, PermissionEngine(PermissionSettings(auto_write=True)), "sys", EngineConfig(plan=False, verify=False), task_id=tid)
    mgr.wait(tid, 10)
    assert mgr.get(tid)["status"] == "completed"
    assert any('"write_file"' in m.content for m in llm2.prompts[0])

    assert mgr.revert(tid, ws) == ["new.py"] and not (project / "new.py").exists()
    assert mgr.get(tid)["status"] == "reverted"

    # interrupted tasks are recoverable after a restart
    db.execute("UPDATE tasks SET status='running' WHERE id=?", (tid,))
    TaskManager(db, bus, ApprovalBroker())
    assert db.one("SELECT status FROM tasks WHERE id=?", (tid,))["status"] == "interrupted"


def test_retrieval_index_incremental(tmp_path, project):
    db = Database(tmp_path / "r.db")
    idx = CodeIndex(db)
    s = idx.update(1, project)
    assert s["added"] >= 2
    assert idx.search(1, "add function")[0]["path"] == "demo/math_utils.py"
    assert idx.update(1, project)["added"] == 0  # unchanged
    (project / "demo" / "math_utils.py").write_text("def divide(a, b):\n    return a / b\n")
    import os
    os.utime(project / "demo" / "math_utils.py", (time.time() + 5, time.time() + 5))
    assert idx.update(1, project)["updated"] == 1
    assert idx.search(1, "divide")[0]["path"] == "demo/math_utils.py"
    assert not any(h["path"] == ".env" for h in idx.search(1, "SECRET"))  # secrets never indexed
    assert len(chunk_text("\n".join(map(str, range(100))))) == 3


def test_context_budget_trims(env):
    from moth.agent.protocol import build_messages

    class Small(ScriptedLLM):
        context_length = 300

    steps = [{"tool": "list_files", "args": {}, "thought": "", "result": "x" * 400} for _ in range(5)]
    msgs = build_messages(Small([]), "sys", "proj", [], [{"path": "a", "start_line": 1, "end_line": 2, "content": "y" * 800}],
                          "goal", [], steps, reserve=50)
    assert "omitted" in " ".join(m.content for m in msgs)


def test_real_untrained_model_is_reported_as_incapable(env, tiny_pipeline):
    """A genuine MOTH network (random weights) drives the loop; the engine must not claim success."""
    import torch

    from moth.inference.local import LocalAgentLLM, LocalInference
    from moth.model.config import preset
    from moth.model.transformer import MothModel

    torch.manual_seed(0)
    tok = tiny_pipeline["tokenizer"]
    eng = LocalInference(env["project"])
    eng.model = MothModel(preset("moth-tiny", vocab_size=448)).eval()
    eng.tokenizer = tok
    eng.manifest = {"name": "untrained-tiny", "context_length": 256, "params": 0}
    llm = LocalAgentLLM(eng)
    state = TaskState("t", "add a multiply function")
    AgentEngine(llm, env["ctx"], "sys", EngineConfig(plan=True, max_new_tokens=24)).run(state)
    assert state.status == "model_incapable"
    assert "untrained-tiny" in state.error
    assert state.report["changes"] == []
