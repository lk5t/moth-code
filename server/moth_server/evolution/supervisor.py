"""Self-healing supervisor (0.9.0): MOTH Cloud watches itself and repairs what it knows how to repair.

Every minute it checks for the states that have stopped MOTH in practice and applies a known remedy:

* **Evolution loop** stopped (its thread died) → started again. A loop that is alive but has not
  finished a round for a long time cannot be killed safely, so it is woken and reported instead.
* **Model pipeline** stopped → started again.
* **No serving model** although one is deployed → loaded again (or the rollback model of the same line).
* **MOTH Cloud's built-in worker** stopped or failing for 10 minutes → started again.
* **Disk nearly full** → safe cleanup of what can be removed (finished run folders, superseded data
  preparations, rejected candidates; download caches only if still short). Protected items — the
  deployed model, rollback versions, data and checkpoints in use — are never touched (storage.py).
* **A cycle that has not changed for hours** while nothing is running → the engine is woken.
* **A data preparation with no progress for 2 hours** → marked failed so it is retried.

Each repair is recorded (``supervisor_log``) and shown on the Owner's diagnostics page. A problem
repaired three times within an hour is reported as an error event: it keeps coming back, so a person
should look. Nothing here runs a Genesis Reset, deletes user data or changes the Owner's settings.

The diagnostics page also shows recent warnings and errors from the server's own log (credentials and
personal data are redacted before they are kept).
"""

from __future__ import annotations

import collections
import logging
import threading
import time
from typing import Any, Callable

from moth_server.context import Ctx

log = logging.getLogger("moth_server.supervisor")
INTERVAL = 60.0
LOOP_STALE_SECONDS = 1800.0       # an alive loop without a finished round for this long is reported
CLOUD_WORKER_GRACE = 600.0        # the built-in worker may fail this long before it is restarted
CYCLE_IDLE_SECONDS = 3 * 3600.0   # a cycle unchanged this long, with nothing running, is woken
BUILD_STALE_SECONDS = 2 * 3600.0  # a data preparation without progress this long is retried
REPEAT_WINDOW, REPEAT_LIMIT = 3600.0, 3
LOG_KEY = "supervisor_log"


# ---- loop heartbeats and the error ring -------------------------------------------------------------
def beat(ctx: Ctx, name: str) -> None:
    """Background loops call this after each round."""
    ctx.extras.setdefault("loop_beats", {})[name] = time.time()


class RingHandler(logging.Handler):
    """Keeps the last warnings and errors of the server's own log, redacted, for the diagnostics page."""

    def __init__(self, size: int = 200):
        super().__init__(level=logging.WARNING)
        self.records: collections.deque = collections.deque(maxlen=size)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from moth.security.redaction import redact

            msg = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                msg += f" — {type(record.exc_info[1]).__name__}: {record.exc_info[1]}"
            self.records.append({"at": record.created, "level": record.levelname.lower(), "logger": record.name,
                                 "message": redact(msg)[0][:1000]})
        except Exception:  # noqa: BLE001 — logging must never fail
            pass


def ring(ctx: Ctx) -> RingHandler:
    h = ctx.extras.get("log_ring")
    if h is None:
        h = RingHandler()
        logging.getLogger("moth_server").addHandler(h)
        ctx.extras["log_ring"] = h
    return h


# ---- checks -----------------------------------------------------------------------------------------
def _thread_alive(name: str) -> bool:
    return any(t.name == name and t.is_alive() for t in threading.enumerate())


