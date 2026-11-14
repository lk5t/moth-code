"""1.0 assistant: plan first, self-check, undo to a checkpoint."""
from moth.agent.engine import AgentEngine, EngineConfig, TaskState
from moth.agent.manager import TaskManager
from moth.events import EventBus
from test_agent import ScriptedLLM, call, env, run  # noqa: F401 — fixture


def test_self_check_sends_moth_back_to_fix_broken_files(env):
    state, llm = run(env, [
        call("write_file", path="broken.py", content="def f(:\n    return 1\n"),
        call("finish", summary="done"),
        call("write_file", path="broken.py", content="def f():\n    return 1\n"),
        call("finish", summary="fixed"),
    ], verify=False)
    assert state.status == "completed", state.report
    checks = [s for s in state.steps if s["tool"] == "self_check"]
    assert len(checks) == 1 and "broken.py:1" in checks[0]["result"]
    assert "def f():" in (env["project"] / "broken.py").read_text()


def test_plan_first_waits_for_approval(env):
    llm = ScriptedLLM(["1. read the code\n2. add multiply"])
    state = TaskState("t", "add multiply")
    AgentEngine(llm, env["ctx"], "You are MOTH.", EngineConfig(approve_plan=True)).run(state)
    assert state.status == "plan_ready" and state.plan == ["read the code", "add multiply"] and not state.steps


def test_restore_undoes_a_task_and_everything_after_it(env):
    from moth.security.permissions import PermissionEngine, PermissionSettings, Workspace

    p = env["project"]
    manager = TaskManager(env["db"], EventBus(), env["broker"])
    ws = Workspace(p)
    perms = PermissionEngine(PermissionSettings(auto_write=True))
    ids = []
    for name in ("one.py", "two.py"):
        tid = manager.start(1, ws, f"create {name}", ScriptedLLM([call("write_file", path=name, content="x = 1\n"),
                                                                  call("finish", summary="ok")]),
                            perms, "", EngineConfig(plan=False, verify=False), memory=env["ctx"].memory,
                            index=env["ctx"].index)
        manager.wait(tid, 30)
        ids.append(tid)
    points = manager.checkpoints(1)
    assert [x["task_id"] for x in points] == ids[::-1]
    restored = manager.restore(1, ids[0], ws)
    assert set(restored) == {"one.py", "two.py"} and not (p / "one.py").exists() and not (p / "two.py").exists()
    assert manager.checkpoints(1) == []
