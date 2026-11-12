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
PRIORITY = ["python-stdlib", "mbpp", "magicoder-oss", "codefeedback", "glaive-code", "gsm8k", "arc", "oasst1",
            "dolly-15k", "tinystories", "simple-wikipedia"]
GB = 1024 ** 3
MAX_SOURCE_CHARS = 64_000_000   # per source; the library grows towards this as the model needs more data

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


def adapt(ctx: Ctx, settings: dict, resources: dict | None = None,
          capacity: dict | None = None) -> tuple[dict, list[dict]]:
    """Return (settings for the next cycle, decisions). ``settings`` is never modified in place."""
    out = copy.deepcopy(settings)
    if not settings.get("autopilot", True):
        return out, []
    tr = out["training"]
    base_steps, base_lr, base_batch = int(tr["steps"]), float(tr["lr"]), int(tr["batch_size"])
    state = ctx.db.get_config("evolution_autopilot", {}) or {}
    # The Owner's settings win: when they changed since the plan was adapted, start again from them.
    if state.get("base") != [base_steps, base_lr, base_batch]:
        state = {}
    steps = int(state.get("steps") or base_steps)
    lr = float(state.get("lr") or base_lr)
    batch = int(state.get("batch_size") or base_batch)
    floor = min(MIN_STEPS, base_steps)  # never raise a deliberately small Owner setting
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
            new_steps = max(floor, base_steps if steps > base_steps else steps)
            why = (f"stopped early ({(early[0]['metrics'] or {}).get('early_stopped')})" if early
                   else f"improved held-out results by only {_pct(last)} and {_pct(prev)} (I need {_pct(min_gain)})")
            decide("lr", f"Training has slowed down: the last two runs {why}. I'm testing a lower learning rate "
                   f"({new_lr:.1e} instead of {lr:.1e})" + (f" and returning to {new_steps} steps." if new_steps != steps else "."),
                   improvements=[last, prev], lr_before=lr, lr_after=new_lr, steps_before=steps, steps_after=new_steps)
            lr, steps = new_lr, new_steps
        elif early and steps > floor:
            stopped = int(((early[0]["metrics"] or {}).get("training") or {}).get("step") or steps)
            new = max(floor, min(steps, int(stopped * 1.2)))
            if new < steps:
                decide("steps", f"Experiment #{early[0]['id']} stopped improving at step {stopped}, so I'm planning "
                       f"{new} steps instead of {steps} to save compute.", steps_before=steps, steps_after=new,
                       stopped_at=stopped)
                steps = new

    # Capability-based assessment (capacity.py): a model that has seen very little text for its size
    # gets longer foundation runs — still fitted into the time budget below.
    if capacity and capacity.get("action") == "foundation_training" and steps < min(MAX_STEPS, base_steps * 2):
        new = min(MAX_STEPS, base_steps * 2)  # twice the Owner's steps at most; never compounding
        decide("steps", f"Foundation training: MOTH has trained on only {capacity.get('tokens_per_param', 0):g} tokens "
               f"per parameter, so I'm training longer: {new} steps instead of {steps}.",
               steps_before=steps, steps_after=new, tokens_per_param=capacity.get("tokens_per_param"))
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
            new = max(floor, fit)
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

    # 0.6.3: Evolution is continuous — no waiting between rounds, also after rounds without an accepted
    # improvement. Endless repetition is prevented by the plan itself (configurations already tried are
    # skipped; the capability assessment changes data, training or architecture when progress stalls).

    tr["steps"], tr["lr"], tr["batch_size"] = int(steps), float(lr), int(batch)
    return out, decisions