def _record(ctx: Ctx, issue: str, action: str, ok: bool, detail: str | None = None) -> dict:
    from moth_server.evolution import memory as MEM

    t = time.time()
    entries = [e for e in (ctx.db.get_config(LOG_KEY, []) or []) if t - float(e.get("at", 0)) < 7 * 86400][-99:]
    entry = {"at": t, "issue": issue, "action": action, "ok": ok, "detail": (detail or "")[:500] or None}
    entries.append(entry)
    ctx.db.set_config(LOG_KEY, entries)
    recent = [e for e in entries if e["issue"] == issue and t - e["at"] < REPEAT_WINDOW]
    if len(recent) >= REPEAT_LIMIT and not any(e.get("escalated") for e in recent[:-1]):
        entry["escalated"] = True
        ctx.db.set_config(LOG_KEY, entries)
        MEM.event(ctx, "supervisor.attention", f"MOTH keeps having the same problem: {issue}. It was repaired "
                  f"{len(recent)} times in the last hour ({action}), so it needs a closer look. Settings → Advanced → "
                  "Diagnostics has the details.", level="error", issue=issue)
    else:
        MEM.event(ctx, "supervisor.repaired", f"Self-repair: {issue} — {action}." + (f" {detail}" if detail else ""),
                  level="info" if ok else "warning", issue=issue, ok=ok)
    return entry


def _check_evolution(ctx: Ctx) -> dict | None:
    from moth_server.evolution import engine as EN, settings as S

    if not S.get(ctx).get("enabled") or ctx.extras.get("disable_background"):
        return None
    if not _thread_alive("evolution"):
        EN.start_background(ctx)
        return _record(ctx, "the Evolution loop had stopped", "started it again", _thread_alive("evolution"))
    last = (ctx.extras.get("loop_beats") or {}).get("evolution")
    started = ctx.extras.get("supervisor_started", time.time())
    if time.time() - (last or started) > LOOP_STALE_SECONDS:
        EN.wake(ctx)
        ctx.extras.setdefault("loop_beats", {})["evolution"] = time.time()  # report once per stale period
        return _record(ctx, "the Evolution loop has not finished a round for 30 minutes",
                       "woke it (a round that is still running is not interrupted)", False)
    return None


def _check_pipeline(ctx: Ctx) -> dict | None:
    if ctx.extras.get("disable_background") or "models_stop" not in ctx.extras or _thread_alive("model-pipeline"):
        return None
    from moth_server.routes import models as RM

    RM.start_pipeline(ctx)
    return _record(ctx, "the model pipeline had stopped", "started it again", _thread_alive("model-pipeline"))


def _check_serving(ctx: Ctx) -> dict | None:
    from moth_server import models as M

    if ctx.extras.get("inference_engine") is not None or not ctx.db.get_config("deployed_release", None):
        return None
    v = M.ensure_serving(ctx)
    return _record(ctx, "no model was serving although one is deployed",
                   f"loaded v{v}" if v else "tried to load the deployed or rollback model (still retrying)", bool(v))


def _check_cloud_worker(ctx: Ctx) -> dict | None:
    import os

    from moth_server.evolution import cloud_worker as CW

    if os.environ.get("MOTH_CLOUD_WORKER", "1") == "0" or ctx.extras.get("disable_background") or not CW.allowed(ctx):
        return None
    st = CW.status(ctx)
    failing = st["state"] in ("error", "re-enrolling") and time.time() - float(st.get("at") or time.time()) > CLOUD_WORKER_GRACE
    if _thread_alive("moth-cloud-worker") and not failing:
        return None
    if failing and _thread_alive("moth-cloud-worker"):
        return None  # its own loop retries every minute; restarting a second thread would double it
    CW.start(ctx, delay=1.0)
    return _record(ctx, "MOTH Cloud's built-in worker had stopped", "started it again", True, st.get("detail"))


def _check_disk(ctx: Ctx) -> dict | None:
    import shutil

    from moth_server.evolution import settings as S, storage

    reserve = float(S.get(ctx)["limits"]["min_free_disk_gb"]) * 1024 ** 3
    if shutil.disk_usage(ctx.settings.data_dir).free >= reserve:
        return None
    freed = 0
    for cats in (("runs", "data", "models"), ("cache",)):
        ids = [i["id"] for i in storage.items(ctx) if not i["protected"] and i["category"] in cats]
        if ids:
            freed += int(storage.cleanup(ctx, ids, None).get("freed_bytes") or 0)
        if shutil.disk_usage(ctx.settings.data_dir).free >= reserve:
            break
    ok = shutil.disk_usage(ctx.settings.data_dir).free >= reserve
    return _record(ctx, "the disk was nearly full", f"removed {freed / 1024 ** 3:.1f} GB of removable files", ok,
                   None if ok else "Still below the free-space reserve: only protected files remain.")


