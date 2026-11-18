"""1.1 Owner reports: candidates versus the live model, and where training time goes.

* ``candidates`` — the recent candidates next to the live model: validation loss, the overall change the
  gates measured, which gates failed and why, and which candidate each run continued from.
* ``speed`` — for recent finished experiments, the wall time split into preparing (planning and data),
  waiting for compute, training and evaluating, from the recorded timestamps and events.
"""

from __future__ import annotations

from typing import Any

from moth_server.evolution import memory as MEM

Ctx = Any


def _val(info: dict) -> float | None:
    tr = (info or {}).get("training") or {}
    v = tr.get("best_val") if tr.get("best_val") is not None else tr.get("val_loss")
    return float(v) if v is not None else None


def candidates(ctx: Ctx, limit: int = 20) -> dict[str, Any]:
    from moth_server import models as M

    live = M.deployed(ctx)
    live_val = _val(live["info"]) if live else None
    rows = []
    for e in MEM.experiments(ctx, limit=200):
        if not e.get("candidate_version"):
            continue
        cfg = e.get("config") or {}
        try:
            rel = M.release(ctx, int(e["candidate_version"]))
        except Exception:  # noqa: BLE001 — removed by retention
            rel = None
        gates = (e.get("metrics") or {}).get("gates") or []
        val = _val(rel["info"]) if rel else None
        rows.append({
            "experiment": e["id"], "cycle": e["cycle_id"], "status": e["status"], "version": e["candidate_version"],
            "base_version": e["base_version"], "method": cfg.get("method"), "strategy": cfg.get("strategy"),
            "continued_from": (cfg.get("continue_from") or {}).get("version"),
            "params": (rel or {}).get("info", {}).get("params"), "kept": rel is not None,
            "val_loss": val, "val_change": round((val - live_val) / live_val, 4) if val is not None and live_val else None,
            "improvement": (e.get("metrics") or {}).get("primary_improvement"),
            "failed_gates": [{"gate": g.get("gate"), "detail": g.get("detail"), "change": g.get("change")}
                             for g in gates if not g.get("passed")],
            "passed_gates": [g.get("gate") for g in gates if g.get("passed")],
            "reason": e.get("error"), "finished_at": e.get("finished_at"),
        })
        if len(rows) >= limit:
            break
    return {"live": {"version": live["version"], "val_loss": live_val, "params": live["info"].get("params")} if live else None,
            "candidates": rows}


PHASES = ("preparing", "waiting", "training", "evaluating")


def speed(ctx: Ctx, limit: int = 20) -> dict[str, Any]:
    trained: dict[int, float] = {}
    for ev in MEM.events(ctx, 1000):
        if ev["kind"] == "experiment.trained" and ev.get("experiment_id"):
            trained.setdefault(int(ev["experiment_id"]), float(ev["ts"]))  # newest first: keep the latest
    cycles: dict[int, dict | None] = {}
    rows, totals = [], dict.fromkeys(PHASES, 0.0)
    for e in MEM.experiments(ctx, limit=200):
        if not e.get("finished_at") or not e.get("started_at"):
            continue
        cid = e["cycle_id"]
        if cid not in cycles:
            cycles[cid] = MEM.cycle(ctx, cid)
        c = cycles[cid] or {}
        c_start = float(c.get("started_at") or c.get("created_at") or e["created_at"])
        created, started, finished = float(e["created_at"]), float(e["started_at"]), float(e["finished_at"])
        done_training = min(max(trained.get(e["id"], finished), started), finished)
        split = {"preparing": max(0.0, created - c_start), "waiting": max(0.0, started - created),
                 "training": done_training - started, "evaluating": finished - done_training}
        for k in PHASES:
            totals[k] += split[k]
        rows.append({"experiment": e["id"], "status": e["status"], "seconds": {k: round(v, 1) for k, v in split.items()},
                     "steps": int(((e.get("metrics") or {}).get("training") or {}).get("step") or 0),
                     "finished_at": finished})
        if len(rows) >= limit:
            break
    whole = sum(totals.values())
    share = {k: round(v / whole, 4) if whole else 0.0 for k, v in totals.items()}
    slowest = max(share, key=share.get) if whole else None
    tips = {"preparing": "Most time goes into planning and preparing data: the data library may be rebuilding.",
            "waiting": "Most time is spent waiting for compute: more workers, or fewer parallel experiments, help.",
            "training": "Most time is training itself, which is where it should go.",
            "evaluating": "Most time goes into evaluation: the benchmarks are slow on this server."}
    return {"experiments": rows, "total_seconds": {k: round(v, 1) for k, v in totals.items()}, "share": share,
            "slowest": slowest, "note": tips.get(slowest or "", "No finished experiments yet.")}