def remember(ctx: Ctx, settings: dict, decisions: list[dict], cycle_id: int | None, owner_settings: dict | None = None) -> None:
    """Keep the adapted plan for the next cycle and record each decision in the activity stream."""
    tr = settings["training"]
    otr = (owner_settings or settings)["training"]
    base = [int(otr["steps"]), float(otr["lr"]), int(otr["batch_size"])]
    ctx.db.set_config("evolution_autopilot", {"steps": tr["steps"], "lr": tr["lr"], "batch_size": tr["batch_size"],
                                              "base": base,
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
    # Scale the download budget with the storage actually free (5 %, between 256 MB and 20 GB).
    free = shutil.disk_usage(library.root(ctx)).free
    budget = int(min(20 * GB, max(256 * 1024**2, free * 0.05)))
    if budget > pol["max_download_bytes"]:
        discovery.update(ctx, {"max_download_bytes": budget})
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
    extra = command_center(ctx, cyc, st, data)
    return {**extra, "stage": stage, "running": bool(deployed and s["enabled"] and not s["paused"]),
            "doing": doing, "next_cycle_at": st.get("next_cycle_at") or None,
            "autopilot": bool(s.get("autopilot", True)),
            "plan": {k: auto.get(k) for k in ("steps", "lr", "batch_size")} if auto else None,
            "decisions": auto.get("decisions") or [], "data": {"status": data.get("status"), "error": data.get("error")},
            "intelligence": intelligence(ctx, st, deployed)}


def intelligence(ctx: Ctx, st: dict, deployed: dict | None) -> dict | None:
    """The latest capability assessment (capacity.py), the model's verified size and growth outcomes."""
    from moth_server import models as M
    from moth_server.evolution import capacity as CAP

    if not deployed:
        return None
    info = deployed.get("info") or {}
    attempts = []
    for e in CAP.growth_attempts(ctx, limit=200)[:3]:
        g = (e.get("config") or {}).get("grow") or {}
        cand = M.release(ctx, e["candidate_version"]) if e.get("candidate_version") else None
        measured = ((cand or {}).get("info") or {}).get("params_measured") or {}
        attempts.append({"experiment": e["id"], "status": e["status"], "params_before": g.get("params_before"),
                         "params_after": measured.get("total") or g.get("params_after"),
                         "measured": bool(measured.get("total")), "candidate": e.get("candidate_version"),
                         "error": e.get("error"), "improvement": (e.get("metrics") or {}).get("primary_improvement")})
    return {"assessment": st.get("capacity"), "params": info.get("params"), "params_verified": M.params_verified(info),
            "version": deployed["version"], "growth_attempts": attempts}


# ---- evolution memory: which strategies worked --------------------------------------------------------------
def strategy_stats(ctx: Ctx, limit: int = 60) -> dict[str, dict]:
    """Per training strategy on this lineage: runs, accepted improvements and mean held-out improvement."""
    stats: dict[str, dict] = {}
    for e in MEM.experiments(ctx, limit=limit):
        key = (e.get("config") or {}).get("strategy")
        imp = _improvement(e)
        if not key or e["status"] not in ("passed", "rejected", "deployed") or imp is None:
            continue
        st = stats.setdefault(key, {"runs": 0, "passed": 0, "total": 0.0})
        st["runs"] += 1
        st["passed"] += int(e["status"] in ("passed", "deployed"))
        st["total"] += imp
    for st in stats.values():
        st["mean_improvement"] = st["total"] / st["runs"]
    return stats


def rank_strategies(ctx: Ctx, candidates: list[str]) -> tuple[list[str], str | None]:
    """Order strategies by recorded success; untried ones keep their place so they still get explored."""
    stats = strategy_stats(ctx)
    uniq = list(dict.fromkeys(candidates))
    tried = [k for k in uniq if stats.get(k, {}).get("runs", 0) >= 2]
    if len(tried) < 2:
        return uniq, None

    def score(k: str) -> tuple:
        st = stats[k]
        return (st["passed"] / st["runs"], st["mean_improvement"])
    best = sorted(tried, key=score, reverse=True)
    ranked = best + [k for k in uniq if k not in best]
    if ranked == uniq:
        return ranked, None
    a, b = best[0], best[1]
    sa, sb = stats[a], stats[b]
    note = (f"{a.capitalize()} training improved held-out results in {sa['passed']} of {sa['runs']} runs "
            f"(mean {sa['mean_improvement'] * 100:+.1f}%) versus {sb['passed']} of {sb['runs']} for {b} "
            f"(mean {sb['mean_improvement'] * 100:+.1f}%), so {a} experiments run first.")
    return ranked, note


# ---- data scaling: grow the library when the model has trained on it many times over ---------------------
def scale_data(ctx: Ctx, force: bool = False, reason: str | None = None) -> dict | None:
    """Double the per-source sample when the lineage has trained on more than 3x the prepared tokens
    (or now, with ``force``, when the capability assessment found the data too thin)."""
    from moth_server import models as M
    from moth_server.intelligence import discovery, library

    dep = M.deployed(ctx)
    build = library.latest_ready(ctx)
    pol = discovery.policy(ctx)
    if not dep or not build or not pol.get("enabled") or pol["max_source_chars"] >= MAX_SOURCE_CHARS:
        return None
    import json as _json

    manifest = build.get("manifest")
    manifest = _json.loads(manifest) if isinstance(manifest, str) else (manifest or {})
    prepared = sum(int(v.get("train", 0)) if isinstance(v, dict) else int(v or 0)
                   for v in (manifest.get("token_counts") or {}).values())
    trained = int(((dep.get("info") or {}).get("lineage_totals") or {}).get("tokens") or 0)
    if prepared <= 0 or (trained < 3 * prepared and not force):
        return None
    new = min(MAX_SOURCE_CHARS, int(pol["max_source_chars"]) * 2)
    discovery.update(ctx, {"max_source_chars": new})
    why = (reason + ", so" if force and reason else
           f"MOTH has trained on {trained:,} tokens, more than three times the {prepared:,} prepared, so")
    MEM.event(ctx, "data.scaled", f"{why} each source now contributes up to {new:,} characters instead of "
              f"{pol['max_source_chars']:,}. The larger library is prepared in the background; training continues meanwhile.",
              trained_tokens=trained, prepared_tokens=prepared, max_source_chars=new)
    try:
        discovery.ensure_data(ctx)
    except Exception:  # noqa: BLE001 — preparation retries on its own
        pass
    return {"max_source_chars": new, "trained": trained, "prepared": prepared}


# ---- which data helped: measured per-domain effect on held-out results ------------------------------------
def data_effects(ctx: Ctx, limit: int = 60) -> dict[str, dict]:
    """For each training domain: the held-out improvement of experiments, weighted by that domain's share
    of their mixture, compared with the average over all experiments. Positive = above average."""
    rows = []
    for e in MEM.experiments(ctx, limit=limit):
        imp = _improvement(e)
        w = (((e.get("config") or {}).get("mixture") or {}).get("weights")) or {}
        if imp is not None and w and e["status"] in ("passed", "rejected", "deployed"):
            rows.append((w, imp))
    if len(rows) < 4:
        return {}
    mean = sum(i for _, i in rows) / len(rows)
    out: dict[str, dict] = {}
    for d in {d for w, _ in rows for d in w}:
        total_w = sum(w.get(d, 0.0) for w, _ in rows)
        if total_w <= 0:
            continue
        weighted = sum(w.get(d, 0.0) * i for w, i in rows) / total_w
        out[d] = {"effect": weighted - mean, "experiments": sum(1 for w, _ in rows if w.get(d, 0) > 0)}
    return out


def apply_data_effects(ctx: Ctx, mix: dict) -> tuple[dict, str | None]:
    """Shift a mixture modestly (at most +/-30 % per domain) towards domains that measurably helped."""
    eff = data_effects(ctx)
    w = dict(mix.get("weights") or {})
    if not eff or not w:
        return mix, None
    scale = max(abs(v["effect"]) for v in eff.values()) or 1.0
    new = {d: max(0.0, v * (1 + 0.3 * (eff.get(d, {}).get("effect", 0.0) / scale))) for d, v in w.items()}
    total = sum(new.values()) or 1.0
    new = {d: v / total for d, v in new.items()}
    best = max((d for d in w if d in eff), key=lambda d: eff[d]["effect"], default=None)
    if best is None or eff[best]["effect"] <= 0:
        return mix, None
    note = (f"Training mixtures with more {best} data improved held-out results by "
            f"{eff[best]['effect'] * 100:+.2f} points more than average over {eff[best]['experiments']} experiments, "
            f"so the next mixture gives {best} {new[best] * 100:.0f}% instead of {w[best] * 100:.0f}%.")
    return {**mix, "weights": new}, note


def command_center(ctx: Ctx, cyc: dict | None, st: dict, data: dict) -> dict:
    """Live facts for AI → Evolution: objective, workers and their tasks, data, versions, bottleneck."""
    import json as _json

    from sqlalchemy import select

    from moth_server import models as M
    from moth_server.db import training_jobs, workers
    from moth_server.evolution import compute as C

    exps = MEM.experiments(ctx, cyc["id"]) if cyc else []
    running = [e for e in exps if e["status"] == "running"]
    objective = next((e.get("rationale") for e in running), None) or next((e.get("rationale") for e in exps
                                                                           if e["status"] in ("planned", "waiting")), None)
    jobs = ctx.db.all(select(training_jobs).where(training_jobs.c.status.in_(("queued", "leased"))))
    by_worker = {j["worker_id"]: j for j in jobs if j["worker_id"]}
    now_ = now()
    ws = []
    for w in ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None))):
        online = (w.get("last_heartbeat_at") or 0) >= now_ - 180 and w["status"] == "online"
        hw = _json.loads(w["hardware"] or "{}")
        j = by_worker.get(w["id"])
        ws.append({"id": w["id"], "name": w["name"], "online": online, "paused": bool(w["paused"]),
                   "compute": "GPU" if hw.get("compute") == "gpu" or (hw.get("compute") is None and hw.get("gpus")) else "CPU",
                   "gflops": (hw.get("benchmark") or {}).get("gflops"),
                   "task": {"kind": j["kind"], "progress": j.get("progress")} if j else None})
    queued = sum(1 for j in jobs if j["status"] == "queued")
    dep = M.deployed(ctx)
    prev_v = st.get("stable_version") if st.get("stable_version") != (dep or {}).get("version") else None
    if prev_v is None and dep:
        prev = next((r for r in M.list_releases(ctx) if r["status"] == "published" and r.get("previously_deployed")
                     and r["version"] != dep["version"] and r.get("path")), None)
        prev_v = prev["version"] if prev else None
    hw = C.local(ctx)
    mem = hw.get("memory") or {}
    bottleneck = None
    waiting = (cyc.get("result") or {}).get("waiting_reason") if cyc else None
    if waiting:
        bottleneck = waiting[0].upper() + waiting[1:]
    elif queued and not any(x["online"] and not x["paused"] for x in ws):
        bottleneck = f"{queued} job(s) wait for a MOTH worker, but none is online."
    elif data.get("status") in ("queued", "running", "preparing") and not running:
        bottleneck = "Training waits for data preparation to finish."
    elif mem.get("percent") and mem["percent"] > 90:
        bottleneck = f"MOTH Cloud's memory is {mem['percent']:.0f}% used; training slows down or waits to protect answering."
    return {"objective": objective, "workers": ws, "queued_jobs": queued,
            "parallel": len(running), "versions": {"active": (dep or {}).get("version"), "previous": prev_v},
            "bottleneck": bottleneck}
