"""``moth-worker`` command line: detect, enroll, run, status, install-service."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from moth_worker import __version__
from moth_worker.config import WorkerConfig, default_dir
from moth_worker.hardware import detect, requirement_problem

SERVICE = """[Unit]
Description=MOTH Worker (MOTH training network)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
Environment=MOTH_WORKER_HOME={home}
ExecStart={exe} run
Restart=always
RestartSec=15
Nice=10
{user_line}
[Install]
WantedBy={wanted}
"""


def cmd_detect(args) -> int:
    hw = detect()
    print(json.dumps(hw, indent=2))
    problem = requirement_problem(hw, args.min_vram, args.allow_cpu)
    if problem:
        print(f"\nNot supported: {problem}", file=sys.stderr)
        return 2
    print("\nThis machine can run MOTH Worker.")
    return 0


def cmd_enroll(args) -> int:
    from moth_worker.client import ServerError, WorkerClient

    home = Path(args.home or default_dir())
    hw = detect()
    problem = requirement_problem(hw, args.min_vram, args.allow_cpu)
    if problem:
        print(f"Cannot enroll: {problem}", file=sys.stderr)
        return 2
    try:
        r = WorkerClient(args.server).enroll(args.token, hw, __version__)
    except ServerError as e:
        print(f"Enrollment failed: {e}", file=sys.stderr)
        return 1
    WorkerConfig(server=args.server.rstrip("/"), worker_id=r["worker_id"], token=r["worker_token"], name=args.name or "",
                 allow_cpu=args.allow_cpu).save(home)
    print(f"Enrolled as worker #{r['worker_id']}. Credentials saved to {home / 'config.json'} (mode 600).")
    return 0


def cmd_run(args) -> int:
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    home = Path(args.home or default_dir())
    cfg = WorkerConfig.load(home)
    runner = WorkerRunner(WorkerClient(cfg.server, cfg.token), home, allow_cpu=cfg.allow_cpu,
                          log=lambda m: print(m, flush=True))
    print(f"MOTH Worker {__version__} running (worker #{cfg.worker_id}, server {cfg.server}).", flush=True)
    runner.run(max_jobs=args.max_jobs)
    return 0 if not runner.revoked else 3


def cmd_status(args) -> int:
    home = Path(args.home or default_dir())
    try:
        cfg = WorkerConfig.load(home)
    except FileNotFoundError:
        print("Not enrolled.")
        return 1
    print(f"Worker #{cfg.worker_id} → {cfg.server}")
    return 0


def cmd_install_service(args) -> int:
    if not shutil.which("systemctl"):
        print("systemd not found; start the worker with:  moth-worker run   (e.g. inside tmux or screen)")
        return 0
    home = Path(args.home or default_dir())
    exe = shutil.which("moth-worker") or f"{sys.executable} -m moth_worker.cli"
    root = os.geteuid() == 0
    unit = SERVICE.format(home=home, exe=exe, user_line="", wanted="multi-user.target" if root else "default.target")
    if root:
        path = Path("/etc/systemd/system/moth-worker.service")
        cmd = ["systemctl"]
    else:
        path = Path.home() / ".config/systemd/user/moth-worker.service"
        cmd = ["systemctl", "--user"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit)
    if args.no_start:
        print(f"Wrote {path}")
        return 0
    for c in (["daemon-reload"], ["enable", "--now", "moth-worker"]):
        subprocess.run(cmd + c, check=False)
    print(f"Installed and started {path}. Logs: journalctl {'-u' if root else '--user -u'} moth-worker -f")
    if not root:
        print("To keep the worker running after you log out:  loginctl enable-linger $USER")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="moth-worker")
    p.add_argument("--home", help="state directory (default: /var/lib/moth-worker as root, else ~/.local/share/moth-worker)")
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect", help="show detected hardware and whether it is supported")
    d.add_argument("--min-vram", type=float, default=8.0)
    d.add_argument("--allow-cpu", action="store_true", help=argparse.SUPPRESS)
    d.set_defaults(fn=cmd_detect)
    e = sub.add_parser("enroll", help="enroll this machine with a one-time token from MOTH Code")
    e.add_argument("--server", required=True)
    e.add_argument("--token", required=True)
    e.add_argument("--name")
    e.add_argument("--min-vram", type=float, default=8.0)
    e.add_argument("--allow-cpu", action="store_true", help=argparse.SUPPRESS)  # development/testing only
    e.set_defaults(fn=cmd_enroll)
    r = sub.add_parser("run", help="run the worker loop")
    r.add_argument("--max-jobs", type=int)
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)
    i = sub.add_parser("install-service", help="install and start the systemd service")
    i.add_argument("--no-start", action="store_true")
    i.set_defaults(fn=cmd_install_service)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
