"""Evaluation on CPU workers (0.5.3): slower workers measure candidates while faster ones train.

For each held-out capability suite of a candidate (``capability:holdout:<domain>``), the server prepares
exactly the token data that suite scores (same records, same truncation, same token budget — tokenized
with the candidate's tokenizer) and creates **two** ``eval_loss`` jobs, preferably for CPU workers. Each
worker computes the masked negative log-likelihood sum and token count with the candidate's verified
weights. The result is accepted only when two different workers agree (relative difference below 1e-4);
it is then stored as the suite's report, so the gate does not recompute it. Disagreement or a timeout
means the server measures the suite itself — a worker can never make a candidate look better.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import now, training_jobs, workers
from moth_server.evolution import memory as MEM

MIN_WORKER_VERSION = (0, 5, 3)
AGREEMENT = 1e-4


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _version_ok(v: str | None) -> bool:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3]) >= MIN_WORKER_VERSION
    except ValueError:
        return False


def eligible_workers(ctx: Ctx) -> list[dict]:
    t = now()
    return [w for w in ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
            if (w["last_heartbeat_at"] or 0) >= t - 180 and not w["paused"] and _version_ok(w["version"])]


def prepare_data(suite_path: Path, tokenizer, max_seq_len: int, dest: Path, limit: int = 200,
                 max_tokens: int = 80_000) -> int:
    """The token data ``moth.model.capabilities.holdout_suite`` scores, as tensors for a worker."""
    import torch

    from moth.model.chat_format import Message, encode_chat

    ids_all, mask_all, offsets, count = [], [], [0], 0
    with open(suite_path, encoding="utf-8") as f:
        for n, line in enumerate(f):
            if n >= limit:
                break
            if not line.strip():
                continue
            rec = json.loads(line)
            if "messages" in rec:
                ids, mask = encode_chat(tokenizer, [Message(m["role"], m["content"]) for m in rec["messages"]],
                                        add_generation_prompt=False)
            else:
                ids = [tokenizer.bos_id] + tokenizer.encode(rec["text"])
                mask = [0] + [1] * (len(ids) - 1)
            ids, mask = ids[:max_seq_len], mask[:max_seq_len]
            if len(ids) < 2 or sum(mask[1:]) == 0:
                continue
            ids_all += ids
            mask_all += mask
            offsets.append(len(ids_all))
            count += sum(mask[1:])
            if count >= max_tokens:
                break
    torch.save({"ids": torch.tensor(ids_all, dtype=torch.int64), "mask": torch.tensor(mask_all, dtype=torch.uint8),
                "offsets": torch.tensor(offsets, dtype=torch.int64)}, dest)
    return count


def ensure(ctx: Ctx, exp: dict, cand: dict, settings: dict) -> bool:
    """Create the evaluation jobs for a candidate (once). True while results are still worth waiting for."""
    from moth.model.tokenizer import Tokenizer

    from moth_server.evolution.evaluation import capability_suites

    d = settings.get("distributed") or {}
    if not d.get("eval_on_workers", True):
        return False
    state = (exp.get("metrics") or {}).get("remote_eval")
    if state is None:
        if len(eligible_workers(ctx)) < 2:
            return False
        suites = [s for s in capability_suites(ctx) if s["capability"] == "holdout"
                  and MEM.report(ctx, cand["version"], s["sha"]) is None]
        if not suites:
            return False
        pkg = Path(cand["path"])
        tok = Tokenizer.load(pkg / "tokenizer.json")
        cfg = json.loads((pkg / "config.json").read_text())
        out_dir = Path(ctx.settings.data_dir) / "evolution" / "eval-jobs" / f"v{cand['version']:05d}"
        out_dir.mkdir(parents=True, exist_ok=True)
        jobs = {}
        with ctx.db.tx() as c:
            for s in suites:
                data = out_dir / f"{s['id'].replace(':', '_')}.pt"
                prepare_data(Path(s["path"]), tok, int(cfg["max_seq_len"]), data, limit=int(s.get("limit", 200)))
                for replica in (0, 1):
                    spec = {"eval": {"version": cand["version"], "suite_id": s["id"], "suite_sha": s["sha"],
                                     "replica": replica, "data": str(data)},
                            "round": -1, "base_sha256": cand["sha256"], "model_config": cfg,
                            "shard_id": s["id"], "shard_sha256": _sha(data), "job_id": f"eval-{cand['version']}-{s['id']}-{replica}",
                            "requirements": {"memory_bytes": 0}, "prefer_cpu": True}
                    jid = c.execute(training_jobs.insert().values(kind="eval_loss", status="queued",
                                                                  spec=json.dumps(spec), attempts=0, max_attempts=2,
                                                                  created_at=now(), updated_at=now())).inserted_primary_key[0]
                    jobs.setdefault(s["id"], []).append(jid)
        state = {"jobs": jobs, "started": now(), "accepted": [], "disagreed": []}
        MEM.update_experiment(ctx, exp["id"], metrics={**(exp.get("metrics") or {}), "remote_eval": state})
        MEM.event(ctx, "evaluation.remote", f"Experiment #{exp['id']}: {len(jobs)} held-out evaluation(s) of "
                  f"v{cand['version']} sent to CPU workers (two independent results each)",
                  cycle_id=exp["cycle_id"], experiment_id=exp["id"])
    collect(ctx, exp, cand, state)
    waiting = [sid for sid in state["jobs"] if sid not in state["accepted"] and sid not in state["disagreed"]]
    if waiting and now() - float(state["started"]) < float(d.get("eval_wait_minutes", 10)) * 60:
        return True
    return False


def collect(ctx: Ctx, exp: dict, cand: dict, state: dict) -> None:
    changed = False
    for sid, ids in state["jobs"].items():
        if sid in state["accepted"] or sid in state["disagreed"]:
            continue
        rows = [ctx.db.one(select(training_jobs).where(training_jobs.c.id == j)) for j in ids]
        if not all(r and r["status"] == "completed" for r in rows):
            continue
        res = [json.loads(r["result"] or "{}") for r in rows]
        a, b = (x.get("loss") for x in res)
        same_worker = rows[0]["worker_id"] == rows[1]["worker_id"]
        if a is None or b is None or same_worker or abs(a - b) > AGREEMENT * max(abs(a), 1e-9):
            state["disagreed"].append(sid)
        else:
            spec = json.loads(rows[0]["spec"])["eval"]
            MEM.save_report(ctx, cand["version"], sid, spec["suite_sha"],
                            {"metric": "loss", "value": (a + b) / 2, "tokens": res[0].get("count"),
                             "higher_is_better": False, "ok": True,
                             "computed_by": [rows[0]["worker_id"], rows[1]["worker_id"]]})
            state["accepted"].append(sid)
        changed = True
    if changed:
        MEM.update_experiment(ctx, exp["id"], metrics={**(exp.get("metrics") or {}), "remote_eval": state})


def files(ctx: Ctx, spec: dict) -> tuple[Path, Path]:
    from moth_server import models as M

    rel = M.release(ctx, int(spec["eval"]["version"]))
    return Path(rel["path"]) / "model.pt", Path(spec["eval"]["data"])


def accept(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    spec = json.loads(job_row["spec"])
    others = [r for r in ctx.db.all(select(training_jobs).where(training_jobs.c.kind == "eval_loss",
                                                                  training_jobs.c.status == "completed"))
              if json.loads(r["spec"])["eval"]["suite_id"] == spec["eval"]["suite_id"]
              and json.loads(r["spec"])["eval"]["version"] == spec["eval"]["version"]]
    if any(r["worker_id"] == job_row["worker_id"] for r in others):
        return {"accepted": False, "reasons": ["the second result must come from a different worker"]}
    if meta.get("base_sha256") != spec["base_sha256"]:
        return {"accepted": False, "reasons": ["evaluated different weights"]}
    try:
        res = json.loads(payload)
        total, count = float(res["total"]), int(res["count"])
    except (ValueError, KeyError, TypeError):
        return {"accepted": False, "reasons": ["unreadable evaluation result"]}
    if count <= 0 or not (total == total) or total < 0:
        return {"accepted": False, "reasons": ["invalid evaluation result"]}
    return {"accepted": True, "loss": total / count, "count": count}
