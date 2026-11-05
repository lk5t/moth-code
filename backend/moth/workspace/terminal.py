"""Integrated terminal: streamed command execution with cancellation.

v0.1 runs each command as its own process in the session's working directory
(``cd`` is handled by the session so it persists). This works identically on
Windows and POSIX and is fully cancellable (the whole process tree is killed).
It is not a full PTY: interactive full-screen programs are not supported yet.
"""

from __future__ import annotations

import codecs
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

IS_WINDOWS = sys.platform == "win32"
OutputCallback = Callable[[str], None]


def default_shell() -> list[str]:
    """Return the argv prefix used to run a command string."""
    if IS_WINDOWS:
        pwsh = shutil.which("pwsh") or shutil.which("powershell")
        if pwsh:
            return [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c"]
    return [os.environ.get("MOTH_SHELL") or ("/bin/bash" if Path("/bin/bash").exists() else "/bin/sh"), "-c"]


def _wrap_command(shell: list[str], command: str) -> list[str]:
    exe = Path(shell[0]).name.lower()
    if exe.startswith(("powershell", "pwsh")):
        command = "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; " + command
    return [*shell, command]


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        proc.kill()
    except OSError:
        pass


@dataclass
class CommandResult:
    command: str
    cwd: str
    exit_code: int | None
    output: str
    duration: float
    cancelled: bool = False
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.cancelled and not self.timed_out


def run_command(
    command: str,
    cwd: str | Path,
    on_output: OutputCallback | None = None,
    timeout: float | None = None,
    cancel_event: threading.Event | None = None,
    env: dict[str, str] | None = None,
    shell: list[str] | None = None,
    max_output: int = 1_000_000,
) -> CommandResult:
    """Run ``command`` to completion, streaming output. Cancellable and time-limited."""
    start = time.time()
    full_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1", **(env or {})}
    kwargs: dict = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        _wrap_command(shell or default_shell(), command),
        cwd=str(cwd), env=full_env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs,
    )
    chunks: list[str] = []
    size = 0
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def reader() -> None:
        nonlocal size
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read1(8192) if hasattr(proc.stdout, "read1") else proc.stdout.read(8192)
            if not data:
                break
            text = decoder.decode(data)
            if text:
                if size < max_output:
                    chunks.append(text)
                    size += len(text)
                if on_output:
                    on_output(text)
        tail = decoder.decode(b"", final=True)
        if tail:
            chunks.append(tail)
            if on_output:
                on_output(tail)

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    cancelled = timed_out = False
    while proc.poll() is None:
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            kill_tree(proc)
            break
        if timeout is not None and time.time() - start > timeout:
            timed_out = True
            kill_tree(proc)
            break
        time.sleep(0.05)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        kill_tree(proc)
    t.join(timeout=5)
    output = "".join(chunks)
    if size >= max_output:
        output += "\n[output truncated]\n"
    return CommandResult(command, str(cwd), proc.returncode, output, time.time() - start, cancelled, timed_out)


_CD_RE = re.compile(r"^\s*(cd|chdir|set-location|sl)(\s+(?P<arg>.+?))?\s*$", re.IGNORECASE)


@dataclass
class TerminalSession:
    id: str
    cwd: Path
    root: Path | None = None  # when set, ``cd`` cannot leave this directory
    running: dict | None = None
    history: list[str] = field(default_factory=list)
    _cancel: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def change_dir(self, arg: str | None) -> str:
        target = Path(arg.strip().strip('"').strip("'")).expanduser() if arg else (self.root or Path.home())
        if not target.is_absolute():
            target = self.cwd / target
        target = target.resolve()
        if not target.is_dir():
            raise FileNotFoundError(f"cd: no such directory: {arg}")
        if self.root is not None:
            try:
                target.relative_to(self.root)
            except ValueError:
                raise PermissionError(f"cd: {target} is outside the workspace {self.root}") from None
        self.cwd = target
        return str(target)

    def execute(self, command: str, on_output: OutputCallback, on_exit: Callable[[CommandResult], None],
                timeout: float | None = None) -> bool:
        """Run in a background thread. Returns False if a command is already running."""
        with self._lock:
            if self.running is not None:
                return False
            self.history.append(command)
            m = _CD_RE.match(command)
            if m and not any(c in command for c in "&|;"):
                try:
                    cwd = self.change_dir(m.group("arg"))
                    on_exit(CommandResult(command, cwd, 0, "", 0.0))
                except (OSError, PermissionError) as e:
                    on_output(str(e) + "\n")
                    on_exit(CommandResult(command, str(self.cwd), 1, str(e), 0.0))
                return True
            self._cancel = threading.Event()
            self.running = {"command": command, "started": time.time()}
            cancel = self._cancel

        def work() -> None:
            try:
                result = run_command(command, self.cwd, on_output, timeout, cancel)
            except Exception as e:  # e.g. shell not found
                on_output(f"failed to start command: {e}\n")
                result = CommandResult(command, str(self.cwd), None, str(e), 0.0)
            with self._lock:
                self.running = None
            on_exit(result)

        threading.Thread(target=work, daemon=True, name=f"term-{self.id}").start()
        return True

    def cancel(self) -> bool:
        with self._lock:
            if self.running is None:
                return False
            self._cancel.set()
            return True


class TerminalManager:
    def __init__(self) -> None:
        self.sessions: dict[str, TerminalSession] = {}
        self._lock = threading.Lock()

    def create(self, cwd: Path | str, root: Path | str | None = None) -> TerminalSession:
        s = TerminalSession(uuid.uuid4().hex[:12], Path(cwd).resolve(), Path(root).resolve() if root else None)
        with self._lock:
            self.sessions[s.id] = s
        return s

    def get(self, sid: str) -> TerminalSession | None:
        return self.sessions.get(sid)

    def close(self, sid: str) -> None:
        with self._lock:
            s = self.sessions.pop(sid, None)
        if s:
            s.cancel()

    def close_all(self) -> None:
        for sid in list(self.sessions):
            self.close(sid)
