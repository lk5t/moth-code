import os
import threading
import time

import pytest

from moth.security.permissions import (
    ActionKind, ApprovalBroker, Decision, PathOutsideWorkspace, PermissionEngine,
    PermissionSettings, Workspace, classify_command, is_secret_path,
)


def test_workspace_boundary(project, tmp_path):
    ws = Workspace(project)
    assert ws.resolve("demo/math_utils.py") == project / "demo" / "math_utils.py"
    with pytest.raises(PathOutsideWorkspace):
        ws.resolve("../outside.txt")
    with pytest.raises(PathOutsideWorkspace):
        ws.resolve(str(tmp_path / "elsewhere"))


@pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
def test_symlink_escape_rejected(project, tmp_path):
    outside = tmp_path / "secret_dir"
    outside.mkdir()
    (project / "link").symlink_to(outside)
    with pytest.raises(PathOutsideWorkspace):
        Workspace(project).resolve("link/file.txt")


@pytest.mark.parametrize("cmd", [
    "rm -rf build", "del /s /q build", "git reset --hard HEAD~1", "git push --force",
    "Remove-Item -Recurse dist", "format C:", "git clean -fdx", "rd /s /q out",
])
def test_destructive_commands_need_approval(cmd):
    r = classify_command(cmd)
    assert r.decision == Decision.ASK and r.risk == "high"


@pytest.mark.parametrize("cmd", ["git push origin main", "npm publish", "twine upload dist/*"])
def test_publish_needs_approval(cmd):
    assert classify_command(cmd).decision == Decision.ASK


@pytest.mark.parametrize("cmd", ["python -m pytest", "npm test", "ls -la", "git status", "cargo build"])
def test_ordinary_commands_allowed(cmd):
    assert classify_command(cmd).decision == Decision.ALLOW


def test_secret_detection():
    for p in [".env", "config/.env.local", "id_rsa", "home/.ssh/config", "server.pem", ".aws/credentials"]:
        assert is_secret_path(p), p
    for p in [".env.example", "src/main.py", "README.md", "environment.py"]:
        assert not is_secret_path(p), p
    assert classify_command("cat .env").decision == Decision.ASK


def test_permission_engine(project):
    ws = Workspace(project)
    eng = PermissionEngine()
    assert eng.check(ActionKind.READ, ws, "demo/math_utils.py").decision == Decision.ALLOW
    assert eng.check(ActionKind.WRITE, ws, "new.py").decision == Decision.ALLOW
    assert eng.check(ActionKind.DELETE, ws, "new.py").decision == Decision.ASK
    assert eng.check(ActionKind.READ, ws, ".env").decision == Decision.ASK
    assert eng.check(ActionKind.WRITE, ws, "../x.py").decision == Decision.DENY
    assert eng.check(ActionKind.PUBLISH, ws, "git push").decision == Decision.ASK
    strict = PermissionEngine(PermissionSettings(auto_write=False, auto_execute=False))
    assert strict.check(ActionKind.WRITE, ws, "new.py").decision == Decision.ASK
    assert strict.check(ActionKind.EXECUTE, ws, "pytest").decision == Decision.ASK


def test_approval_broker_roundtrip():
    seen = []
    broker = ApprovalBroker(notify=seen.append)
    result = {}

    def worker():
        result["approved"] = broker.request("delete", "a.txt", "deleting", timeout=5)

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(50):
        if seen:
            break
        time.sleep(0.02)
    assert broker.pending()[0]["target"] == "a.txt"
    assert broker.resolve(seen[0].id, True)
    t.join(2)
    assert result["approved"] is True
    assert broker.pending() == []


def test_approval_cancel_and_timeout():
    broker = ApprovalBroker()
    cancel = threading.Event()
    cancel.set()
    assert broker.request("x", "y", "z", cancel_event=cancel) is False
    assert broker.request("x", "y", "z", timeout=0.2) is False
