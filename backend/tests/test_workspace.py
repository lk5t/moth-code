import shutil
import subprocess
import sys
import threading
import time

import pytest

from moth.security.permissions import PathOutsideWorkspace, Workspace
from moth.workspace.files import FileOps
from moth.workspace.git import Git, git_available
from moth.workspace.scanner import file_tree, scan_project
from moth.workspace.terminal import TerminalManager, run_command

PY = f'"{sys.executable}"'


def test_file_ops_roundtrip(project):
    ops = FileOps(Workspace(project))
    res = ops.write("pkg/new_mod.py", "x = 1\n")
    assert res["created"] and ops.read("pkg/new_mod.py") == "x = 1\n"
    ops.edit("pkg/new_mod.py", "x = 1", "x = 2")
    assert ops.read("pkg/new_mod.py") == "x = 2\n"
    with pytest.raises(ValueError):
        ops.edit("pkg/new_mod.py", "missing", "y")
    ops.rename("pkg/new_mod.py", "pkg/renamed.py")
    assert not (project / "pkg/new_mod.py").exists()
    ops.delete("pkg/renamed.py")
    assert not (project / "pkg/renamed.py").exists()
    with pytest.raises(PathOutsideWorkspace):
        ops.write("../escape.py", "bad")
    with pytest.raises(PermissionError):
        ops.delete(".")
    names = [e["name"] for e in ops.list_dir(".")]
    assert names[0] in ("demo", "node_modules")  # directories first


def test_scan_project(project):
    s = scan_project(project)
    assert s.languages.get("Python") == 2
    assert "python" in s.build_systems and s.test_command == "python -m pytest"
    assert s.readme == "README.md"
    tree = [e["path"] for e in file_tree(project)]
    assert "demo/math_utils.py" in tree and "demo" in tree
    assert not any(p.startswith("node_modules") for p in tree)


def test_run_command_streams_and_exit_code(tmp_path):
    out = []
    r = run_command(f'{PY} -c "print(\'hello moth\'); import sys; sys.exit(3)"', tmp_path, out.append)
    assert r.exit_code == 3 and "hello moth" in r.output and "hello moth" in "".join(out)


def test_run_command_cancel_kills_process(tmp_path):
    cancel = threading.Event()
    threading.Timer(0.5, cancel.set).start()
    start = time.time()
    r = run_command(f'{PY} -c "import time; time.sleep(30)"', tmp_path, cancel_event=cancel)
    assert r.cancelled and time.time() - start < 10


def test_run_command_timeout(tmp_path):
    r = run_command(f'{PY} -c "import time; time.sleep(30)"', tmp_path, timeout=0.5)
    assert r.timed_out and not r.ok


def test_terminal_session_cd_and_restrict(project):
    mgr = TerminalManager()
    s = mgr.create(project, root=project)
    done = threading.Event()
    results = []

    def on_exit(r):
        results.append(r)
        done.set()

    s.execute("cd demo", lambda t: None, on_exit)
    assert done.wait(5) and s.cwd == (project / "demo").resolve()
    done.clear()
    s.execute("cd ../..", lambda t: None, on_exit)
    assert done.wait(5) and results[-1].exit_code == 1
    assert s.cwd == (project / "demo").resolve()
    mgr.close_all()


@pytest.mark.skipif(not git_available(), reason="git not installed")
def test_git_integration(project):
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=project, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
    g = Git(project)
    assert g.is_repo()
    statuses = {e["path"]: e["status"] for e in g.status()}
    assert statuses.get("README.md") == "untracked"
    g.add()
    sha = g.commit("initial")
    assert len(sha) == 40
    (project / "README.md").write_text("# Demo\nchanged\n")
    assert {e["path"]: e["status"] for e in g.status()}["README.md"] == "modified"
    assert "+changed" in g.diff("README.md")
    assert g.log()[0]["subject"] == "initial"


def test_edit_preserves_crlf_files(tmp_path):
    (tmp_path / "w.py").write_bytes(b"def add(a, b):\r\n    return a + b\r\n")
    ops = FileOps(Workspace(tmp_path))
    ops.edit("w.py", "    return a + b\n", "    return a + b\n\n\ndef mul(a, b):\n    return a * b\n")
    data = (tmp_path / "w.py").read_bytes()
    assert b"def mul" in data and b"\n" not in data.replace(b"\r\n", b"")


def test_powershell_script_wrapping():
    from moth.workspace.terminal import powershell_script

    s = powershell_script('"C:\\\\Program Files\\\\Python\\\\python.exe" -c "print(1)"')
    assert '& "C:' in s and "exit $LASTEXITCODE" in s
    assert "& " not in powershell_script("npm test").split("LASTEXITCODE=0; ")[1].split("\n")[0]
