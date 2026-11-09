"""Distributed training of one evolution experiment across several MOTH workers (0.5.3).

Local-SGD rounds (the "DiLoCo" family, with plain averaging as the outer step):

1. Round ``r`` has one set of weights on the server. Every participant gets a *shard job*: the round's
   weights, its own slice of the curriculum data (a different sample per participant) and ``local_steps``.
2. Each participant trains on its slice and returns its weight delta. The server checks it (base hash,
   round, shapes, finite values, size bound) and stores it once — a repeated or late submission for an
   old round is refused, so no training step is counted twice.
3. When every shard of the round is in (or enough of them after a failure), the deltas are averaged
   weighted by the tokens each participant trained. The averaged update is applied only if the server's
   own probe loss on held-out data does not get worse beyond a small tolerance; otherwise the round is
   discarded and the previous weights are kept. Either way the next round starts from verified weights.
4. After the last round the weights become a candidate package that goes through the normal gates.

Participants are any compatible online workers — CPU or GPU, including MOTH Code computers that joined
— and the work per participant follows its measured speed. Disconnections are handled by the job
leases: an expired shard goes back to the queue and is picked up by another participant.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from moth_server.evolution.native_reset import next_job_values
from moth_server.context import Ctx
from moth_server.db import now, training_jobs, workers
from moth_server.evolution import memory as MEM

PROBE_TOLERANCE = 0.05
ONLINE_SECONDS = 180


def participants(ctx: Ctx, need_bytes: int, worker_ids: list[int] | None = None) -> list[dict]:
    from moth_server.training import fits, worker_allowed

    t = now()
    out = []
    for w in ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None))):
        if not worker_allowed(ctx, w):
            continue
        if worker_ids is not None and w['id'] not in worker_ids:
            continue
        if (w.get("last_heartbeat_at") or 0) < t - ONLINE_SECONDS or w.get("paused"):
            continue
        hw = json.loads(w["hardware"] or "{}")
        if fits(hw, {"requirements": {"memory_bytes": need_bytes}}, json.loads(w['limits'] or '{}')):
            out.append({**w, "hw": hw})
    # Prefer workers with a history of verified useful work; new and slower devices remain eligible.
    out.sort(key=lambda w: (w['verified_jobs'] + 1) / (w['verified_jobs'] + w['failed_jobs'] + 2), reverse=True)
    # Keep work on compatible GPUs when they exist; CPU participants remain the fallback.
    gpu = [w for w in out if w["hw"].get("compute") == "gpu"]
    return gpu or out


def available(ctx: Ctx, settings: dict, need_bytes: int) -> tuple[bool, int]:
    d = settings.get("distributed") or {}
    if not d.get("enabled", True) or not (settings.get("backends") or {}).get("workers", True):
        return False, 0
    n = len(participants(ctx, need_bytes, settings.get("worker_ids")))
    return n >= int(d.get("min_participants", 2)), n


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _round_weights(rd: Path, r: int) -> Path:
    return rd / f"round-{r:03d}.pt"


def start(ctx: Ctx, exp: dict, settings: dict, need_bytes: int) -> dict:
    """Create round 0 (from the development checkpoint or the base weights) and its shard jobs."""
    import torch

    from moth_server import models as M
    from moth_server.evolution.backends import run_dir, worker_training_supported
    from moth_server.evolution import datasets as DS

    cfg = exp["config"]
    base = M.release(ctx, exp["base_version"])
    rd = run_dir(ctx, exp)
    rd.mkdir(parents=True, exist_ok=True)
    d = settings.get("distributed") or {}
    people = participants(ctx, need_bytes, settings.get("worker_ids"))
    n = max(int(d.get("min_participants", 2)), min(int(d.get("max_participants", 8)), len(people)))
    rounds = max(1, int(d.get("rounds", 3)))
    local_steps = max(1, math.ceil(int(cfg["steps"]) / rounds))
    dev = (base["info"].get("dev_checkpoint") or {})
    src = Path(dev["path"]) if dev.get("path") else Path(base["path"]) / "model.pt"
    expected_sha = dev.get("sha256") if dev.get("path") else base["sha256"]
    if not src.is_file() or not expected_sha or _sha(src) != expected_sha:
        raise ValueError("distributed training requires an intact, checksum-verified base checkpoint")
    if not worker_training_supported(ctx, exp):
        raise ValueError("assistant-masked data cannot use token-only distributed shards")
    raw = torch.load(src, map_location="cpu", weights_only=False)
    state = raw["model"] if isinstance(raw, dict) and "model" in raw else raw
    torch.save({k: v.float() if v.is_floating_point() else v for k, v in state.items()}, _round_weights(rd, 0))
    # probe: held-out tokens the server uses to accept or discard each round's update
    if cfg.get("mixture"):
        from moth_server.evolution.v2 import write_mixture_shard

        for i in range(n):
            write_mixture_shard(cfg["mixture"]["path"], cfg["mixture"]["weights"],
                                local_steps * int(cfg["batch_size"]) * int(cfg["seq_len"]) * rounds * 2,
                                int(cfg["seed"]) * 1000 + i, rd / f"shard-{i}.bin")
        _probe_from_mixture(cfg["mixture"], rd / "probe.bin")
    else:
        import numpy as np

        ds = DS.get(ctx, exp["dataset_id"])
        DS.write_shard(ds, rd / "train-all.bin")
        toks = np.fromfile(rd / "train-all.bin", dtype=np.uint32)
        for i, part in enumerate(np.array_split(toks, n)):
            part.tofile(rd / f"shard-{i}.bin")
        val = np.fromfile(Path(ds["path"]) / "val.bin", dtype=np.dtype(DS.meta(ds).get("dtype", "uint32")))
        val[:64 * 1024].astype(np.uint32).tofile(rd / "probe.bin")
    state_info = {"round": 0, "rounds": rounds, "shards": n, "local_steps": local_steps, "history": [],
                  "worker_ids": settings.get("worker_ids"),
                  "weights_sha256": _sha(_round_weights(rd, 0)), "started_from": "dev_checkpoint" if dev else "weights",
                  "jobs": {}}
    _create_round_jobs(ctx, exp, base, state_info, need_bytes)
    return state_info


def _probe_from_mixture(mixture: dict, dest: Path) -> None:
    import numpy as np

    mix = json.loads((Path(mixture["path"]) / "mixture.json").read_text())
    parts = []
    for d, w in mixture["weights"].items():
        info = mix["domains"].get(d)
        if not info or w <= 0:
            continue
        meta = json.loads((Path(mixture["path"]) / info["dir"] / "meta.json").read_text())
        val = np.fromfile(Path(mixture["path"]) / info["dir"] / "val.bin", dtype=np.dtype(meta["dtype"]))
        parts.append(val[: max(1024, int(32 * 1024 * w))].astype(np.uint32))
    np.concatenate(parts).tofile(dest)


def _create_round_jobs(ctx: Ctx, exp: dict, base: dict, st: dict, need_bytes: int,
                       only: list[int] | None = None) -> None:
    from moth.community.protocol import PROTOCOL

    from moth_server.evolution.backends import run_dir

    cfg = exp["config"]
    rd = run_dir(ctx, exp)
    r = st["round"]
    jobs = st["jobs"].setdefault(str(r), {})
    with ctx.db.tx() as c:
        for i in (only if only is not None else range(st["shards"])):
            spec = {"evolution_experiment": exp["id"], "round": r, "dist": {"round": r, "shard": i},
                    "worker_ids": st.get("worker_ids"),
                    "model_version": base["version"], "base_sha256": st["weights_sha256"],
                    "model_config": json.loads((Path(base["path"]) / "config.json").read_text()),
                    "tokenizer_fingerprint": base["info"].get("tokenizer_fingerprint"),
                    "shard_id": f"evolution-{exp['id']}-shard-{i}", "shard_sha256": _sha(rd / f"shard-{i}.bin"),
                    "shard_license": "approved library data", "job_id": f"evolution-{exp['id']}-r{r}-s{i}",
                    "train": {"steps": st["local_steps"], "lr": cfg["lr"], "batch_size": cfg["batch_size"],
                              "batch_autotune": bool(cfg.get("batch_autotune", True)),
                              "seq_len": cfg["seq_len"], "weight_decay": cfg["weight_decay"]},
                    "protocol": PROTOCOL, "requirements": {"memory_bytes": int(need_bytes)}, "prefer_gpu": True}
            jid = c.execute(training_jobs.insert().values(**next_job_values(ctx,c), kind="dist_shard", status="queued", spec=json.dumps(spec),
                                                          attempts=0, max_attempts=3, created_at=now(),
                                                          updated_at=now())).inserted_primary_key[0]
            jobs[str(i)] = jid


def steps_for(conn, spec: dict, hw: dict) -> int:
    """Local steps for a participant: proportional to its measured speed relative to the online median
    (within 0.25×–4× of the round's base), so slow CPUs do not hold up a round."""
    base = int(spec["train"]["steps"])
    mine = float((hw.get("benchmark") or {}).get("gflops") or 0)
    if mine <= 0:
        return base
    t = now()
    speeds = []
    for w in conn.execute(select(workers.c.hardware).where(workers.c.revoked_at.is_(None),
                                                           workers.c.last_heartbeat_at >= t - ONLINE_SECONDS)):
        g = (json.loads(w[0] or "{}").get("benchmark") or {}).get("gflops")
        if g:
            speeds.append(float(g))
    if not speeds:
        return base
    speeds.sort()
    median = speeds[len(speeds) // 2]
    return max(1, min(base * 4, int(round(base * max(0.25, min(4.0, mine / median))))))


def job_files(ctx: Ctx, spec: dict) -> tuple[Path, Path]:
    from moth_server.evolution.backends import run_dir

    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    rd = run_dir(ctx, exp)
    return _round_weights(rd, int(spec["dist"]["round"])), rd / f"shard-{int(spec['dist']['shard'])}.bin"


def accept_shard(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    """Validate one participant's update for the current round and store it (exactly once)."""
    import torch

    from moth.community.validation import deserialize_state, tensor_bytes_sha256, validate_delta

    from moth_server.evolution.backends import EVOLUTION_MAX_RELATIVE_NORM, run_dir

    spec = json.loads(job_row["spec"])
    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    st = (exp["resources"] or {}).get("distributed") or {}
    r, i = int(spec["dist"]["round"]), int(spec["dist"]["shard"])
    reasons = []
    if exp["status"] != "running" or r != st.get("round"):
        reasons.append(f"round {r} is over (the experiment is at round {st.get('round')})")
    if meta.get("base_sha256") != spec["base_sha256"] or spec["base_sha256"] != st.get("weights_sha256"):
        reasons.append("the update is based on different weights than this round")
    if tensor_bytes_sha256(payload) != meta.get("delta_sha256"):
        reasons.append("checksum mismatch")
    rd = run_dir(ctx, exp)
    dest = rd / f"delta-r{r:03d}-s{i}.pt"
    if dest.exists():
        reasons.append("this shard of the round was already submitted")
    if reasons:
        return {"accepted": False, "reasons": reasons}
    try:
        delta = deserialize_state(payload)
    except Exception as e:  # noqa: BLE001
        return {"accepted": False, "reasons": [f"unreadable update: {e}"]}
    base = torch.load(_round_weights(rd, r), map_location="cpu", weights_only=True)
    report = validate_delta(base, delta, max_relative_norm=EVOLUTION_MAX_RELATIVE_NORM)
    if not report.ok:
        return {"accepted": False, "reasons": report.reasons}
    tmp = dest.with_suffix(".tmp")
    torch.save({"delta": delta, "tokens": int(meta.get("tokens") or 0), "worker_id": job_row["worker_id"],
                "steps": meta.get('steps'), "train_loss": meta.get('train_loss'),
                "batch_tuning": meta.get("batch_tuning"),
                "loss_before": meta.get("loss_before"), "loss_after": meta.get("loss_after")}, tmp)
    tmp.replace(dest)
    return {"accepted": True, **report.stats}


def _probe_loss(state: dict, model_config: dict, probe: Path) -> float:
    import numpy as np
    import torch

    from moth.community.client import batch_loss
    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    m = MothModel(MothConfig.from_dict(model_config))
    m.load_state_dict(state)
    toks = np.fromfile(probe, dtype=np.uint32)
    with torch.no_grad():
        return float(batch_loss(m, toks, "cpu"))


def advance(ctx: Ctx, exp: dict, settings: dict) -> dict[str, Any]:
    """Progress a distributed experiment: aggregate finished rounds, requeue failed shards, finish."""
    import torch

    from moth_server import models as M
    from moth_server.evolution.backends import run_dir

    st = dict((exp["resources"] or {}).get("distributed") or {})
    rd = run_dir(ctx, exp)
    r = st["round"]
    ids = {int(k): v for k, v in (st["jobs"].get(str(r)) or {}).items()}
    rows = {j["id"]: j for j in ctx.db.all(select(training_jobs).where(training_jobs.c.id.in_(list(ids.values()))))}
    done = [i for i, jid in ids.items() if (rd / f"delta-r{r:03d}-s{i}.pt").exists()]
    failed = [i for i, jid in ids.items() if rows.get(jid, {}).get("status") in ("failed", "cancelled")
              and i not in done]
    pending = [i for i in ids if i not in done and i not in failed]
    progress = {"round": r, "rounds": st["rounds"], "done": len(done), "shards": st["shards"]}
    if pending:
        return {"state": "running", **progress}
    if failed and len(done) < int((settings.get("distributed") or {}).get("min_participants", 2)):
        base = M.release(ctx, exp["base_version"])
        _create_round_jobs(ctx, exp, base, st, int((exp["resources"] or {}).get("need_bytes") or 0), only=failed)
        _save(ctx, exp, st)
        MEM.event(ctx, "distributed.requeued", f"Experiment #{exp['id']}: round {r}: {len(failed)} shard(s) failed; "
                  "queued again", level="warning", cycle_id=exp["cycle_id"], experiment_id=exp["id"])
        return {"state": "running", **progress}
    # aggregate: token-weighted average of the verified deltas
    base_w = torch.load(_round_weights(rd, r), map_location="cpu", weights_only=True)
    items = [torch.load(rd / f"delta-r{r:03d}-s{i}.pt", map_location="cpu", weights_only=False) for i in sorted(done)]
    total = sum(max(1, it["tokens"]) for it in items)
    avg = {k: sum(it["delta"][k].float() * (max(1, it["tokens"]) / total) for it in items) for k in base_w}
    new_w = {k: (v.float() + avg[k]).to(v.dtype) if v.is_floating_point() else v for k, v in base_w.items()}
    base = M.release(ctx, exp["base_version"])
    model_cfg = json.loads((Path(base["path"]) / "config.json").read_text())
    before = _probe_loss(base_w, model_cfg, rd / "probe.bin")
    after = _probe_loss(new_w, model_cfg, rd / "probe.bin")
    accepted = math.isfinite(after) and after <= before * (1 + PROBE_TOLERANCE)
    torch.save(new_w if accepted else base_w, _round_weights(rd, r + 1))
    contributors = {}
    for it in items:
        w = str(it.get("worker_id"))
        contributors[w] = contributors.get(w, 0) + int(it["tokens"])
    st["history"].append({"round": r, "participants": len(items), "tokens": total, "probe_before": round(before, 5),
                          "steps": sum(it['steps'] for it in items) if all(it.get('steps') is not None for it in items) else None,
                          "train_loss": sum(it['train_loss'] * it['tokens'] for it in items) / total
                          if all(it.get('train_loss') is not None for it in items) else None,
                          "probe_after": round(after, 5), "accepted": accepted, "contributors": contributors,
                          "batch_tuning": {str(it["worker_id"]): it.get("batch_tuning") for it in items},
                          "at": now()})
    MEM.event(ctx, "distributed.round", f"Experiment #{exp['id']}: round {r + 1}/{st['rounds']} from {len(items)} "
              f"participant(s): probe loss {before:.3f} → {after:.3f} "
              + ("(applied)" if accepted else "(discarded: worse than before)"),
              level="info" if accepted else "warning", cycle_id=exp["cycle_id"], experiment_id=exp["id"])
    st["round"] = r + 1
    st["weights_sha256"] = _sha(_round_weights(rd, r + 1))
    if st["round"] < st["rounds"]:
        _create_round_jobs(ctx, exp, base, st, int((exp["resources"] or {}).get("need_bytes") or 0))
        _save(ctx, exp, st)
        return {"state": "running", **progress, "round": st["round"]}
    _save(ctx, exp, st)
    return {"state": "finished", "result": _package(ctx, exp, base, st, rd)}


def _save(ctx: Ctx, exp: dict, st: dict) -> None:
    MEM.update_experiment(ctx, exp["id"], resources={**(exp["resources"] or {}), "distributed": st},
                          progress=min(1.0, st["round"] / max(1, st["rounds"])))
    exp["resources"] = {**(exp["resources"] or {}), "distributed": st}


def _package(ctx: Ctx, exp: dict, base: dict, st: dict, rd: Path) -> dict[str, Any]:
    import torch

    from moth.model.registry import sha256_file

    final = torch.load(_round_weights(rd, st["round"]), map_location="cpu", weights_only=True)
    bdir = Path(base["path"])
    ref = torch.load(bdir / "model.pt", map_location="cpu", weights_only=True)
    dtype = ref[next(iter(ref))].dtype
    pkg = rd / "export" / f"moth-evolution-e{exp['id']}"
    shutil.rmtree(pkg, ignore_errors=True)
    pkg.mkdir(parents=True)
    torch.save({k: v.to(dtype) if v.is_floating_point() else v for k, v in final.items()}, pkg / "model.pt")
    for f in ("config.json", "tokenizer.json"):
        shutil.copy2(bdir / f, pkg / f)
    manifest = json.loads((bdir / "manifest.json").read_text())
    for key in ("model_version", "display_name", "initialization"):
        manifest.pop(key, None)
    tokens = sum(h["tokens"] for h in st["history"])
    steps = sum(h['steps'] for h in st['history']) if all(h.get('steps') is not None for h in st['history']) else None
    manifest.update(name=f"moth-evolution-e{exp['id']}", created=now(), sha256=sha256_file(pkg / "model.pt"),
                    training={"method": "continued", "backend": "distributed", "rounds": st["rounds"],
                              "steps": steps, "train_loss": st['history'][-1].get('train_loss') if st['history'] else None,
                              "participants": max((h["participants"] for h in st["history"]), default=0),
                              "tokens": tokens, "history": st["history"]},
                    lineage={"base_sha256": base["sha256"], "base_name": base["name"], "method": "continued"})
    (pkg / "manifest.json").write_text(json.dumps(manifest, indent=2))
    result = {"ok": True, "reason": "completed", "package": str(pkg), "sha256": manifest["sha256"],
              "backend": "distributed", "tokens": tokens, "step": steps,
              "max_steps": st["rounds"] * st["local_steps"], "rounds": st["history"],
              "seconds": round(time.time() - float((exp["resources"] or {}).get("started") or time.time()), 1)}
    (rd / "result.json").write_text(json.dumps(result))
    return result
