"""Automatic start, single instance, logging and uninstall for MOTH Worker.

``install-service`` picks the best mechanism the machine allows, with no administrator rights needed:

* **systemd** — as root a system service; otherwise the user's systemd, if lingering is (or can be)
  enabled so it runs without a login and after reboots;
* **cron** — ``@reboot`` plus a check every minute (the worker keeps exactly one instance itself);
* **launchd** — a LaunchAgent on macOS (starts at login, restarted if it stops);
* **task** — a Windows scheduled task (at logon; at startup when installed as administrator) running
  the worker under ``--supervise``, which restarts it if it stops.

The chosen mechanism is recorded in ``service.json`` so ``uninstall`` removes exactly what was added.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from moth_worker.config import WorkerConfig, default_dir

CRON_MARK = "# moth-worker"
UNIT = """[Unit]
Description=MOTH Worker (MOTH training network)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=MOTH_WORKER_HOME={home}
ExecStart={exe} --home {home} run
Restart=always
RestartSec=15
Nice=10

[Install]
WantedBy={wanted}
"""
PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>dev.mothcode.worker</string>
  <key>ProgramArguments</key><array><string>{exe}</string><string>--home</string><string>{home}</string>
    <string>run</string><string>--log-file</string><string>{home}/worker.log</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
"""
TASK = "MOTH Worker"


def _exe() -> str:
    """The moth-worker command of this installation."""
    here = Path(sys.executable).parent
    for name in ("moth-worker", "moth-worker.exe"):
        if (here / name).exists():
            return str(here / name)
    return shutil.which("moth-worker") or f"{sys.executable} -m moth_worker.cli"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


