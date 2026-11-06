"""``moth-worker`` command line: detect, enroll, run, status, install-service, uninstall."""

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
    from moth_worker.service import log_to_file, single_instance, supervise

    from moth_worker import updater

    home = Path(args.home or default_dir())
    if args.supervise:  # Windows scheduled task: restart the worker if it ever stops
        return supervise(home, [a for a in sys.argv[1:] if a != "--supervise"])
    lock = single_instance(home)
    if lock is None:
        return 0  # already running (cron starts it every minute; this keeps exactly one)
    if args.log_file:
        log_to_file(Path(args.log_file))
    (home / "worker.pid").write_text(str(os.getpid()))
    cfg = WorkerConfig.load(home)
    guard = updater.startup_guard(home, log=lambda m: print(m, flush=True))
    if guard and guard.get("reverted"):
        updater.restart(sys.argv[1:])  # start the restored previous version
    runner = WorkerRunner(WorkerClient(cfg.server, cfg.token), home, allow_cpu=cfg.allow_cpu,
                          log=lambda m: print(m, flush=True),
                          update_check_seconds=None if args.no_auto_update else
                          float(os.environ.get("MOTH_WORKER_UPDATE_CHECK_SECONDS", "1800")))
    print(f"MOTH Worker {__version__} running (worker #{cfg.worker_id}, server {cfg.server}).", flush=True)
    runner.run(max_jobs=args.max_jobs)
    if runner.updated_to:
        updater.restart(sys.argv[1:])  # same command line, new version (via reexec_into_current)
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


from moth_worker.service import cmd_install_service, cmd_uninstall  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    from moth_worker import updater

    raw = list(sys.argv[1:] if argv is None else argv)
    home_arg = raw[raw.index("--home") + 1] if "--home" in raw[:-1] else None
    updater.reexec_into_current(Path(home_arg or default_dir()), raw)  # newest installed version runs
    p = argparse.ArgumentParser(prog="moth-worker")
    p.add_argument("--home", help="state directory (default: /var/lib/moth-worker as root, %%LOCALAPPDATA%%\\MOTH\\worker on "
                                  "Windows, else ~/.local/share/moth-worker)")
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
    r.add_argument("--no-auto-update", action="store_true", help="don't install updates offered by MOTH Cloud")
    r.add_argument("--log-file", help="write the log to this file (rotated at 5 MB)")
    r.add_argument("--supervise", action="store_true", help="keep restarting the worker if it stops (Windows task)")
    r.set_defaults(fn=cmd_run)
    s = sub.add_parser("status")
    s.set_defaults(fn=cmd_status)
    i = sub.add_parser("install-service", help="start the worker automatically at boot and after crashes")
    i.add_argument("--mode", default="auto", choices=["auto", "systemd", "cron", "launchd", "task"])
    i.add_argument("--no-start", action="store_true")
    i.set_defaults(fn=cmd_install_service)
    u = sub.add_parser("uninstall", help="stop the worker, remove its automatic start, revoke it and delete its files")
    u.add_argument("--keep-files", action="store_true", help="keep the worker's files (only stop and revoke)")
    u.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    u.set_defaults(fn=cmd_uninstall)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