def _check_cycle(ctx: Ctx) -> dict | None:
    from moth_server.evolution import engine as EN, memory as MEM

    cyc = MEM.active_cycle(ctx)
    if not cyc or cyc["status"] in ("monitoring",):
        return None
    if any(e["status"] == "running" for e in MEM.experiments(ctx, cyc["id"])):
        return None
    if time.time() - float(cyc.get("updated_at") or time.time()) < CYCLE_IDLE_SECONDS:
        return None
    EN.wake(ctx)
    MEM.update_cycle(ctx, cyc["id"])  # touch: report once per idle period
    return _record(ctx, f"cycle #{cyc['id']} had not changed for 3 hours ({cyc['status'].replace('_', ' ')})",
                   "woke the Evolution engine", True)


def _check_build(ctx: Ctx) -> dict | None:
    from sqlalchemy import select

    from moth_server.db import library_builds, now

    for b in ctx.db.all(select(library_builds).where(library_builds.c.status == "running")):
        prog = ctx.db.get_config(f"library_progress_{b['id']}", {}) or {}
        last = float(prog.get("updated_at") or b.get("created_at") or time.time())
        if time.time() - last > BUILD_STALE_SECONDS:
            with ctx.db.tx() as c:
                c.execute(library_builds.update().where(library_builds.c.id == b["id"], library_builds.c.status == "running")
                          .values(status="failed", error="no progress for 2 hours; retried automatically",
                                  finished_at=now()))
            return _record(ctx, f"data preparation #{b['id']} made no progress for 2 hours",
                           "marked it failed so it is prepared again", True)
    return None


CHECKS: list[tuple[str, Callable[[Ctx], dict | None]]] = [
    ("evolution", _check_evolution), ("pipeline", _check_pipeline), ("serving", _check_serving),
    ("cloud_worker", _check_cloud_worker), ("disk", _check_disk), ("cycle", _check_cycle), ("build", _check_build)]


def run_checks(ctx: Ctx) -> list[dict]:
    from moth_server.evolution.native_reset import fenced

    if fenced(ctx):
        return []  # never interfere with a Genesis Reset
    done = []
    for name, check in CHECKS:
        try:
            r = check(ctx)
            if r:
                done.append(r)
        except Exception:  # noqa: BLE001 — one failing check never stops the others
            log.exception("supervisor check %s failed", name)
    beat(ctx, "supervisor")
    return done


def start(ctx: Ctx) -> threading.Thread | None:
    ring(ctx)
    if ctx.extras.get("disable_background"):
        return None
    ctx.extras["supervisor_started"] = time.time()
    stop = ctx.extras.setdefault("supervisor_stop", threading.Event())

    def loop() -> None:
        while not stop.wait(INTERVAL):
            run_checks(ctx)
            try:  # 0.9.0: the autonomous self-quiz is scheduled from here too
                from moth_server.intelligence import self_training

                self_training.maybe_run(ctx)
            except Exception:  # noqa: BLE001
                log.exception("self-training scheduling failed")

    t = threading.Thread(target=loop, daemon=True, name="moth-supervisor")
    t.start()
    return t


