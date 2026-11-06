"""Training memory: what MOTH remembers about its own evolution (structured, persistent).

Runs and their reproducible configurations, datasets used (by id and hash — never contents),
evaluation results and regressions, successful and unsuccessful experiments, weaknesses, resource
use and duration, checkpoint lineage and model ancestry. Survives restarts and upgrades (database).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import and_, delete, desc, func, select

from moth_server.context import Ctx
from moth_server.db import (
    evaluation_reports, evolution_cycles, evolution_events, evolution_experiments, model_lineage, now,
)

TERMINAL_CYCLE = ("completed", "rejected", "failed", "cancelled", "rolled_back")
TERMINAL_EXPERIMENT = ("passed", "rejected", "failed", "cancelled")


def config_hash(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


def event(ctx: Ctx, kind: str, message: str, level: str = "info", cycle_id: int | None = None,
          experiment_id: int | None = None, conn=None, **data: Any) -> None:
    values = dict(ts=now(), cycle_id=cycle_id, experiment_id=experiment_id, level=level, kind=kind[:48],
                  message=message[:2000], data=json.dumps(data, default=str)[:8000])
    if conn is not None:
        conn.execute(evolution_events.insert().values(**values))
    else:
        with ctx.db.tx() as c:
            c.execute(evolution_events.insert().values(**values))


def _row(r: dict | None, *json_cols: str) -> dict | None:
    if r is None:
        return None
    out = dict(r)
    for c in json_cols:
        if c in out and isinstance(out[c], str):
            try:
                out[c] = json.loads(out[c])
            except ValueError:
                pass
    return out


def cycle(ctx: Ctx, cid: int) -> dict | None:
    return _row(ctx.db.one(select(evolution_cycles).where(evolution_cycles.c.id == cid)), "plan", "result")


def active_cycle(ctx: Ctx) -> dict | None:
    return _row(ctx.db.one(select(evolution_cycles).where(evolution_cycles.c.status.notin_(TERMINAL_CYCLE))
                           .order_by(evolution_cycles.c.id)), "plan", "result")


def cycles(ctx: Ctx, limit: int = 50) -> list[dict]:
    return [_row(r, "plan", "result") for r in
            ctx.db.all(select(evolution_cycles).order_by(desc(evolution_cycles.c.id)).limit(limit))]


def experiment(ctx: Ctx, eid: int) -> dict | None:
    return _row(ctx.db.one(select(evolution_experiments).where(evolution_experiments.c.id == eid)),
                "config", "metrics", "resources")


def experiments(ctx: Ctx, cycle_id: int | None = None, limit: int = 100) -> list[dict]:
    q = select(evolution_experiments).order_by(desc(evolution_experiments.c.id)).limit(limit)
    if cycle_id is not None:
        q = q.where(evolution_experiments.c.cycle_id == cycle_id)
    return [_row(r, "config", "metrics", "resources") for r in ctx.db.all(q)]


def update_cycle(ctx: Ctx, cid: int, conn=None, **values: Any) -> None:
    for k in ("plan", "result"):
        if k in values and not isinstance(values[k], str):
            values[k] = json.dumps(values[k], default=str)
    values["updated_at"] = now()
    stmt = evolution_cycles.update().where(evolution_cycles.c.id == cid).values(**values)
    if conn is not None:
        conn.execute(stmt)
    else:
        with ctx.db.tx() as c:
            c.execute(stmt)


def update_experiment(ctx: Ctx, eid: int, conn=None, **values: Any) -> None:
    for k in ("config", "metrics", "resources"):
        if k in values and not isinstance(values[k], str):
            values[k] = json.dumps(values[k], default=str)
    values["updated_at"] = now()
    stmt = evolution_experiments.update().where(evolution_experiments.c.id == eid).values(**values)
    if conn is not None:
        conn.execute(stmt)
    else:
        with ctx.db.tx() as c:
            c.execute(stmt)


def tried(ctx: Ctx, cfg_hash: str) -> dict | None:
    """The most recent finished experiment with exactly this configuration (same base, data, settings)."""
    return _row(ctx.db.one(select(evolution_experiments).where(
        evolution_experiments.c.config_hash == cfg_hash,
        evolution_experiments.c.status.in_(("passed", "rejected", "failed")))
        .order_by(desc(evolution_experiments.c.id))), "config", "metrics")


def history_for_architecture(ctx: Ctx, arch_key: str, limit: int = 200) -> list[dict]:
    """Finished experiments on this architecture, with outcome and measured improvement."""
    out = []
    for r in ctx.db.all(select(evolution_experiments).where(
            evolution_experiments.c.status.in_(("passed", "rejected", "failed")))
            .order_by(desc(evolution_experiments.c.id)).limit(limit)):
        e = _row(r, "config", "metrics")
        if (e["config"] or {}).get("architecture_key") == arch_key:
            out.append(e)
    return out


# ---- lineage -----------------------------------------------------------------------------------
def record_lineage(ctx: Ctx, version: int, parent: int | None, method: str, cycle_id: int | None = None,
                   experiment_id: int | None = None, datasets: list[str] | None = None, conn=None) -> None:
    def write(c) -> None:
        if c.execute(select(model_lineage.c.version).where(model_lineage.c.version == version)).first():
            return
        c.execute(model_lineage.insert().values(version=version, parent_version=parent, method=method,
                                                cycle_id=cycle_id, experiment_id=experiment_id,
                                                datasets=json.dumps(datasets or []), created_at=now()))
    if conn is not None:
        write(conn)
    else:
        with ctx.db.tx() as c:
            write(c)


def lineage(ctx: Ctx) -> list[dict]:
    return [_row(r, "datasets") for r in ctx.db.all(select(model_lineage).order_by(model_lineage.c.version))]


def ancestors(ctx: Ctx, version: int) -> list[dict]:
    rows = {r["version"]: r for r in lineage(ctx)}
    out, v, seen = [], version, set()
    while v is not None and v in rows and v not in seen:
        seen.add(v)
        out.append(rows[v])
        v = rows[v]["parent_version"]
    return out


def datasets_used_by_lineage(ctx: Ctx, version: int) -> set[str]:
    used: set[str] = set()
    for a in ancestors(ctx, version):
        used.update(a.get("datasets") or [])
    return used


# ---- evaluation reports ---------------------------------------------------------------------------
def report(ctx: Ctx, version: int, suite_sha: str) -> dict | None:
    r = ctx.db.one(select(evaluation_reports).where(and_(evaluation_reports.c.model_version == version,
                                                         evaluation_reports.c.suite_sha == suite_sha)))
    return json.loads(r["metrics"]) if r else None


def save_report(ctx: Ctx, version: int, suite: str, suite_sha: str, metrics: dict) -> None:
    with ctx.db.tx() as c:
        c.execute(delete(evaluation_reports).where(and_(evaluation_reports.c.model_version == version,
                                                        evaluation_reports.c.suite_sha == suite_sha)))
        c.execute(evaluation_reports.insert().values(model_version=version, suite=suite[:64], suite_sha=suite_sha,
                                                     metrics=json.dumps(metrics, default=str), created_at=now()))


def reports_for(ctx: Ctx, version: int) -> list[dict]:
    return [_row(r, "metrics") for r in ctx.db.all(select(evaluation_reports).where(
        evaluation_reports.c.model_version == version).order_by(evaluation_reports.c.suite))]


# ---- retention ------------------------------------------------------------------------------------
def prune(ctx: Ctx, retention_days: float) -> int:
    """Delete evolution events older than the retention period. Model versions, lineage, evaluation
    reports and experiment records are kept (they are small and needed for rollback and planning)."""
    cutoff = now() - retention_days * 86400
    with ctx.db.tx() as c:
        n = c.execute(delete(evolution_events).where(evolution_events.c.ts < cutoff)).rowcount
    return int(n or 0)


def events(ctx: Ctx, limit: int = 100, cycle_id: int | None = None, experiment_id: int | None = None,
           level: str | None = None) -> list[dict]:
    q = select(evolution_events).order_by(desc(evolution_events.c.id)).limit(limit)
    if cycle_id is not None:
        q = q.where(evolution_events.c.cycle_id == cycle_id)
    if experiment_id is not None:
        q = q.where(evolution_events.c.experiment_id == experiment_id)
    if level:
        q = q.where(evolution_events.c.level == level)
    return [_row(r, "data") for r in ctx.db.all(q)]


def compute_seconds_since(ctx: Ctx, since: float) -> float:
    v = ctx.db.one(select(func.coalesce(func.sum(evolution_experiments.c.compute_seconds), 0.0).label("s"))
                   .where(evolution_experiments.c.updated_at >= since))
    return float(v["s"] if v else 0.0)
