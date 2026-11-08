"""This computer as a MOTH training participant (0.5.3 unified training).

MOTH Code can contribute its computer to the same training network as the MOTH workers: it enrolls once
with the signed-in account (a worker credential stored in the app's settings), then runs the *same*
worker loop the standalone MOTH Worker runs — claim a job that fits this computer, download the verified
weights and data, train, return the verified update — in a background thread. Jobs are evolution
experiments and distributed-training shards of the one MOTH lineage, so this computer, the cloud and the
workers train one model together.

Stopping (switch off, quitting the app) checkpoints the job; it resumes when contribution is switched on
again, or another participant takes it over after its lease expires. Worker self-updates are off here:
MOTH Code updates itself.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

import httpx


class ParticipantError(RuntimeError):
    pass


def available() -> bool:
    try:
        import moth_worker  # noqa: F401

        return True
    except ImportError:
        return False


class Participant:
    def __init__(self, home: Path, account: Callable[[], dict | None], get_setting: Callable[[str], Any],
                 set_setting: Callable[[str, Any], None], publish: Callable[[str, dict], None],
                 http_factory: Callable[[str], httpx.Client] | None = None):
        self.dir = Path(home) / "participant"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.account = account
        self.get_setting, self.set_setting, self.publish = get_setting, set_setting, publish
        self.http_factory = http_factory or (lambda base: httpx.Client(base_url=base, timeout=120.0))
        self.runner = None
        self.thread: threading.Thread | None = None
        self.log_lines: deque[str] = deque(maxlen=60)
        self.completed = 0
        self.error: str | None = None
        self.authorized_session: tuple[str, str] | None = None

    def _cfg(self) -> dict[str, Any]:
        return self.get_setting("participant") or {}

    def log(self, msg: str) -> None:
        self.log_lines.append(f"{time.strftime('%H:%M:%S')} {msg}")
        self.publish("participant", {"kind": "log", "line": self.log_lines[-1]})

    def status(self) -> dict[str, Any]:
        cfg = self._cfg()
        r = self.runner
        return {"available": available(), "enabled": bool(cfg.get("enabled")), "running": bool(self.thread and
                self.thread.is_alive()), "worker_id": cfg.get("worker_id"), "server": cfg.get("server"),
                "job": r.current_job if r else None, "progress": r.progress if r else None,
                "paused_by_owner": bool(r and r.paused), "completed_jobs": self.completed, "error": self.error,
                "log": list(self.log_lines)[-15:]}

    def _enroll(self, server: str, token: str) -> dict[str, Any]:
        """One-time enrollment of this computer with the signed-in account."""
        from moth_worker import __version__
        from moth_worker.client import WorkerClient
        from moth_worker.hardware import detect, machine_id

        with self.http_factory(server) as http:
            r = http.post("/v1/training/enrollments", json={"name": "MOTH Code on this computer"},
                          headers={"Authorization": f"Bearer {token}"})
            if r.status_code >= 400:
                raise ParticipantError(r.json().get("detail") if r.headers.get("content-type", "").startswith(
                    "application/json") else f"enrollment failed (HTTP {r.status_code})")
            enroll_token = r.json()["token"]
        hw = {**detect(), "machine_id": machine_id(), "client": "moth-code"}
        res = WorkerClient(server).enroll(enroll_token, hw, __version__)
        cfg = {**self._cfg(), "server": server, "worker_id": res["worker_id"], "worker_token": res["worker_token"]}
        self.set_setting("participant", cfg)
        return cfg

    def enable(self) -> dict[str, Any]:
        if not available():
            raise ParticipantError("This build of MOTH Code cannot train for the network (MOTH Worker is missing).")
        acct = self.account() or {}
        server = (acct.get("server_url") or "").rstrip("/")
        if not acct.get("token") or not server:
            raise ParticipantError("Sign in to MOTH Cloud first.")
        with self.http_factory(server) as http:
            response = http.get("/v1/me", headers={"Authorization": f"Bearer {acct['token']}"})
            if response.status_code != 200:
                raise ParticipantError("Verify your signed-in account before authorizing this computer.")
            user = response.json()
            uid = (user.get("user") or user).get("id")
        if not uid:
            raise ParticipantError("The server did not return a verified account identity.")
        from moth_worker.hardware import machine_id
        identity = {"account_id": uid, "device_id": machine_id()}
        cfg = self._cfg()
        if any(cfg.get(k) != v for k, v in identity.items()):
            self.disable()
            if self.thread and self.thread.is_alive():
                raise ParticipantError("Previous contribution is still checkpointing; retry after it stops.")
            cfg = {"enabled": False}
            self.set_setting("participant", cfg)
        if cfg.get("server") != server or not cfg.get("worker_token"):
            cfg = self._enroll(server, acct["token"])
        self.set_setting("participant", {**cfg, **identity, "enabled": True})
        self.authorized_session = (server, acct["token"])
        self.start()
        return self.status()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        cfg = self._cfg()
        acct = self.account() or {}
        if not self.authorized_session or self.authorized_session != ((acct.get("server_url") or "").rstrip("/"), acct.get("token")):
            self.disable()
            return
        if not cfg.get("enabled") or not cfg.get("worker_token"):
            return
        from moth_worker.client import WorkerClient
        from moth_worker.runner import WorkerRunner

        client = WorkerClient(cfg["server"], cfg["worker_token"])
        self.runner = WorkerRunner(client, self.dir, log=self.log, heartbeat_seconds=30.0, update_check_seconds=None)
        detected = self.runner.hardware
        self.runner.hardware = lambda: {**detected(), "client": "moth-code"}  # shown as "this app" to the Owner
        self.error = None

        def loop() -> None:
            try:
                self.log("contributing this computer to MOTH training")
                self.completed += self.runner.run(idle_sleep=20.0)
            except Exception as e:  # noqa: BLE001 - reported in the app
                self.error = f"{type(e).__name__}: {e}"
                self.log(f"stopped: {self.error}")
            finally:
                if self.runner and self.runner.revoked:
                    self.set_setting("participant", {"enabled": False})
                    self.error = "This computer's training credential was revoked; switch on again to re-enroll."
                self.publish("participant", {"kind": "status", **self.status()})

        self.thread = threading.Thread(target=loop, daemon=True, name="moth-participant")
        self.thread.start()

    def disable(self) -> dict[str, Any]:
        self.authorized_session = None
        self.set_setting("participant", {**self._cfg(), "enabled": False})
        self.stop()
        return self.status()

    def stop(self, wait: float = 15.0) -> None:
        if self.runner:
            self.runner.stop_event.set()
        if self.thread:
            self.thread.join(timeout=wait)