# ---- diagnostics -------------------------------------------------------------------------------------
def diagnostics(ctx: Ctx) -> dict[str, Any]:
    import platform
    import shutil

    from moth_server import __version__, models as M
    from moth_server.evolution import cloud_worker as CW, memory as MEM, settings as S

    t = time.time()
    beats = ctx.extras.get("loop_beats") or {}
    loops = [{"name": n, "label": label, "alive": _thread_alive(thread),
              "last_round_seconds_ago": round(t - beats[n]) if n in beats else None}
             for n, label, thread in (("evolution", "Evolution engine", "evolution"),
                                      ("pipeline", "Model pipeline", "model-pipeline"),
                                      ("cloud-worker", "MOTH Cloud's built-in worker", "moth-cloud-worker"),
                                      ("supervisor", "Self-repair supervisor", "moth-supervisor"))]
    du = shutil.disk_usage(ctx.settings.data_dir)
    dep = M.deployed(ctx)
    cyc = MEM.active_cycle(ctx)
    s = S.get(ctx)
    return {
        "version": __version__, "python": platform.python_version(), "platform": platform.platform(terse=True),
        "loops": loops,
        "serving": {"deployed_version": dep["version"] if dep else None,
                    "loaded": ctx.extras.get("inference_engine") is not None,
                    "problem": ctx.db.get_config("serving_restore_error", None)},
        "evolution": {"enabled": bool(s.get("enabled")), "paused": bool(s.get("paused")),
                      "cycle": {"id": cyc["id"], "status": cyc["status"],
                                "waiting_reason": (cyc.get("result") or {}).get("waiting_reason")} if cyc else None},
        "cloud_worker": CW.status(ctx),
        "disk": {"free": du.free, "total": du.total,
                 "reserve": float(s["limits"]["min_free_disk_gb"]) * 1024 ** 3},
        "repairs": list(reversed((ctx.db.get_config(LOG_KEY, []) or [])[-30:])),
        "errors": list(reversed(list(ring(ctx).records)))[:50],
    }


def report_text(d: dict[str, Any]) -> str:
    """A plain-text report the Owner can copy and share (no credentials: everything is redacted)."""
    import datetime as _dt

    def ts(x):
        return _dt.datetime.fromtimestamp(float(x), _dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if x else "-"

    lines = [f"MOTH Cloud {d['version']} diagnostics — {ts(time.time())}", f"Platform: {d['platform']} · Python {d['python']}", "",
             "Loops:"]
    lines += [f"- {l['label']}: {'running' if l['alive'] else 'STOPPED'}"
              + (f", last round {l['last_round_seconds_ago']} s ago" if l["last_round_seconds_ago"] is not None else "")
              for l in d["loops"]]
    sv = d["serving"]
    lines += ["", f"Serving: deployed v{sv['deployed_version']} · {'loaded' if sv['loaded'] else 'NOT LOADED'}"
              + (f" · {sv['problem']}" if sv.get("problem") else "")]
    ev = d["evolution"]
    lines += [f"Evolution: {'on' if ev['enabled'] else 'off'}{' (paused)' if ev['paused'] else ''}"
              + (f" · cycle #{ev['cycle']['id']} {ev['cycle']['status']}" if ev["cycle"] else "")
              + (f" · {ev['cycle']['waiting_reason']}" if ev["cycle"] and ev["cycle"].get("waiting_reason") else "")]
    cw = d["cloud_worker"]
    lines += [f"Built-in worker: {cw['state']}" + (f" — {cw['detail']}" if cw.get("detail") else "")]
    dk = d["disk"]
    lines += [f"Disk: {dk['free'] / 1024 ** 3:.1f} GB free of {dk['total'] / 1024 ** 3:.1f} GB "
              f"(reserve {dk['reserve'] / 1024 ** 3:.0f} GB)", "", "Recent self-repairs:"]
    lines += [f"- {ts(r['at'])}: {r['issue']} → {r['action']}{'' if r['ok'] else ' (not fixed)'}" for r in d["repairs"][:15]] or ["- none"]
    lines += ["", "Recent warnings and errors:"]
    lines += [f"- {ts(e['at'])} {e['level']} {e['logger']}: {e['message']}" for e in d["errors"][:30]] or ["- none"]
    return "\n".join(lines)