# ---- single instance, logging, supervision ---------------------------------------------------------
def single_instance(home: Path):
    """An exclusive lock on ``<home>/run.lock`` held for the life of the process, or None if another
    worker of this installation is already running."""
    home.mkdir(parents=True, exist_ok=True)
    f = open(home / "run.lock", "a+")
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def log_to_file(path: Path) -> None:
    """Send print() output to a rotating log file (5 MB × 3)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")

    class Stream:
        def write(self, s: str) -> None:
            for line in s.splitlines():
                if line.strip():
                    handler.emit(logging.LogRecord("moth-worker", logging.INFO, "", 0,
                                                   time.strftime("%Y-%m-%d %H:%M:%S ") + line, None, None))

        def flush(self) -> None:
            handler.flush()

    sys.stdout = sys.stderr = Stream()  # type: ignore[assignment]


def supervise(home: Path, argv: list[str]) -> int:
    """Run the worker and start it again whenever it stops (unless it was revoked or uninstalled)."""
    while True:
        rc = subprocess.run([sys.executable, "-m", "moth_worker.cli", *argv]).returncode
        if rc in (3, 4) or not (home / "config.json").exists():
            return rc
        time.sleep(15)


# ---- install --------------------------------------------------------------------------------------
def _record(home: Path, info: dict[str, Any]) -> None:
    (home / "service.json").write_text(json.dumps({**info, "installed_at": int(time.time())}, indent=2))


def _systemd_user_ok() -> bool:
    if not shutil.which("systemctl") or _run(["systemctl", "--user", "show-environment"]).returncode != 0:
        return False
    user = os.environ.get("USER") or ""
    linger = _run(["loginctl", "show-user", user, "-p", "Linger"]).stdout.strip()
    if linger != "Linger=yes":
        _run(["loginctl", "enable-linger", user])  # allowed for one's own user on many systems
        linger = _run(["loginctl", "show-user", user, "-p", "Linger"]).stdout.strip()
    return linger == "Linger=yes"


def _install_systemd(home: Path, root: bool, start: bool) -> dict:
    unit = UNIT.format(home=home, exe=_exe(), wanted="multi-user.target" if root else "default.target")
    path = Path("/etc/systemd/system/moth-worker.service") if root else \
        Path.home() / ".config/systemd/user/moth-worker.service"
    cmd = ["systemctl"] if root else ["systemctl", "--user"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit)
    _run(cmd + ["daemon-reload"])
    _run(cmd + (["enable", "--now", "moth-worker"] if start else ["enable", "moth-worker"]))
    return {"mode": "systemd", "scope": "system" if root else "user", "path": str(path)}


def _cron_lines(home: Path) -> list[str]:
    run = f"{_exe()} --home {home} run --log-file {home}/worker.log >/dev/null 2>&1"
    return [f"@reboot {run} {CRON_MARK}", f"* * * * * {run} {CRON_MARK}"]


def _install_cron(home: Path, start: bool) -> dict:
    if not shutil.which("crontab"):
        raise RuntimeError("neither systemd nor cron is available; start the worker with: moth-worker run")
    current = _run(["crontab", "-l"]).stdout if _run(["crontab", "-l"]).returncode == 0 else ""
    keep = [l for l in current.splitlines() if CRON_MARK not in l]
    p = subprocess.run(["crontab", "-"], input="\n".join(keep + _cron_lines(home)) + "\n", text=True,
                       capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"could not install the cron entries: {p.stderr.strip()}")
    if start:
        subprocess.Popen([*_exe().split(), "--home", str(home), "run", "--log-file", str(home / "worker.log")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    return {"mode": "cron"}


def _install_launchd(home: Path, start: bool) -> dict:
    path = Path.home() / "Library/LaunchAgents/dev.mothcode.worker.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PLIST.format(exe=_exe(), home=home))
    if start:
        _run(["launchctl", "unload", str(path)])
        _run(["launchctl", "load", "-w", str(path)])
    return {"mode": "launchd", "path": str(path)}


def _is_admin_windows() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        return False


def _install_task(home: Path, start: bool) -> dict:
    pyw = Path(sys.executable).with_name("pythonw.exe")
    py = str(pyw if pyw.exists() else Path(sys.executable))
    tr = f'"{py}" -m moth_worker.cli --home "{home}" run --supervise --log-file "{home}\\worker.log"'
    admin = _is_admin_windows()
    cmd = ["schtasks", "/Create", "/F", "/TN", TASK, "/TR", tr, "/RL", "LIMITED"]
    cmd += ["/SC", "ONSTART", "/RU", "SYSTEM"] if admin else ["/SC", "ONLOGON"]
    p = _run(cmd)
    if p.returncode != 0:
        raise RuntimeError(f"could not create the scheduled task: {(p.stderr or p.stdout).strip()}")
    if start:
        _run(["schtasks", "/Run", "/TN", TASK])
    return {"mode": "task", "trigger": "startup" if admin else "logon"}


def cmd_install_service(args) -> int:
    home = Path(args.home or default_dir())
    start = not args.no_start
    mode = args.mode
    root = os.name != "nt" and os.geteuid() == 0
    if mode == "auto":
        if os.name == "nt":
            mode = "task"
        elif sys.platform == "darwin":
            mode = "launchd"
        elif shutil.which("systemctl") and (root or _systemd_user_ok()) and Path("/run/systemd/system").exists():
            mode = "systemd"
        else:
            mode = "cron"
    try:
        info = {"systemd": lambda: _install_systemd(home, root, start), "cron": lambda: _install_cron(home, start),
                "launchd": lambda: _install_launchd(home, start), "task": lambda: _install_task(home, start)}[mode]()
    except RuntimeError as e:
        print(f"Automatic start was not set up: {e}")
        return 1
    _record(home, info)
    how = {"systemd": "a systemd service", "cron": "cron (at boot and checked every minute)",
           "launchd": "a macOS LaunchAgent", "task": "a Windows scheduled task"}[info["mode"]]
    print(f"MOTH Worker starts automatically through {how} and is restarted if it stops. "
          f"Log: {home / 'worker.log' if info['mode'] != 'systemd' else 'journalctl ' + ('-u' if root else '--user -u') + ' moth-worker'}")
    return 0


# ---- uninstall -------------------------------------------------------------------------------------
def _remove_service(home: Path) -> None:
    try:
        info = json.loads((home / "service.json").read_text())
    except (OSError, ValueError):
        info = {}
    mode = info.get("mode")
    if mode == "systemd":
        cmd = ["systemctl"] if info.get("scope") == "system" else ["systemctl", "--user"]
        _run(cmd + ["disable", "--now", "moth-worker"])
        Path(info["path"]).unlink(missing_ok=True)
        _run(cmd + ["daemon-reload"])
    elif mode == "launchd":
        _run(["launchctl", "unload", "-w", info["path"]])
        Path(info["path"]).unlink(missing_ok=True)
    elif mode == "task":
        _run(["schtasks", "/End", "/TN", TASK])
        _run(["schtasks", "/Delete", "/F", "/TN", TASK])
    if shutil.which("crontab"):  # also catches cron entries from older installs
        cur = _run(["crontab", "-l"])
        if cur.returncode == 0 and CRON_MARK in cur.stdout:
            keep = [l for l in cur.stdout.splitlines() if CRON_MARK not in l]
            subprocess.run(["crontab", "-"], input="\n".join(keep) + ("\n" if keep else ""), text=True)


def _stop_running(home: Path) -> None:
    try:
        pid = int((home / "worker.pid").read_text())
    except (OSError, ValueError):
        return
    if pid == os.getpid():
        return
    try:
        if os.name == "nt":
            _run(["taskkill", "/PID", str(pid), "/T", "/F"])
        else:
            import signal

            os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def cmd_uninstall(args) -> int:
    home = Path(args.home or default_dir())
    if not args.yes:
        if input("Remove MOTH Worker from this computer? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing was changed.")
            return 1
    _remove_service(home)
    _stop_running(home)
    try:
        from moth_worker.client import WorkerClient

        cfg = WorkerConfig.load(home)
        WorkerClient(cfg.server, cfg.token).leave()
        print(f"Worker #{cfg.worker_id} was removed from {cfg.server}.")
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001 — offline: the Owner can revoke it in MOTH Code
        print(f"Could not reach MOTH Cloud to remove the worker ({e}); remove it in MOTH Code → Workers.")
    if args.keep_files:
        (home / "config.json").unlink(missing_ok=True)
        print("Stopped and revoked; files kept.")
        return 0
    venv = Path(sys.prefix)
    ours = (venv.name == "venv" and venv.parent.name in ("moth-worker", "worker")) or str(venv) == "/opt/moth-worker"
    targets = [home] + ([venv] if ours and venv.exists() and home not in venv.parents and venv != home else [])
    if os.name == "nt":
        # Files of running programs cannot be deleted on Windows: stop every other process started from the
        # worker's environment (e.g. the scheduled task's supervisor), then delete — retrying — after exit.
        paths = ", ".join("'" + str(t).replace("'", "''") + "'" for t in targets)
        ps = (f"$t = @({paths}); foreach ($p in Get-Process) {{ if ($p.Id -ne {os.getpid()} -and $p.Path) {{ "
              "foreach ($d in $t) { if ($p.Path -like ($d + '*')) { Stop-Process -Id $p.Id -Force "
              "-ErrorAction SilentlyContinue } } } }; "
              f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue; "
              "for ($i = 0; $i -lt 30; $i++) { foreach ($d in $t) { Remove-Item -Recurse -Force $d "
              "-ErrorAction SilentlyContinue }; if (-not ($t | Where-Object { Test-Path $_ })) { break }; Start-Sleep 1 }; "
              "if ($t | Where-Object { Test-Path $_ }) { 'not removed: ' + (($t | Where-Object { Test-Path $_ }) -join ', ') "
              "} else { 'removed' }")
        ps = f"& {{ {ps} }} *> (Join-Path $env:TEMP 'moth-worker-uninstall.log')"
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", ps],
                         creationflags=0x08000000 | 0x00000008)  # no window, detached
    else:
        for t in targets:
            shutil.rmtree(t, ignore_errors=True)
    print("MOTH Worker was removed from this computer.")
    return 0
