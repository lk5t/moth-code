"""MOTH Evolution Engine autopilot: one-click start, an adaptive training plan and explained decisions.

The autopilot is a conventional, measurable controller. It does not ask the native model for
decisions (an early MOTH model cannot make them reliably). Every adjustment comes from recorded
measurements of earlier experiments on this lineage and from the resources measured now, and every
adjustment is recorded with the reason and the numbers behind it.

* ``adapt`` — the training plan for the next cycle: steps, learning rate, batch size and the wait
  before the next cycle, adjusted from held-out improvement, early stopping, memory failures and the
  time each step actually took. Bounded by the Owner's limits; returns explanations.
* ``start`` / ``pause`` — the one-click controls. ``start`` creates a first model when there is none
  (genesis), approves the trusted catalog sources that fit the storage budget, starts preparing data
  and turns on continuous evolution. Nothing here bypasses the existing gates, budgets or consent.
* ``status`` — the stage MOTH is in, the next thing it will do and why, in plain words.
"""

from __future__ import annotations

import copy
import shutil
from typing import Any

from moth_server.context import Ctx
from moth_server.db import now
from moth_server.evolution import memory as MEM
from moth_server.evolution import settings as S

# Trusted catalog sources in the order the autopilot adds them: coding first, then reasoning,
# instruction following and general language. Every one has a verified license and attribution.
PRIORITY = ["python-stdlib", "mbpp", "gsm8k", "arc", "oasst1", "dolly-15k", "tinystories", "simple-wikipedia"]

MIN_STEPS, MAX_STEPS = 50, 20_000
STALL_CYCLES = 3          # cycles without an accepted improvement before the engine slows down
MEMORY_WORDS = ("out of memory", "cuda error: out of memory", "memoryerror", "cannot allocate", "killed")


def _recent(ctx: Ctx, limit: int = 12) -> list[dict]:
    """Finished experiments, newest first (this lineage; a Genesis Reset clears older ones)."""
    done = ("passed", "rejected", "failed", "trained", "deployed")
    return [e for e in MEM.experiments(ctx, limit=limit * 3) if e["status"] in done][:limit]


