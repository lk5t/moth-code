"""A worker that already runs an updated version (re-executed into it) must restart into the NEXT update.

Real processes: three installed worker versions, the real CLI entry ``reexec_into_current`` and the real
restart environment. Before 0.6.3 the restart inherited MOTH_WORKER_REEXEC and the old version's
PYTHONPATH, so the old version started again, re-installed the same update and restarted — a loop."""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _version(home: Path, v: str) -> Path:
    d = home / "versions" / v
    (d / "worker" / "moth_worker").mkdir(parents=True)
    (d / "backend").mkdir()
    real = (ROOT / "worker" / "moth_worker" / "updater.py").read_text()
    (d / "worker" / "moth_worker" / "updater.py").write_text(real)
    (d / "worker" / "moth_worker" / "ed25519_verify.py").write_text((ROOT / "worker/moth_worker/ed25519_verify.py").read_text())
    (d / "worker" / "moth_worker" / "__init__.py").write_text(f'__version__ = "{v}"\n')
    # a tiny CLI with the real start-up sequence: run the newest installed version, report, maybe restart
    (d / "worker" / "moth_worker" / "cli.py").write_text(textwrap.dedent(f'''
        import os, sys
        from pathlib import Path
        from moth_worker import __version__, updater
        home = Path(sys.argv[1])
        updater.reexec_into_current(home, sys.argv[1:])
        with open(home / "started.log", "a") as f:
            f.write(__version__ + "\\n")
        if (home / "install-next").exists():
            target = (home / "install-next").read_text().strip()
            (home / "install-next").unlink()
            updater._relink(home / "current", home / "versions" / target)   # what apply() does
            updater.restart(sys.argv[1:])
    '''))
    return d


def test_second_update_restarts_into_the_new_version(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    base = _version(tmp_path / "base-install", "0.6.1")  # the originally installed worker
    _version(home, "0.6.2")
    _version(home, "0.6.3")
    os.symlink(home / "versions" / "0.6.2", home / "current")  # first update already installed
    (home / "install-next").write_text("0.6.3")  # while running 0.6.2, the 0.6.3 update is installed
    env = {k: v for k, v in os.environ.items() if not k.startswith("MOTH_WORKER")}
    env["PYTHONPATH"] = str(base / "worker")
    out = subprocess.run([sys.executable, "-m", "moth_worker.cli", str(home)], env=env, capture_output=True,
                         text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    # 0.6.1 re-executes into 0.6.2, which installs 0.6.3 and restarts: the restart must run 0.6.3
    assert (home / "started.log").read_text().split() == ["0.6.2", "0.6.3"]
