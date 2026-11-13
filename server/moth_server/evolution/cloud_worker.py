"""MOTH Cloud's own worker (0.7.2): the server trains together with the external workers.

MOTH Cloud enrolls itself once as a ``cloud`` worker (named "MOTH Cloud server", owned by the Owner)
and runs the ordinary MOTH Worker loop in a background thread, talking to this server in-process. It
therefore takes part in exactly the same verified work as every other worker — distributed training
rounds (its weight deltas are checked and averaged like anyone's), dataset preparation chunks and
held-out evaluations — with the same leases, checksums and acceptance rules.

It works only while the Owner allows it: AI Settings → What trains MOTH → "MOTH Cloud server"
(``backends.local_cpu``/``local_gpu``) and ``distributed.cloud_participates`` (default on). It pauses
whenever MOTH Cloud is running a local experiment of its own, so the server never trains two things at
once, and it respects the usual resource pressure checks. If the Owner revokes it in Network, it stays
revoked (it never re-enrolls by itself). ``MOTH_CLOUD_WORKER=0`` turns it off entirely.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path

from moth_server.context import Ctx

log = logging.getLogger("moth_server.cloud_worker")
NAME = "MOTH Cloud server"


def allowed(ctx: Ctx) -> bool:
    from moth_server.evolution import settings as S

    s = S.get(ctx)
    be = s.get("backends") or {}
    return bool((be.get("local_cpu") or be.get("local_gpu")) and (s.get("distributed") or {}).get("cloud_participates", True)
                and not ctx.db.get_config("cloud_worker_revoked", False))


def local_busy(ctx: Ctx) -> bool:
    from moth_server.evolution import memory as MEM

    return any(e.get("backend") == "local" and e["status"] in ("running", "paused")
               for e in MEM.experiments(ctx, limit=50))


def _import_worker():
    try:
        import moth_worker  # noqa: F401
    except ImportError:  # release layout: <release>/server/moth_server and <release>/worker/moth_worker
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "worker"))
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    return WorkerClient, WorkerRunner


def credential(ctx: Ctx) -> str | None:
    """This server's worker credential (enrolled once with the Owner's account)."""
    from sqlalchemy import select

    from moth_server import training as T
    from moth_server.db import users

    f = Path(ctx.settings.data_dir) / "cloud-worker" / "credential"
    if f.exists():
        return f.read_text().strip() or None
    owner = ctx.db.one(select(users).where(users.c.role == "owner", users.c.status == "active"))
    if not owner:
        return None
    from moth_worker import __version__  # noqa: F401 — imported via _import_worker

    token = T.create_enrollment(ctx, dict(owner), NAME, None, kind="cloud")
    from moth_worker.hardware import detect

    # no machine id: a real worker on the same computer must never replace (revoke) this one or vice versa
    hw = {k: v for k, v in detect().items() if k != "machine_id"}
    _, cred = T.enroll_worker(ctx, token, {**hw, "name": NAME}, __version__)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(cred)
    os.chmod(f, 0o600)
    return cred


def make_runner(ctx: Ctx, http):
    WorkerClient, WorkerRunner = _import_worker()

    class CloudRunner(WorkerRunner):
        def hardware(self):
            return {k: v for k, v in super().hardware().items() if k != "machine_id"}

        def beat(self) -> None:
            super().beat()
            if not allowed(ctx) or local_busy(ctx):
                self.paused = True

    cred = credential(ctx)
    if not cred:
        return None
    return CloudRunner(WorkerClient("http://moth-cloud.internal", cred, http=http),
                       Path(ctx.settings.data_dir) / "cloud-worker", allow_cpu=True,
                       log=lambda m: log.info("%s", m), heartbeat_seconds=30, update_check_seconds=None)


def start(ctx: Ctx, delay: float = 20.0) -> threading.Thread | None:
    if os.environ.get("MOTH_CLOUD_WORKER", "1") == "0" or ctx.extras.get("disable_background"):
        return None

    def loop():
        time.sleep(delay)
        from starlette.testclient import TestClient  # in-process: no network, same verification path

        http = None
        while True:
            try:
                if not allowed(ctx):
                    time.sleep(60)
                    continue
                http = http or TestClient(ctx.extras["app"])
                runner = make_runner(ctx, http)
                if runner is None:
                    time.sleep(60)
                    continue
                runner.run(idle_sleep=15.0)  # returns when revoked or stopped
                if runner.revoked:
                    ctx.db.set_config("cloud_worker_revoked", True)  # the Owner's decision stands
                    log.info("the MOTH Cloud worker was revoked; it will not re-enroll")
            except Exception:  # noqa: BLE001 — the server keeps running; try again later
                log.exception("MOTH Cloud worker stopped unexpectedly")
            time.sleep(60)

    t = threading.Thread(target=loop, daemon=True, name="moth-cloud-worker")
    t.start()
    return t