def _improvement(e: dict) -> float | None:
    v = (e.get("metrics") or {}).get("primary_improvement")
    return float(v) if isinstance(v, (int, float)) else None


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def adapt(ctx: Ctx, settings: dict, resources: dict | None = None) -> tuple[dict, list[dict]]:
    """Return (settings for the next cycle, decisions). ``settings`` is never modified in place."""
    out = copy.deepcopy(settings)
    if not settings.get("autopilot", True):
        return out, []
    tr = out["training"]
    base_steps, base_lr, base_batch = int(tr["steps"]), float(tr["lr"]), int(tr["batch_size"])
    state = ctx.db.get_config("evolution_autopilot", {}) or {}
    steps = int(state.get("steps") or base_steps)
    lr = float(state.get("lr") or base_lr)
    batch = int(state.get("batch_size") or base_batch)
    decisions: list[dict] = []

    def decide(kind: str, message: str, **metrics: Any) -> None:
        decisions.append({"kind": kind, "message": message, "metrics": metrics})

    recent = _recent(ctx)
    memory_failures = [e for e in recent[:3] if e["status"] == "failed"
                       and any(w in (e.get("error") or "").lower() for w in MEMORY_WORDS)]
    scored = [e for e in recent if _improvement(e) is not None]
    min_gain = float(settings["gates"]["min_improvement"])

    if memory_failures and batch > 1:
        new = max(1, batch // 2)
        decide("batch_size", f"Experiment #{memory_failures[0]['id']} ran out of memory, so I'm halving the batch "
               f"size from {batch} to {new}.", batch_before=batch, batch_after=new, experiment=memory_failures[0]["id"])
        batch = new
    elif len(scored) >= 2:
        last, prev = _improvement(scored[0]), _improvement(scored[1])
        early = [e for e in scored[:2] if (e.get("metrics") or {}).get("early_stopped")]
        if last >= 2 * min_gain and prev >= 2 * min_gain and not early:
            new = min(MAX_STEPS, int(steps * 1.5))
            if new != steps:
                decide("steps", f"The last two runs improved held-out results by {_pct(last)} and {_pct(prev)} without "
                       f"levelling off, so I'm training longer: {new} steps instead of {steps}.",
                       improvements=[last, prev], steps_before=steps, steps_after=new)
                steps = new
        elif last < min_gain and prev < min_gain:
            new_lr = max(lr / 2, 1e-6)
            new_steps = max(MIN_STEPS, base_steps if steps > base_steps else steps)
            why = (f"stopped early ({(early[0]['metrics'] or {}).get('early_stopped')})" if early
                   else f"improved held-out results by only {_pct(last)} and {_pct(prev)} (I need {_pct(min_gain)})")
            decide("lr", f"Training has slowed down: the last two runs {why}. I'm testing a lower learning rate "
                   f"({new_lr:.1e} instead of {lr:.1e})" + (f" and returning to {new_steps} steps." if new_steps != steps else "."),
                   improvements=[last, prev], lr_before=lr, lr_after=new_lr, steps_before=steps, steps_after=new_steps)
            lr, steps = new_lr, new_steps
        elif early and steps > MIN_STEPS:
            stopped = int(((early[0]["metrics"] or {}).get("training") or {}).get("step") or steps)
            new = max(MIN_STEPS, min(steps, int(stopped * 1.2)))
            if new < steps:
                decide("steps", f"Experiment #{early[0]['id']} stopped improving at step {stopped}, so I'm planning "
                       f"{new} steps instead of {steps} to save compute.", steps_before=steps, steps_after=new,
                       stopped_at=stopped)
                steps = new

    # Fit the cycle into the Owner's time budget, using the real time per step measured last time.
    timed = next((e for e in recent if ((e.get("metrics") or {}).get("training") or {}).get("seconds")
                  and ((e.get("metrics") or {}).get("training") or {}).get("step")), None)
    if timed:
        t = timed["metrics"]["training"]
        per_step = float(t["seconds"]) / max(1, int(t["step"]))
        experiments = int(settings["max_experiments_per_cycle"])
        budget = float(settings["budget"]["max_cycle_hours"]) * 3600 * 0.8
        fit = int(budget / max(per_step * experiments, 1e-6))
        if fit < steps:
            new = max(MIN_STEPS, fit)
            decide("budget", f"Each step took {per_step:.2f} s last time, so {steps} steps for {experiments} experiments "
                   f"would not fit the {settings['budget']['max_cycle_hours']:g}-hour cycle budget. I'm planning {new} steps.",
                   seconds_per_step=per_step, steps_before=steps, steps_after=new)
            steps = new

    # Memory available now: a smaller batch rather than an out-of-memory failure.
    mem = ((resources or {}).get("local") or {}).get("memory") or {}
    avail = mem.get("available")
    if isinstance(avail, (int, float)) and avail < float(settings["limits"]["min_free_memory_gb"]) * 2 * 1024**3 and batch > 1:
        new = max(1, batch // 2)
        decide("batch_size", f"Only {avail / 1024**3:.1f} GB of memory is free on MOTH Cloud, so I'm reducing the batch "
               f"size from {batch} to {new}.", free_bytes=avail, batch_before=batch, batch_after=new)
        batch = new

    # Avoid endless loops: after several cycles with no accepted improvement, wait longer between cycles.
    cycles = [c for c in MEM.cycles(ctx, limit=STALL_CYCLES) if c["status"] in MEM.TERMINAL_CYCLE]
    if len(cycles) >= STALL_CYCLES and not any(c["status"] in ("deployed", "monitoring") or (c.get("result") or {}).get("outcome") == "deployed"
                                               for c in cycles):
        factor = min(16, 2 ** (len(cycles) - STALL_CYCLES + 1))
        hours = float(settings["interval_hours"]) * factor
        hours = max(hours, 1.0)
        out["interval_hours"] = hours
        decide("pace", f"The last {len(cycles)} cycles produced no accepted improvement, so I'm waiting {hours:g} h "
               "between cycles instead of training continuously. New data, a growth experiment or your request starts sooner.",
               cycles=[c["id"] for c in cycles], interval_hours=hours)

    tr["steps"], tr["lr"], tr["batch_size"] = int(steps), float(lr), int(batch)
    return out, decisions


def remember(ctx: Ctx, settings: dict, decisions: list[dict], cycle_id: int | None) -> None:
    """Keep the adapted plan for the next cycle and record each decision in the activity stream."""
    tr = settings["training"]
    ctx.db.set_config("evolution_autopilot", {"steps": tr["steps"], "lr": tr["lr"], "batch_size": tr["batch_size"],
                                              "updated_at": now(), "decisions": decisions[-8:]})
    for d in decisions:
        MEM.event(ctx, "plan.adjusted", d["message"], cycle_id=cycle_id, decision=d["kind"], **{
            k: v for k, v in d["metrics"].items() if isinstance(v, (int, float, str, list))})


# ---- one-click controls ---------------------------------------------------------------------------------
def _choose_sources(ctx: Ctx) -> tuple[list[str], list[str]]:
    """Trusted sources in priority order that fit the download budget and free disk space."""
    from moth.datafactory import catalog
    from moth_server.intelligence import discovery, library

    p = discovery.policy(ctx)
    reserve = S.get(ctx)["limits"]["min_free_disk_gb"] * 1024**3
    free = shutil.disk_usage(library.root(ctx)).free - reserve
    chosen, skipped, total = [], [], 0
    for sid in PRIORITY:
        try:
            src = catalog.with_pin(catalog.source(sid), library.pins(ctx).get(sid))
        except (KeyError, TypeError):
            continue
        if src["license"] not in discovery.LICENSES or not src.get("attribution"):
            continue
        size = sum(f["size"] for f in src["files"])
        if total + size > p["max_download_bytes"] or (total + size) * 4 > free:
            skipped.append(sid)
            continue
        chosen.append(sid)
        total += size
    return chosen, skipped


def start(ctx: Ctx, actor_id: int | None) -> dict:
    """Start Evolution with one click. Every step is a real, existing operation."""
    from moth_server import models as M
    from moth_server.evolution import bootstrap, engine
    from moth_server.evolution.native_reset import fenced
    from moth_server.intelligence import discovery, library

    if fenced(ctx):
        raise ValueError("A Genesis Reset is still in progress. Finish it in Settings → Advanced first.")
    steps: list[str] = []
    if M.deployed(ctx) is None:
        opts = bootstrap.options(ctx)
        if not opts["can_initialize"]:
            raise ValueError(f"A model is registered ({opts['existing']}) but none is deployed. Deploy or delete it in "
                             "AI → AI Settings, then start again.")
        tokenizer = "library" if library.latest_ready(ctx) else "byte"
        bootstrap.activate_initial(ctx, actor_id, "seed", tokenizer)
        steps.append(f"Created the first MOTH model (seed size, {'trained' if tokenizer == 'library' else 'byte-level'} "
                     "tokenizer). It starts untrained and learns from the prepared data.")
        MEM.event(ctx, "genesis.created", steps[-1])
    pol = discovery.policy(ctx)
    chosen, skipped = _choose_sources(ctx)
    new = [s for s in chosen if s not in pol["approved_sources"]]
    if new:
        discovery.update(ctx, {"enabled": True, "approved_sources": list(dict.fromkeys(pol["approved_sources"] + new))})
        steps.append("Selected trusted, licensed training data: " + ", ".join(new) + ".")
        MEM.event(ctx, "data.selected", steps[-1] + (f" Skipped for storage limits: {', '.join(skipped)}." if skipped else ""))
    elif not pol["enabled"]:
        discovery.update(ctx, {"enabled": True})
    try:
        prep = discovery.ensure_data(ctx)
        steps.append(f"Data preparation: {prep.get('status', 'checked')}.")
    except Exception as e:  # noqa: BLE001 — preparation retries on its own; report it
        steps.append(f"Data preparation could not start yet: {str(e)[:200]}")
    S.update(ctx, {"enabled": True, "paused": False, "automatic": True})
    MEM.event(ctx, "engine.started", "Evolution started" + (" by the Owner" if actor_id else ""))
    engine.wake(ctx)
    return {"steps": steps, "status": status(ctx)}


def pause(ctx: Ctx, actor_id: int | None) -> dict:
    from moth_server.evolution import engine

    S.update(ctx, {"paused": True})
    MEM.event(ctx, "engine.paused", "Evolution paused" + (" by the Owner" if actor_id else "") +
              ". Running training stops at its next checkpoint; nothing is lost.")
    engine.wake(ctx)
    return {"status": status(ctx)}


STAGES = {"planning": "Planning", "waiting_for_compute": "Waiting for compute", "training": "Training",
          "evaluating": "Evaluating", "deploying": "Deploying", "monitoring": "Monitoring the new version"}


def status(ctx: Ctx) -> dict:
    """What MOTH is doing now and what it will do next, from recorded state only."""
    from moth_server import models as M
    from moth_server.evolution import engine
    from moth_server.intelligence import discovery

    s = S.get(ctx)
    st = engine.state(ctx)
    cyc = MEM.active_cycle(ctx)
    deployed = M.deployed(ctx)
    auto = ctx.db.get_config("evolution_autopilot", {}) or {}
    data = discovery.status(ctx)["state"]
    if not deployed:
        stage, doing = "genesis", "There is no model yet. Start Evolution to create one and train it from zero."
    elif not s["enabled"]:
        stage, doing = "off", "Evolution is turned off."
    elif s["paused"]:
        stage, doing = "paused", "Evolution is paused. Start it to continue from the latest checkpoint."
    elif cyc:
        stage = cyc["status"]
        waiting = (cyc.get("result") or {}).get("waiting_reason")
        doing = f"{STAGES.get(stage, stage.replace('_', ' ').capitalize())} (cycle #{cyc['id']})" + (f": {waiting}" if waiting else ".")
    elif data.get("status") in ("queued", "running", "preparing"):
        prog = data.get("progress")
        prog = prog.get("message") if isinstance(prog, dict) else prog
        stage, doing = "preparing_data", "Preparing training data" + (f": {prog}" if prog else ".")
    else:
        stage = "idle"
        doing = st.get("idle_reason") or "Waiting for the next cycle."
    return {"stage": stage, "running": bool(deployed and s["enabled"] and not s["paused"]),
            "doing": doing, "next_cycle_at": st.get("next_cycle_at") or None,
            "autopilot": bool(s.get("autopilot", True)),
            "plan": {k: auto.get(k) for k in ("steps", "lr", "batch_size")} if auto else None,
            "decisions": auto.get("decisions") or [], "data": {"status": data.get("status"), "error": data.get("error")}}
