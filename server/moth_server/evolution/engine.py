"""The evolution cycle: one autonomous, persistent, restartable workflow.

States of a cycle (``evolution_cycles.status``)::

    planning ─► waiting_for_compute ⇄ training ─► evaluating ─► deploying ─► monitoring ─► completed
       │                                              │              │            └──► rolled_back
       └─► (nothing new to try: no cycle is created)  └─► rejected   └─► failed (previous model serving)

* At most one cycle is active; a tick advances it one step (``tick``), from a background thread every
  ``TICK_SECONDS`` or synchronously in tests. All state is in the database, so a restart continues
  where it stopped (a running local trainer is re-attached or resumed from its checkpoint).
* Experiments train one at a time (no two jobs compete for the same hardware).
* Failed experiments never touch the active model; candidates are separate releases.
* Endless retries are prevented: experiments have ``max_attempts``; failed cycles back off
  exponentially; after ``max_consecutive_failures`` evolution pauses itself and says why.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import evolution_cycles, evolution_experiments, now
from moth_server.evolution import backends as B
from moth_server.evolution import compute as C
from moth_server.evolution import datasets as DS
from moth_server.evolution import evaluation as EV
from moth_server.evolution import memory as MEM
from moth_server.evolution import planner as P
from moth_server.evolution import settings as S

log = logging.getLogger("moth_server.evolution")

TICK_SECONDS = 30.0
STATE_KEY = "evolution_state"
_tick_lock = threading.Lock()


class EvolutionError(ValueError):
    pass


# ---- persistent engine state ---------------------------------------------------------------------------
def state(ctx: Ctx) -> dict[str, Any]:
    return {"consecutive_failures": 0, "next_cycle_at": 0.0, "idle_reason": None, "stable_version": None,
            "last_tick": None, **(ctx.db.get_config(STATE_KEY, {}) or {})}


def _set_state(ctx: Ctx, **values: Any) -> dict:
    st = {**state(ctx), **values}
    ctx.db.set_config(STATE_KEY, st)
    return st


# ---- public operations ---------------------------------------------------------------------------------
def start_cycle(ctx: Ctx, trigger: str = "manual", actor_id: int | None = None) -> dict:
    """Start a cycle now (Owner: "Run now"), if none is active and its prerequisites exist."""
    from moth_server import models as M

    settings = S.get(ctx)
    base = M.deployed(ctx)
    if not base:
        raise EvolutionError("no model is deployed: evolution continues training the deployed model")
    preview = P.plan(ctx, base, settings, cycle_seed=0)
    if not preview["experiments"]:
        raise EvolutionError("; ".join(preview["notes"]) or "there is nothing new to train on")
    t = now()
    with ctx.db.tx() as c:
        if c.execute(select(evolution_cycles.c.id).where(evolution_cycles.c.status.notin_(MEM.TERMINAL_CYCLE))).first():
            raise EvolutionError("an evolution cycle is already running")
        res = c.execute(evolution_cycles.insert().values(status="planning", trigger=trigger, base_version=base["version"],
                                                         base_sha256=base["sha256"], plan="{}", result="{}",
                                                         created_at=t, updated_at=t))
        cid = res.inserted_primary_key[0]
        MEM.event(ctx, "cycle.created", f"Evolution cycle #{cid} started ({trigger}) from model v{base['version']}",
                  cycle_id=cid, conn=c, actor=actor_id)
    _set_state(ctx, idle_reason=None)
    return MEM.cycle(ctx, cid)


def cancel_cycle(ctx: Ctx, actor_id: int | None = None) -> dict | None:
    cyc = MEM.active_cycle(ctx)
    if not cyc:
        return None
    if cyc["status"] in ("deploying", "monitoring"):
        raise EvolutionError("the candidate is being deployed or monitored; roll back instead of cancelling")
    for e in MEM.experiments(ctx, cyc["id"]):
        if e["status"] in MEM.TERMINAL_EXPERIMENT:
            continue
        _stop_experiment(ctx, e, "cancelled by the Owner")
    MEM.update_cycle(ctx, cyc["id"], status="cancelled", finished_at=now(), error="cancelled by the Owner")
    MEM.event(ctx, "cycle.cancelled", f"Cycle #{cyc['id']} was cancelled", cycle_id=cyc["id"], actor=actor_id)
    _schedule_next(ctx, failed=False)
    return MEM.cycle(ctx, cyc["id"])


def dataset_revoked(ctx: Ctx, dataset_id: int) -> int:
    """Stop every unfinished experiment that would train on a revoked dataset. Returns how many."""
    n = 0
    for e in MEM.experiments(ctx, limit=1000):
        if e["dataset_id"] == dataset_id and e["status"] not in MEM.TERMINAL_EXPERIMENT + ("trained", "evaluating"):
            _stop_experiment(ctx, e, "its training dataset was revoked")
            MEM.event(ctx, "experiment.cancelled", f"Experiment #{e['id']} was cancelled: its training dataset was "
                      "revoked", level="warning", cycle_id=e["cycle_id"], experiment_id=e["id"])
            n += 1
    return n


def rollback_to(ctx: Ctx, version: int, actor_id: int | None) -> dict:
    """Owner-selected rollback to a previous compatible version (health-checked atomic switch)."""
    from moth_server import models as M

    current = M.deployed(ctx)
    target = M.release(ctx, version)
    if target["status"] not in ("published", "deployed"):
        raise EvolutionError("only a version that passed evaluation (published) can be deployed")
    if current and target["info"].get("tokenizer_fingerprint") != current["info"].get("tokenizer_fingerprint"):
        raise EvolutionError("that version uses a different tokenizer than the deployed model; deploy it from "
                             "Models if this is intended")
    cyc = MEM.active_cycle(ctx)
    rel = M.deploy(ctx, version, actor_id)
    if cyc and cyc["status"] in ("deploying", "monitoring"):
        MEM.update_cycle(ctx, cyc["id"], status="rolled_back", finished_at=now(),
                         error=f"the Owner switched to v{version}")
        _schedule_next(ctx, failed=False)
    MEM.event(ctx, "deploy.rollback", f"Rolled back to v{version} by the Owner", level="warning",
              actor=actor_id, previous=current["version"] if current else None)
    _set_state(ctx, stable_version=version)
    return rel


# ---- the tick ------------------------------------------------------------------------------------------
def tick(ctx: Ctx) -> dict[str, Any]:
    """Advance evolution. A request that arrives while a tick is running is never lost: it is
    remembered (``evolution_wake``) and the running tick goes round once more."""
    if not _tick_lock.acquire(blocking=False):
        ctx.extras["evolution_wake"] = True
        return {"skipped": "busy"}
    try:
        for _ in range(3):
            ctx.extras["evolution_wake"] = False
            try:
                out = _tick(ctx)
            except Exception as e:  # noqa: BLE001 — the engine must keep running; the error is recorded
                log.exception("evolution tick failed")
                MEM.event(ctx, "engine.error", f"Evolution engine error: {type(e).__name__}: {e}", level="error")
                return {"error": str(e)}
            if not ctx.extras.get("evolution_wake"):
                return out
        return out
    finally:
        _tick_lock.release()


def wake(ctx: Ctx) -> None:
    """Something changed (data approved, evolution resumed …): check now, not at the scheduled time."""
    _set_state(ctx, next_cycle_at=0)
    ctx.extras["evolution_wake"] = True
    kick(ctx)


def _tick(ctx: Ctx) -> dict[str, Any]:
    settings = S.get(ctx)
    if not ctx.extras.get("evolution_recovered"):
        recover(ctx)
        ctx.extras["evolution_recovered"] = True
    st = _set_state(ctx, last_tick=now())
    if now() - float(st.get("last_prune") or 0) > 86400:
        MEM.prune(ctx, float(settings["retention_days"]))
        _set_state(ctx, last_prune=now())
    cyc = MEM.active_cycle(ctx)
    if not settings["enabled"] or settings["paused"]:
        if cyc:
            _pause_running(ctx, cyc, "evolution is paused" if settings["enabled"] else "evolution is turned off")
        return {"state": "paused" if settings["enabled"] else "off"}
    if cyc is None:
        started = _maybe_start(ctx, settings)
        if "cycle" not in started:
            return started
        cyc = MEM.active_cycle(ctx)
    # Advance through quick transitions in one tick (planning → trying to start, trained → evaluating …),
    # so the dashboard never shows a state the engine has not actually checked yet. Bounded.
    for _ in range(MAX_STEPS_PER_TICK):
        before = cyc["status"]
        HANDLERS[before](ctx, cyc, settings)
        after = MEM.cycle(ctx, cyc["id"])
        if after["status"] == before or after["status"] in MEM.TERMINAL_CYCLE:
            break
        cyc = after
    return {"cycle": cyc["id"], "status": MEM.cycle(ctx, cyc["id"])["status"]}


def _maybe_start(ctx: Ctx, settings: dict) -> dict:
    from moth_server import models as M

    st = state(ctx)
    if now() < float(st["next_cycle_at"] or 0):
        return {"state": "scheduled", "next_cycle_at": st["next_cycle_at"]}
    base = M.deployed(ctx)
    reason = None
    if not base:
        reason = "No model is deployed yet. Evolution continues training the deployed model."
    elif not DS.approved(ctx):
        reason = "No approved training data. Add a dataset in Evolution → Data and approve it."
    else:
        preview = P.plan(ctx, base, settings, 0)
        if not preview["experiments"]:
            reason = " ".join(preview["notes"]) or "Nothing new to train on."
    if reason:
        if reason != st.get("idle_reason"):
            MEM.event(ctx, "engine.idle", reason)
        # check again in a while (approving data or deploying a model starts a cycle sooner)
        # an Owner action during this check (e.g. approving data) wins: don't push the next check later
        later = 0.0 if ctx.extras.get("evolution_wake") else now() + min(3600.0, float(settings["interval_hours"]) * 3600)
        _set_state(ctx, idle_reason=reason, next_cycle_at=later)
        return {"state": "idle", "reason": reason}
    cyc = start_cycle(ctx, "schedule")
    return {"cycle": cyc["id"], "status": cyc["status"]}


def _planning(ctx: Ctx, cyc: dict, settings: dict) -> None:
    from moth_server import models as M

    base = M.release(ctx, cyc["base_version"])
    result = P.plan(ctx, base, settings, cycle_seed=1000 + cyc["id"])
    if not result["experiments"]:
        MEM.update_cycle(ctx, cyc["id"], status="completed", plan=result, finished_at=now(),
                         result={"outcome": "nothing_to_do", "notes": result["notes"]})
        MEM.event(ctx, "cycle.nothing_to_do", "; ".join(result["notes"]), cycle_id=cyc["id"])
        _schedule_next(ctx, failed=False)
        return
    t = now()
    with ctx.db.tx() as c:
        for p in result["experiments"]:
            res = c.execute(evolution_experiments.insert().values(
                cycle_id=cyc["id"], status="planned", config=json.dumps(p["config"]),
                config_hash=p["config_hash"], dataset_id=p["dataset_id"], base_version=base["version"],
                base_sha256=base["sha256"], rationale=p["rationale"], attempts=0, max_attempts=3, metrics="{}",
                resources="{}", compute_seconds=0.0, created_at=t, updated_at=t))
            MEM.event(ctx, "experiment.planned", f"Experiment #{res.inserted_primary_key[0]}: {p['rationale']}",
                      cycle_id=cyc["id"], experiment_id=res.inserted_primary_key[0], conn=c)
        MEM.update_cycle(ctx, cyc["id"], conn=c, status="waiting_for_compute", plan=result, started_at=t)


def _need_bytes(ctx: Ctx, exp: dict) -> int:
    from moth_server import models as M

    base = M.release(ctx, exp["base_version"])
    cfg = base["info"].get("config") or {}
    return C.estimate_training_memory(int(base["info"].get("params") or 0), exp["config"]["batch_size"],
                                      exp["config"]["seq_len"], int(cfg.get("d_model", 512)),
                                      int(cfg.get("n_layers", 12)))


def _training(ctx: Ctx, cyc: dict, settings: dict) -> None:
    exps = sorted(MEM.experiments(ctx, cyc["id"]), key=lambda e: e["id"])
    started = float(cyc["started_at"] or cyc["created_at"])
    if now() - started > float(settings["budget"]["max_cycle_hours"]) * 3600:
        for e in exps:
            if e["status"] not in MEM.TERMINAL_EXPERIMENT + ("trained",):
                _stop_experiment(ctx, e, "the cycle's time budget was used up")
        MEM.event(ctx, "cycle.budget", "The cycle's time budget was used up; evaluating what finished",
                  level="warning", cycle_id=cyc["id"])
        MEM.update_cycle(ctx, cyc["id"], status="evaluating")
        return
    active = next((e for e in exps if e["status"] == "running"), None) or \
        next((e for e in exps if e["status"] in ("planned", "waiting", "paused")), None)
    if active is None:
        MEM.update_cycle(ctx, cyc["id"], status="evaluating")
        return
    if active["status"] == "running":
        _advance_running(ctx, cyc, active, settings)
    else:
        _try_start(ctx, cyc, active, settings)


def _waiting(ctx: Ctx, cyc: dict, exp: dict, reasons: list[str], status: str = "waiting") -> None:
    reason = "; ".join(reasons)
    if exp.get("error") != reason or exp["status"] != status:
        MEM.event(ctx, "experiment.waiting", f"Experiment #{exp['id']} is waiting: {reason}",
                  cycle_id=cyc["id"], experiment_id=exp["id"])
    MEM.update_experiment(ctx, exp["id"], status=status, error=reason)
    MEM.update_cycle(ctx, cyc["id"], status="waiting_for_compute", result={**(cyc["result"] or {}),
                                                                          "waiting_reason": reason})


def _try_start(ctx: Ctx, cyc: dict, exp: dict, settings: dict) -> None:
    if exp.get("job_id"):  # a worker job exists already (e.g. requeued after a lease expiry)
        MEM.update_experiment(ctx, exp["id"], status="running")
        return
    choice, reasons = C.choose_backend(ctx, settings, _need_bytes(ctx, exp))
    if choice is None:  # a paused experiment keeps its checkpoint and stays "paused"
        _waiting(ctx, cyc, exp, reasons, "paused" if exp["status"] == "paused" else "waiting")
        return
    if choice["backend"] == "local":
        blockers = C.local_blockers(ctx, settings, choice["device"])
        if blockers:
            _waiting(ctx, cyc, exp, blockers, "paused" if exp["status"] == "paused" else "waiting")
            return
        resumed = exp["status"] == "paused"
        res = B.start_local(ctx, exp, choice["device"], settings)
        MEM.update_experiment(ctx, exp["id"], status="running", backend="local", error=None,
                              started_at=exp["started_at"] or now(), run_dir=str(B.run_dir(ctx, exp)),
                              resources={**(exp["resources"] or {}), **res})
        MEM.update_cycle(ctx, cyc["id"], status="training", result={**(cyc["result"] or {}), "waiting_reason": None})
        MEM.event(ctx, "experiment.resumed" if resumed else "experiment.started",
                  f"Experiment #{exp['id']} {'resumed from its checkpoint' if resumed else 'started'} on this "
                  f"server ({choice['device']})", cycle_id=cyc["id"], experiment_id=exp["id"])
    else:
        jid = B.create_worker_job(ctx, exp, _need_bytes(ctx, exp))
        MEM.update_experiment(ctx, exp["id"], status="running", backend="worker", job_id=jid, error=None,
                              started_at=now(), run_dir=str(B.run_dir(ctx, exp)))
        MEM.event(ctx, "experiment.queued", f"Experiment #{exp['id']} was queued for a MOTH worker (job {jid})",
                  cycle_id=cyc["id"], experiment_id=exp["id"])
        MEM.update_cycle(ctx, cyc["id"], status="waiting_for_compute",
                         result={**(cyc["result"] or {}), "waiting_reason": "waiting for a MOTH worker to take the job"})


def _finish_training(ctx: Ctx, cyc: dict, exp: dict, result: dict, seconds: float) -> None:
    rd = B.run_dir(ctx, exp)
    total = float(exp["compute_seconds"] or 0) + seconds
    if not result.get("ok"):
        attempts = int(exp["attempts"]) + 1
        final = attempts >= int(exp["max_attempts"])
        MEM.update_experiment(ctx, exp["id"], status="failed" if final else "waiting", attempts=attempts,
                              error=result.get("error"), compute_seconds=total,
                              finished_at=now() if final else None)
        MEM.event(ctx, "experiment.failed" if final else "experiment.retry",
                  f"Experiment #{exp['id']} failed{'' if final else ' (will retry)'}: {result.get('error')}",
                  level="error" if final else "warning", cycle_id=cyc["id"], experiment_id=exp["id"])
        if final:
            B.cleanup_run(ctx, exp)
        return
    from pathlib import Path

    try:
        rel = B.register_candidate(ctx, exp, Path(result["package"]))
    except Exception as e:  # noqa: BLE001 — e.g. invalid package: the experiment failed, nothing else changes
        MEM.update_experiment(ctx, exp["id"], status="failed", error=f"candidate rejected: {e}",
                              compute_seconds=total, finished_at=now())
        MEM.event(ctx, "experiment.failed", f"Experiment #{exp['id']}: the trained model was invalid: {e}",
                  level="error", cycle_id=cyc["id"], experiment_id=exp["id"])
        B.cleanup_run(ctx, exp)
        return
    training = {k: result.get(k) for k in ("step", "max_steps", "best_val", "seconds", "device", "resumed",
                                           "loss_before", "loss_after", "tokens", "backend", "peak_memory_bytes")}
    MEM.update_experiment(ctx, exp["id"], status="trained", candidate_version=rel["version"], compute_seconds=total,
                          metrics={**(exp["metrics"] or {}), "training": training, "progress": B.progress(ctx, exp)},
                          resources={**(exp["resources"] or {}), "peak_memory_bytes": result.get("peak_memory_bytes")},
                          progress=1.0, error=None)
    MEM.event(ctx, "experiment.trained", f"Experiment #{exp['id']} finished training → candidate v{rel['version']}",
              cycle_id=cyc["id"], experiment_id=exp["id"], seconds=round(total, 1))
    (rd / "STOP").unlink(missing_ok=True)


def _advance_running(ctx: Ctx, cyc: dict, exp: dict, settings: dict) -> None:
    rd = B.run_dir(ctx, exp)
    if exp["backend"] == "worker":
        j = B.job(ctx, exp["job_id"])
        if j is None:
            MEM.update_experiment(ctx, exp["id"], status="failed", error="the worker job disappeared", finished_at=now())
            return
        if j["status"] == "completed" and (rd / "result.json").exists():
            _finish_training(ctx, cyc, exp, json.loads((rd / "result.json").read_text()),
                             max(0.0, (j["updated_at"] or now()) - (exp["started_at"] or now())))
        elif j["status"] in ("failed", "cancelled"):
            MEM.update_experiment(ctx, exp["id"], status="failed", error=f"worker job {j['status']}: {j['error']}",
                                  finished_at=now(), attempts=j["attempts"])
            MEM.event(ctx, "experiment.failed", f"Experiment #{exp['id']}: the worker job failed: {j['error']}",
                      level="error", cycle_id=cyc["id"], experiment_id=exp["id"])
        else:
            MEM.update_experiment(ctx, exp["id"], progress=j["progress"], worker_id=j["worker_id"])
            leased = j["status"] == "leased"
            MEM.update_cycle(ctx, cyc["id"], status="training" if leased else "waiting_for_compute",
                             result={**(cyc["result"] or {}),
                                     "waiting_reason": None if leased else "waiting for a MOTH worker to take the job"})
        return
    st = B.local_state(ctx, exp)
    res = exp["resources"] or {}
    elapsed = max(0.0, now() - float(res.get("started") or now()))
    if st == "running":
        blockers = C.local_blockers(ctx, settings, res.get("device", "cpu"))
        if blockers:
            B.pause_local(ctx, exp)
            MEM.update_experiment(ctx, exp["id"], status="paused", error="; ".join(blockers),
                                  compute_seconds=float(exp["compute_seconds"] or 0) + elapsed)
            MEM.event(ctx, "experiment.paused", f"Experiment #{exp['id']} paused (checkpoint saved): "
                      + "; ".join(blockers), level="warning", cycle_id=cyc["id"], experiment_id=exp["id"])
            MEM.update_cycle(ctx, cyc["id"], status="waiting_for_compute",
                             result={**(cyc["result"] or {}), "waiting_reason": "; ".join(blockers)})
            return
        prog = B.progress(ctx, exp)
        MEM.update_experiment(ctx, exp["id"], progress=prog.get("fraction"),
                              metrics={**(exp["metrics"] or {}), "progress": prog})
        MEM.update_cycle(ctx, cyc["id"], status="training")
        return
    (ctx.extras.get("evolution_procs") or {}).pop(exp["id"], None)
    if st == "finished":
        result = json.loads((rd / "result.json").read_text())
        if result.get("ok") and result.get("reason") == "stopped":
            MEM.update_experiment(ctx, exp["id"], status="paused", compute_seconds=float(exp["compute_seconds"] or 0)
                                  + float(result.get("seconds") or 0))
            return
        _finish_training(ctx, cyc, exp, result, float(result.get("seconds") or elapsed))
    else:  # the process ended without a result (killed, server restart, out of memory)
        MEM.update_experiment(ctx, exp["id"], status="paused",
                              error="the training process stopped unexpectedly; it resumes from its last checkpoint",
                              compute_seconds=float(exp["compute_seconds"] or 0) + elapsed)
        MEM.event(ctx, "experiment.interrupted", f"Experiment #{exp['id']}'s training process stopped unexpectedly; "
                  "it will resume from its last checkpoint", level="warning", cycle_id=cyc["id"], experiment_id=exp["id"])


def _stop_experiment(ctx: Ctx, exp: dict, reason: str) -> None:
    if exp["status"] == "running" and exp["backend"] == "local":
        if not B.pause_local(ctx, exp, wait_s=30):
            B.kill_local(ctx, exp)
    if exp.get("job_id"):
        from moth_server.db import training_jobs

        with ctx.db.tx() as c:
            c.execute(training_jobs.update().where(training_jobs.c.id == exp["job_id"],
                                                   training_jobs.c.status.in_(("queued", "leased")))
                      .values(status="cancelled", error=reason, updated_at=now()))
    MEM.update_experiment(ctx, exp["id"], status="cancelled", error=reason, finished_at=now())
    B.cleanup_run(ctx, exp)


def _pause_running(ctx: Ctx, cyc: dict, reason: str) -> None:
    for e in MEM.experiments(ctx, cyc["id"]):
        if e["status"] == "running" and e["backend"] == "local" and B.local_state(ctx, e) == "running":
            B.pause_local(ctx, e)
            MEM.update_experiment(ctx, e["id"], status="paused", error=reason)
            MEM.event(ctx, "experiment.paused", f"Experiment #{e['id']} paused (checkpoint saved): {reason}",
                      cycle_id=cyc["id"], experiment_id=e["id"])


def _evaluating(ctx: Ctx, cyc: dict, settings: dict) -> None:
    from moth_server import models as M

    base = M.release(ctx, cyc["base_version"])
    for e in sorted(MEM.experiments(ctx, cyc["id"]), key=lambda x: x["id"]):
        if e["status"] not in ("trained", "evaluating"):
            continue
        MEM.update_experiment(ctx, e["id"], status="evaluating")
        cand = M.release(ctx, e["candidate_version"])
        try:
            verdict = EV.gate(ctx, cand, base, DS.get(ctx, e["dataset_id"]), settings)
        except Exception as ex:  # noqa: BLE001
            MEM.update_experiment(ctx, e["id"], status="failed", error=f"evaluation failed: {ex}", finished_at=now())
            MEM.event(ctx, "experiment.failed", f"Experiment #{e['id']}: evaluation failed: {ex}", level="error",
                      cycle_id=cyc["id"], experiment_id=e["id"])
            continue
        metrics = {**(e["metrics"] or {}), "gates": verdict["gates"], "primary_improvement": verdict["primary_improvement"],
                   "performance": verdict["performance"]}
        failed = [g["gate"] for g in verdict["gates"] if not g["passed"]]
        MEM.update_experiment(ctx, e["id"], status="passed" if verdict["passed"] else "rejected", metrics=metrics,
                              finished_at=now(), error=None if verdict["passed"] else "failed: " + ", ".join(failed))
        if not verdict["passed"] and M.release(ctx, cand["version"])["status"] == "published":
            # passed the basic release checks but not evolution's gates: never deployable by accident
            M._set(ctx, cand["version"], "evaluated", error="Not promoted by evolution (failed: " + ", ".join(failed)
                   + "). It can still be published explicitly from Models.")
        MEM.event(ctx, "experiment.passed" if verdict["passed"] else "experiment.rejected",
                  f"Candidate v{cand['version']} " + ("passed every gate" if verdict["passed"] else
                                                      f"was rejected ({', '.join(failed)})"),
                  level="info" if verdict["passed"] else "warning", cycle_id=cyc["id"], experiment_id=e["id"],
                  improvement=verdict["primary_improvement"])
        B.cleanup_run(ctx, e)
    exps = MEM.experiments(ctx, cyc["id"])
    passed = [e for e in exps if e["status"] == "passed"]
    if not passed:
        MEM.update_cycle(ctx, cyc["id"], status="rejected", finished_at=now(),
                         result={**(cyc["result"] or {}), "outcome": "no_candidate_passed",
                                 "experiments": {e["id"]: e["status"] for e in exps}})
        MEM.event(ctx, "cycle.rejected", f"Cycle #{cyc['id']}: no candidate improved the model safely; the deployed "
                  "model stays", cycle_id=cyc["id"])
        _schedule_next(ctx, failed=False)
        return
    best = max(passed, key=lambda e: (e["metrics"] or {}).get("primary_improvement") or 0)
    if not settings["auto_deploy"]:
        MEM.update_cycle(ctx, cyc["id"], status="completed", candidate_version=best["candidate_version"],
                         finished_at=now(), result={**(cyc["result"] or {}), "outcome": "awaiting_owner_deploy"})
        MEM.event(ctx, "cycle.ready", f"Candidate v{best['candidate_version']} passed; automatic deployment is off, "
                  "deploy it from Models when ready", cycle_id=cyc["id"])
        _schedule_next(ctx, failed=False)
        return
    MEM.update_cycle(ctx, cyc["id"], status="deploying", candidate_version=best["candidate_version"])


def _deploying(ctx: Ctx, cyc: dict, settings: dict) -> None:
    from moth_server import models as M

    previous = M.deployed(ctx)
    if previous and not state(ctx).get("stable_version"):
        _set_state(ctx, stable_version=previous["version"])  # the candidate becomes stable only after monitoring
    try:
        M.deploy(ctx, cyc["candidate_version"])
    except M.ReleaseError as e:
        MEM.update_cycle(ctx, cyc["id"], status="failed", finished_at=now(), error=str(e))
        MEM.event(ctx, "deploy.failed", f"Deploying v{cyc['candidate_version']} failed; v"
                  f"{previous['version'] if previous else '?'} is still serving: {e}", level="error", cycle_id=cyc["id"])
        _schedule_next(ctx, failed=True)
        return
    t = now()
    act = C.activity(ctx)
    window = max(60.0, float(settings["monitoring"]["minutes"]) * 60)
    baseline = act.stats(previous["version"], t - window, t) if previous else {}
    MEM.update_cycle(ctx, cyc["id"], status="monitoring",
                     result={**(cyc["result"] or {}), "deployed_at": t,
                             "previous_version": previous["version"] if previous else None, "baseline": baseline})
    MEM.event(ctx, "deploy.done", f"v{cyc['candidate_version']} is now serving (previous: "
              f"v{previous['version'] if previous else 'none'}); monitoring for "
              f"{settings['monitoring']['minutes']:g} min", cycle_id=cyc["id"])


def _probe(ctx: Ctx) -> str | None:
    """A real inference request against the serving engine. Returns an error, or None if healthy."""
    from moth.model.generation import GenerationParams

    eng = ctx.extras.get("inference_engine")
    if eng is None:
        return "no model is loaded"
    try:
        _, stats = eng.complete("def ", GenerationParams(max_new_tokens=4, temperature=0.0, top_k=1))
        return None if stats.generated_tokens >= 1 else "the model produced no tokens"
    except Exception as e:  # noqa: BLE001
        return f"{type(e).__name__}: {e}"


def _monitoring(ctx: Ctx, cyc: dict, settings: dict) -> None:
    from moth_server import models as M

    res = cyc["result"] or {}
    mon = settings["monitoring"]
    started = float(res.get("deployed_at") or now())
    problem = None
    if ctx.extras.get("deployed_version") != cyc["candidate_version"]:
        problem = "another model was deployed during monitoring"
    else:
        problem = _probe(ctx)
        stats = C.activity(ctx).stats(cyc["candidate_version"], started)
        if problem is None and stats["requests"] >= int(mon["min_requests"]):
            if stats["error_rate"] > float(mon["max_error_rate"]):
                problem = f"error rate {stats['error_rate']:.0%} is above {float(mon['max_error_rate']):.0%}"
            base_spt = (res.get("baseline") or {}).get("seconds_per_token")
            if problem is None and base_spt and stats["seconds_per_token"] and \
                    stats["seconds_per_token"] > base_spt * float(mon["max_latency_factor"]):
                problem = (f"latency is {stats['seconds_per_token'] / base_spt:.1f}× the previous model's "
                           f"(limit {float(mon['max_latency_factor']):g}×)")
        MEM.update_cycle(ctx, cyc["id"], result={**res, "monitor": stats})
    if problem and problem != "another model was deployed during monitoring":
        prev = res.get("previous_version")
        rolled = None
        if prev:
            try:
                M.deploy(ctx, int(prev))
                rolled = prev
            except M.ReleaseError as e:
                problem += f"; rolling back to v{prev} also failed: {e}"
        M._set(ctx, cyc["candidate_version"], "failed",
               error=f"Rolled back after deployment monitoring: {problem}")
        MEM.update_cycle(ctx, cyc["id"], status="rolled_back", finished_at=now(), error=problem)
        MEM.event(ctx, "deploy.rollback", f"v{cyc['candidate_version']} was rolled back"
                  + (f" to v{rolled}" if rolled else "") + f": {problem}", level="error", cycle_id=cyc["id"])
        _schedule_next(ctx, failed=True)
        return
    if problem:  # the Owner switched models: monitoring of this candidate ends
        MEM.update_cycle(ctx, cyc["id"], status="completed", finished_at=now(),
                         result={**res, "outcome": "superseded"})
        _schedule_next(ctx, failed=False)
        return
    if now() - started >= float(mon["minutes"]) * 60:
        MEM.update_cycle(ctx, cyc["id"], status="completed", finished_at=now(), result={**res, "outcome": "deployed"})
        _set_state(ctx, stable_version=cyc["candidate_version"])
        MEM.event(ctx, "cycle.completed", f"v{cyc['candidate_version']} passed monitoring and is the new stable model",
                  cycle_id=cyc["id"])
        _schedule_next(ctx, failed=False)


def _schedule_next(ctx: Ctx, failed: bool) -> None:
    settings = S.get(ctx)
    st = state(ctx)
    fails = int(st["consecutive_failures"]) + 1 if failed else 0
    delay = float(settings["interval_hours"]) * 3600 * (2 ** min(fails, 4))
    values: dict[str, Any] = {"consecutive_failures": fails, "next_cycle_at": now() + delay}
    if failed and fails >= int(settings["max_consecutive_failures"]):
        S.update(ctx, {"paused": True})
        MEM.event(ctx, "engine.paused", f"Evolution paused itself after {fails} failed cycles in a row. Review the "
                  "failures, then resume.", level="error")
    _set_state(ctx, **values)


# ---- restart recovery ----------------------------------------------------------------------------------
def recover(ctx: Ctx) -> None:
    """After a restart: nothing stays stuck in a transient state."""
    cyc = MEM.active_cycle(ctx)
    if not cyc:
        return
    for e in MEM.experiments(ctx, cyc["id"]):
        if e["status"] == "evaluating":
            MEM.update_experiment(ctx, e["id"], status="trained")
    if cyc["status"] == "deploying":
        if ctx.extras.get("deployed_version") == cyc["candidate_version"] or \
                ctx.db.get_config("deployed_release") == cyc["candidate_version"]:
            MEM.update_cycle(ctx, cyc["id"], status="monitoring",
                             result={**(cyc["result"] or {}), "deployed_at": now()})
        # otherwise deploy() did not complete: it is retried (the previous model kept serving)
    elif cyc["status"] == "monitoring":
        MEM.update_cycle(ctx, cyc["id"], result={**(cyc["result"] or {}), "deployed_at": now()})  # watch a full window
    MEM.event(ctx, "engine.recovered", f"Resumed cycle #{cyc['id']} ({cyc['status']}) after a restart", cycle_id=cyc["id"])


# ---- background loop ------------------------------------------------------------------------------------
def start_background(ctx: Ctx) -> None:
    stop = threading.Event()
    ctx.extras["evolution_stop"] = stop

    def loop() -> None:
        while not stop.wait(TICK_SECONDS):
            tick(ctx)

    threading.Thread(target=loop, daemon=True, name="evolution").start()


HANDLERS = {"planning": _planning, "waiting_for_compute": _training, "training": _training,
            "evaluating": _evaluating, "deploying": _deploying, "monitoring": _monitoring}
MAX_STEPS_PER_TICK = 5


def kick(ctx: Ctx) -> None:
    """Run a tick now (after an Owner action) without blocking the request."""
    if ctx.extras.get("synchronous_jobs"):
        tick(ctx)
    else:
        threading.Thread(target=lambda: tick(ctx), daemon=True, name="evolution-kick").start()
