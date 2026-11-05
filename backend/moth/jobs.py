"""Background jobs that run ``moth`` CLI subcommands in isolated subprocesses.

Isolation means a crash, CUDA error or out-of-memory condition in training
cannot take down the desktop backend. Jobs stop gracefully through a stop
file (the trainer checkpoints first) and are force-killed only as a fallback.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from moth.cli import EVENT_PREFIX
from moth.workspace.terminal import kill_tree


def cli_command(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):  # PyInstaller build: the executable dispatches subcommands
        return [sys.executable, *args]
    return [sys.executable, "-m", "moth.cli", *args]


@dataclass
class Job:
    id: str
    kind: str
    title: str
    status: str = "running"  # running | completed | failed | cancelled
    progress: float | None = None
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)
    finished: float | None = None
    logs: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _stop_file: Path | None = field(default=None, repr=False)

    def public(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_") and k != "logs"} | {
            "logs": self.logs[-50:]}


class JobManager:
    def __init__(self, work_dir: Path, publish: Callable[[str, dict], None]):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.publish = publish
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, kind: str, title: str, args: list[str], meta: dict[str, Any] | None = None,
              on_event: Callable[[Job, dict], None] | None = None, stop_file: Path | None = None) -> Job:
        job = Job(uuid.uuid4().hex[:12], kind, title, meta=meta or {})
        job._stop_file = stop_file or (self.work_dir / f"{job.id}.stop")
        job._stop_file.unlink(missing_ok=True)
        cmd = cli_command("--json-events", *args)
        if kind != "train" and "--stop-file" not in args and args and args[0] in ("tokenizer", "prepare"):
            cmd += ["--stop-file", str(job._stop_file)]
        kwargs: dict[str, Any] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        backend_root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = backend_root + os.pathsep + env.get("PYTHONPATH", "")
        job._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", errors="replace", env=env, **kwargs)
        with self._lock:
            self.jobs[job.id] = job
        self.publish("job", {"job": job.public()})
        threading.Thread(target=self._pump, args=(job, on_event), daemon=True, name=f"job-{job.id}").start()
        return job

    def _pump(self, job: Job, on_event) -> None:
        assert job._proc and job._proc.stdout
        last_publish = 0.0
        for line in job._proc.stdout:
            line = line.rstrip("\n")
            if line.startswith(EVENT_PREFIX):
                try:
                    event = json.loads(line[len(EVENT_PREFIX):])
                except json.JSONDecodeError:
                    continue
                kind = event.get("kind")
                if kind == "progress" and event.get("total"):
                    job.progress = event["done"] / event["total"]
                if kind == "metrics" and event.get("max_steps"):
                    job.progress = event["step"] / event["max_steps"]
                if kind in ("status", "progress"):
                    job.message = event.get("message") or _summ(event)
                if kind == "done":
                    job.result = event
                if kind in ("error", "cancelled"):
                    job.error = event.get("message")
                if on_event:
                    try:
                        on_event(job, event)
                    except Exception:
                        pass
                if kind != "progress" or time.time() - last_publish > 0.5:
                    last_publish = time.time()
                    self.publish("job", {"job": job.public(), "event": event})
            else:
                job.logs.append(line)
                if len(job.logs) > 500:
                    del job.logs[:250]
        code = job._proc.wait()
        job.finished = time.time()
        if job.status == "cancelled" or (job._stop_file and job._stop_file.exists()):
            job.status = "cancelled"
        elif code == 0:
            job.status = "completed"
            job.progress = 1.0
        else:
            job.status = "failed"
            job.error = job.error or "\n".join(job.logs[-15:]) or f"exit code {code}"
        if job._stop_file:
            job._stop_file.unlink(missing_ok=True)
        if on_event:
            try:
                on_event(job, {"kind": "exit", "status": job.status})
            except Exception:
                pass
        self.publish("job", {"job": job.public()})

    def stop(self, job_id: str, grace: float = 60.0) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.status != "running" or not job._proc:
            return False
        job.status = "cancelled"
        if job._stop_file:
            job._stop_file.parent.mkdir(parents=True, exist_ok=True)
            job._stop_file.touch()

        def enforce() -> None:
            try:
                job._proc.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                kill_tree(job._proc)

        threading.Thread(target=enforce, daemon=True).start()
        return True

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        return [j.public() for j in sorted(self.jobs.values(), key=lambda j: -j.created)]

    def running(self, kind: str | None = None) -> list[Job]:
        return [j for j in self.jobs.values() if j.status == "running" and (kind is None or j.kind == kind)]

    def shutdown(self) -> None:
        for j in self.running():
            self.stop(j.id, grace=10)


def _summ(event: dict) -> str:
    if "done" in event and "total" in event:
        return f"{event['done']}/{event['total']}"
    if "tokens" in event:
        return f"{event.get('documents', 0)} documents, {event['tokens']} tokens"
    return ""
