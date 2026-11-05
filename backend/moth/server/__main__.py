"""Entry point: ``python -m moth.server``.

Binds to 127.0.0.1 on the requested port (``MOTH_PORT``; 0 = any free port)
and prints ``MOTH_BACKEND_READY {"port": N}`` on stdout once listening so the
desktop shell knows where to connect.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time

import uvicorn

from moth.config import get_paths
from moth.server.app import create_app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="moth-backend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MOTH_PORT", "0")))
    parser.add_argument("--home", default=None)
    parser.add_argument("--parent-pid", type=int, default=int(os.environ.get("MOTH_PARENT_PID", "0")))
    args = parser.parse_args(argv)

    paths = get_paths(args.home)
    app = create_app(paths)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((args.host, args.port))
    port = sock.getsockname()[1]

    config = uvicorn.Config(app, log_level="warning", lifespan="on", timeout_graceful_shutdown=5)
    server = uvicorn.Server(config)

    def announce() -> None:
        while not server.started:
            time.sleep(0.05)
        print("MOTH_BACKEND_READY " + json.dumps({"port": port, "home": str(paths.home)}), flush=True)

    threading.Thread(target=announce, daemon=True).start()
    if args.parent_pid:
        threading.Thread(target=_watch_parent, args=(args.parent_pid, server), daemon=True).start()
    server.run(sockets=[sock])
    sys.exit(0)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _watch_parent(pid: int, server: uvicorn.Server) -> None:
    """Exit when the desktop shell is gone (crash, kill, or forced quit)."""
    started_as_child = sys.platform != "win32" and os.getppid() == pid
    while True:
        time.sleep(1.5)
        # On POSIX a dead parent means we get re-parented; this also covers an unreaped (zombie) parent.
        orphaned = started_as_child and os.getppid() != pid
        if orphaned or not _pid_alive(pid):
            server.should_exit = True
            return


if __name__ == "__main__":
    main()
