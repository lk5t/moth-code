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
from moth_server.evolution import compute as C
from moth_server.evolution import memory as MEM

PROBE_TOLERANCE = 0.05
ONLINE_SECONDS = 180
SHARD_STALL_SECONDS = 20 * 60  # 2.3.2: a piece of a shared round with no progress this long is taken back


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
    # 1.0.9: every online computer takes part (GPUs listed first); steps_for() gives each a share of the
    # steps that matches its measured speed, so slower CPUs add work without holding a round up.
    return [w for w in out if w["hw"].get("compute") == "gpu"] + [w for w in out if w["hw"].get("compute") != "gpu"]


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


SUCCESSOR_ROUND_STEPS = 1000
OUTER_LR = 0.7        # 1.1 DiLoCo outer learning rate and Nesterov momentum (Douillard et al., 2023)
OUTER_MOMENTUM = 0.9
MIN_LOCAL_STEPS = 20
SUCCESSOR_MAX_RELATIVE_NORM = 1000.0   # 0.10.0: a successor is averaged often, so the participants stay in step
ROUND_MAX_RELATIVE_NORM = 100.0        # 2.2: was 10; small models moved their embedding further in one round


def model_config(exp: dict, base: dict) -> dict:
    """The architecture the participants train: the base's, or a successor's new shape and vocabulary."""
    cfg = json.loads((Path(base["path"]) / "config.json").read_text())
    arch = ((exp.get("config") or {}).get("rebirth") or {}).get("architecture")
    return {**cfg, **arch} if arch else cfg


def tokenizer_info(exp: dict, base: dict) -> tuple[Path, str | None]:
    tok = ((exp.get("config") or {}).get("rebirth") or {}).get("tokenizer")
    if tok:
        return Path(tok["path"]), tok["fingerprint"]
    return Path(base["path"]) / "tokenizer.json", base["info"].get("tokenizer_fingerprint")


def _successor_init(exp: dict, base: dict) -> dict:
    """Fresh, seeded initial weights of a successor (round 0 of a shared from-scratch run)."""
    import torch

    from moth.model.config import MothConfig
    from moth.model.transformer import MothModel

    torch.manual_seed(int((exp.get("config") or {}).get("seed") or 0))
    m = MothModel(MothConfig.from_dict(model_config(exp, base)))
    state = {k: v.detach().float() if v.is_floating_point() else v for k, v in m.state_dict().items()}
    if ((exp.get("config") or {}).get("rebirth") or {}).get("transfer_from_base"):
        # same tokenizer: 2.5 grow the current model exactly into the bigger shape when possible (it starts as good
        # as the current one), else 1.1 copy its weights where the shapes overlap
        from pathlib import Path

        from moth.model.growth import grow_into

        raw = torch.load(Path(base["path"]) / "model.pt", map_location="cpu", weights_only=False)
        old = raw["model"] if isinstance(raw, dict) and "model" in raw else raw
        cfg_file = Path(base["path"]) / "config.json"
        old_cfg = MothConfig.from_dict(json.loads(cfg_file.read_text()) if cfg_file.is_file()
                                       else (raw.get("model_config") or base["info"]["config"]))
        state, how = grow_into({k: v.float() if v.is_floating_point() else v for k, v in old.items()}, old_cfg,
                               MothConfig.from_dict(model_config(exp, base)), state,
                               seed=int((exp.get("config") or {}).get("seed") or 0))
        exp.setdefault("resources", {})["growth_start"] = how
    return state


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
    successor = bool(cfg.get("rebirth"))
    # 1.0.6: the participants *share* the steps (each trains about steps / n), so more computers finish
    # the run sooner instead of each repeating the whole run; they are averaged at least every
    # SUCCESSOR_ROUND_STEPS local steps so they stay in step.
    per_participant = max(MIN_LOCAL_STEPS, math.ceil(int(cfg["steps"]) / n))
    rounds = max(1, int(d.get("rounds", 3)))
    rounds = max(rounds, min(500, math.ceil(per_participant / SUCCESSOR_ROUND_STEPS)))
    local_steps = max(1, math.ceil(per_participant / rounds))
    # 1.0.2: a run handed over from MOTH Cloud alone continues from its verified checkpoint
    resume = cfg.get("resume") or {}
    handed = rd / "resume-base.pt"
    resumed = bool(resume.get("sha256") and handed.is_file() and _sha(handed) == resume["sha256"])
    dev = {} if successor or resumed else (base["info"].get("dev_checkpoint") or {})
    cont = cfg.get("continue_from") or {}
    if cont.get("path") and not successor and not resumed and Path(cont["path"]).is_file() \
            and _sha(Path(cont["path"])) == cont.get("sha256"):  # 1.1: keep training the newest candidate
        dev = {"path": cont["path"], "sha256": cont["sha256"]}
    if not successor and not resumed:
        src = Path(dev["path"]) if dev.get("path") else Path(base["path"]) / "model.pt"
        expected_sha = dev.get("sha256") if dev.get("path") else base["sha256"]
        if not src.is_file() or not expected_sha or _sha(src) != expected_sha:
            raise ValueError("distributed training requires an intact, checksum-verified base checkpoint")
    if not worker_training_supported(ctx, exp, masks=True):
        raise ValueError("private training data never leaves MOTH Cloud")
    if resumed:
        state = torch.load(handed, map_location="cpu", weights_only=True)
        torch.save({k: v.float() if v.is_floating_point() else v for k, v in state.items()}, _round_weights(rd, 0))
    elif successor and cfg.get("warm_start") and Path(cfg["warm_start"]["path"]).is_file() \
            and _sha(Path(cfg["warm_start"]["path"])) == cfg["warm_start"]["sha256"]:
        # 1.0.7: a declined successor's next attempt continues from its weights
        state = torch.load(cfg["warm_start"]["path"], map_location="cpu", weights_only=False)
        state = state["model"] if isinstance(state, dict) and "model" in state else state
        torch.save({k: v.float() if v.is_floating_point() else v for k, v in state.items()}, _round_weights(rd, 0))
    elif successor:  # trained from scratch: every participant starts from the same seeded weights
        torch.save(_successor_init(exp, base), _round_weights(rd, 0))
    else:
        raw = torch.load(src, map_location="cpu", weights_only=False)
        state = raw["model"] if isinstance(raw, dict) and "model" in raw else raw
        torch.save({k: v.float() if v.is_floating_point() else v for k, v in state.items()}, _round_weights(rd, 0))
    # probe: held-out tokens the server uses to accept or discard each round's update
    if cfg.get("mixture"):
        from moth_server.evolution.v2 import write_mixture_shard

        for i in range(n):  # 0.8.3: with the loss mask, so conversation data can be shared too
            from moth_server.evolution.v2 import blended_weights

            write_mixture_shard(cfg["mixture"]["path"], blended_weights(cfg["mixture"]["weights"], cfg.get("mixture_schedule")),
                                local_steps * int(cfg["batch_size"]) * int(cfg["seq_len"]) * rounds * 2,
                                int(cfg["seed"]) * 1000 + i, rd / f"shard-{i}.bin", mask_dest=rd / f"shard-{i}.mask")
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
                  "weights_sha256": _sha(_round_weights(rd, 0)),
                  "started_from": "checkpoint" if resumed else "declined_attempt" if successor and cfg.get("warm_start") else "successor_init" if successor else "dev_checkpoint" if dev else "weights",
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

    from moth_server.evolution.backends import MASK_WORKER_VERSION, run_dir

    cfg = exp["config"]
    rd = run_dir(ctx, exp)
    r = st["round"]
    jobs = st["jobs"].setdefault(str(r), {})
    with ctx.db.tx() as c:
        for i in (only if only is not None else range(st["shards"])):
            spec = {"evolution_experiment": exp["id"], "round": r, "dist": {"round": r, "shard": i},
                    "worker_ids": st.get("worker_ids"),
                    "model_version": base["version"], "base_sha256": st["weights_sha256"],
                    "model_config": model_config(exp, base),
                    "tokenizer_fingerprint": tokenizer_info(exp, base)[1],
                    "shard_id": f"evolution-{exp['id']}-shard-{i}", "shard_sha256": _sha(rd / f"shard-{i}.bin"),
                    "shard_license": "approved library data", "job_id": f"evolution-{exp['id']}-r{r}-s{i}",
                    **({"mask_sha256": _sha(rd / f"shard-{i}.mask"), "min_worker_version": MASK_WORKER_VERSION}
                       if (rd / f"shard-{i}.mask").exists() else {}),
                    "train": {"steps": st["local_steps"], "lr": cfg["lr"], "batch_size": cfg["batch_size"],
                              "batch_autotune": bool(cfg.get("batch_autotune", True)),
                              "seq_len": cfg["seq_len"], "weight_decay": cfg["weight_decay"],
                              # 1.0.5: early rounds use the short context, like a local run
                              **({"short_context": int(cfg["short_context"])}
                                 if cfg.get("short_context") and r < float(cfg.get("short_until") or 0) * st["rounds"] else {})},
                    "protocol": PROTOCOL, "requirements": {"memory_bytes": int(need_bytes)}, "prefer_gpu": True}
            jid = c.execute(training_jobs.insert().values(**next_job_values(ctx,c), kind="dist_shard", status="queued", spec=json.dumps(spec),
                                                          attempts=0, max_attempts=3, created_at=now(),
                                                          updated_at=now())).inserted_primary_key[0]
            jobs[str(i)] = jid


MAX_SPEED_SHARE = 25.0  # 2.3: a GPU is 30–100× a CPU; a 4× cap left it waiting for the CPUs every round
MIN_SPEED_SHARE = 0.1


def steps_for(conn, spec: dict, hw: dict, measured: dict | None = None, worker_id: int | None = None) -> int:
    """Local steps for a participant: proportional to its speed relative to the online median, so a round's
    participants finish at about the same time (the averaging is weighted by tokens trained).

    2.3: measured training throughput (tokens/s of real jobs) is used when this computer and the others have
    one; it reflects GPUs, which the CPU benchmark does not. The share may range 0.1×–25× of the base."""
    base = int(spec["train"]["steps"])
    t = now()
    online = [(r[0], json.loads(r[1] or "{}")) for r in conn.execute(
        select(workers.c.id, workers.c.hardware).where(workers.c.revoked_at.is_(None),
                                                       workers.c.last_heartbeat_at >= t - ONLINE_SECONDS))]
    measured = measured or {}
    mine_m = float(measured.get(f"worker:{worker_id}") or 0) if worker_id is not None else 0.0
    others_m = sorted(float(measured.get(f"worker:{i}") or 0) for i, _ in online)
    others_m = [v for v in others_m if v > 0]
    if mine_m > 0 and len(others_m) >= 2:
        median = others_m[len(others_m) // 2]
        share = mine_m / median
    else:
        mine = float((hw.get("benchmark") or {}).get("gflops") or 0)
        speeds = sorted(float((h.get("benchmark") or {}).get("gflops") or 0) for _, h in online)
        speeds = [g for g in speeds if g > 0]
        if mine <= 0 or not speeds:
            return base
        share = mine / speeds[len(speeds) // 2]
    share = max(MIN_SPEED_SHARE, min(MAX_SPEED_SHARE, share))
    return max(1, int(round(base * share)))


def job_files(ctx: Ctx, spec: dict) -> tuple[Path, Path]:
    from moth_server.evolution.backends import run_dir

    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    rd = run_dir(ctx, exp)
    return _round_weights(rd, int(spec["dist"]["round"])), rd / f"shard-{int(spec['dist']['shard'])}.bin"


def job_mask(ctx: Ctx, spec: dict) -> Path:
    from moth_server.evolution.backends import run_dir

    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    return run_dir(ctx, exp) / f"shard-{int(spec['dist']['shard'])}.mask"


def accept_shard(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    """Validate one participant's update for the current round and store it (exactly once)."""
    import torch

    from moth.community.validation import deserialize_state, tensor_bytes_sha256, validate_delta

    from moth_server.evolution.backends import run_dir

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
    # 1.0.15: a successor trained from scratch starts with deliberately tiny weights in some layers (e.g. the
    # residual output projections), so a fast GPU's honest update can be many times their size. Its updates
    # are held to a far looser size limit; every round is still accepted only if it lowers the loss on
    # held-out text (advance), and non-finite updates are always refused.
    # 2.2: a round of an exploration with a raised learning rate on a small model can also honestly exceed 10x
    # (embedding and output head); such rounds still have to lower held-out loss in advance() to be kept.
    cfg = exp.get("config") or {}
    limit = SUCCESSOR_MAX_RELATIVE_NORM if cfg.get("rebirth") else ROUND_MAX_RELATIVE_NORM
    report = validate_delta(base, delta, max_relative_norm=limit)
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
    skipped = set((st.get("skipped") or {}).get(str(r), []))  # 2.3.2: no computer took them in time
    failed = [i for i, jid in ids.items() if rows.get(jid, {}).get("status") in ("failed", "cancelled")
              and i not in done and i not in skipped]
    pending = [i for i in ids if i not in done and i not in failed and i not in skipped]
    progress = {"round": r, "rounds": st["rounds"], "done": len(done), "shards": st["shards"]}
    if pending:
        snap = lambda: json.dumps([st.get("watch"), st.get("leased_since")], sort_keys=True)  # noqa: E731
        before = snap()
        taken = _take_back_stuck(ctx, exp, st, r, ids, rows, pending, len(done))
        if taken or snap() != before:
            _save(ctx, exp, st)  # the progress clock must survive between checks
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
    avg = {k: sum(it["delta"][k].float() * (max(1, it["tokens"]) / total) for it in items)
           for k in base_w if base_w[k].is_floating_point()}
    base = M.release(ctx, exp["base_version"])
    model_cfg = model_config(exp, base)
    before = _probe_loss(base_w, model_cfg, rd / "probe.bin")
    # 1.1 DiLoCo: the averaged change is the outer gradient of a Nesterov-momentum step carried across rounds,
    # which learns more per round than applying the plain average. If it does not help on the held-out probe,
    # the plain average is tried, and if neither helps the round is discarded (as before).
    mom_path = rd / "outer-momentum.pt"
    mom = torch.load(mom_path, map_location="cpu", weights_only=True) if mom_path.exists() else {}
    new_mom = {k: OUTER_MOMENTUM * mom.get(k, torch.zeros_like(d)) + d for k, d in avg.items()}
    diloco = {k: (v.float() + OUTER_LR * (avg[k] + OUTER_MOMENTUM * new_mom[k])).to(v.dtype) if k in avg else v
              for k, v in base_w.items()}
    plain = {k: (v.float() + avg[k]).to(v.dtype) if k in avg else v for k, v in base_w.items()}
    method, new_w, after = "diloco", diloco, _probe_loss(diloco, model_cfg, rd / "probe.bin")
    if not (math.isfinite(after) and after <= before * (1 + PROBE_TOLERANCE)):
        method, new_w, after = "average", plain, _probe_loss(plain, model_cfg, rd / "probe.bin")
        new_mom = {k: OUTER_MOMENTUM * mom.get(k, torch.zeros_like(d)) for k, d in avg.items()}  # damp the momentum
    accepted = math.isfinite(after) and after <= before * (1 + PROBE_TOLERANCE)
    torch.save(new_w if accepted else base_w, _round_weights(rd, r + 1))
    if accepted:
        torch.save(new_mom, mom_path)
    contributors = {}
    for it in items:
        w = str(it.get("worker_id"))
        contributors[w] = contributors.get(w, 0) + int(it["tokens"])
    st["history"].append({"round": r, "participants": len(items), "tokens": total, "probe_before": round(before, 5),
                          "steps": sum(it['steps'] for it in items) if all(it.get('steps') is not None for it in items) else None,
                          "train_loss": sum(it['train_loss'] * it['tokens'] for it in items) / total
                          if all(it.get('train_loss') is not None for it in items) else None,
                          "probe_after": round(after, 5), "accepted": accepted, "contributors": contributors,
                          "method": method if accepted else None,
                          "batch_tuning": {str(it["worker_id"]): it.get("batch_tuning") for it in items},
                          "at": now()})
    MEM.event(ctx, "distributed.round", f"Experiment #{exp['id']}: round {r + 1}/{st['rounds']} from {len(items)} "
              f"participant(s): probe loss {before:.3f} → {after:.3f} "
              + (f"(applied, {'DiLoCo step' if method == 'diloco' else 'plain average'})" if accepted
                 else "(discarded: worse than before)"),
              level="info" if accepted else "warning", cycle_id=exp["cycle_id"], experiment_id=exp["id"])
    st["round"] = r + 1
    st["weights_sha256"] = _sha(_round_weights(rd, r + 1))
    if st["round"] < st["rounds"] and _stalled(st["history"], int(st["rounds"])):
        st["stopped_early"] = {"after": st["round"], "planned": st["rounds"]}
        MEM.event(ctx, "distributed.stopped_early", f"Experiment #{exp['id']}: held-out loss has not improved for "
                  f"{PLATEAU_ROUNDS} rounds; finishing after round {st['round']} of {st['rounds']} (more rounds would "
                  "only memorise the training data) and testing the result now.",
                  cycle_id=exp["cycle_id"], experiment_id=exp["id"])
        st["rounds"] = st["round"]
    if st["round"] < st["rounds"]:
        _create_round_jobs(ctx, exp, base, st, int((exp["resources"] or {}).get("need_bytes") or 0))
        _save(ctx, exp, st)
        return {"state": "running", **progress, "round": st["round"]}
    _save(ctx, exp, st)
    _learn_shared_speed(ctx, exp, st)
    return {"state": "finished", "result": _package(ctx, exp, base, st, rd)}


def _take_back_stuck(ctx: Ctx, exp: dict, st: dict, r: int, ids: dict, rows: dict, pending: list[int], n_done: int) -> bool:
    """2.3.2: a round waits for every piece, so one computer that took a piece and then stopped making progress
    (asleep, paused while its owner works, busy, or gone while still checking in) held the whole experiment at
    step 0 for good. A piece without progress for SHARD_STALL_SECONDS is cancelled and queued again for any
    computer (MOTH Cloud's own worker included); a late result for the old piece is refused."""
    t = now()
    watch = st.setdefault("watch", {})
    stuck, unclaimed = [], []
    for i in pending:
        j = rows.get(ids[i])
        if not j:
            continue
        key = str(j["id"])
        prog = round(float(j.get("progress") or 0.0), 4)
        seen = watch.get(key)
        if not seen or seen[0] != prog or seen[2] != j["status"]:
            watch[key] = [prog, t, j["status"]]  # first sight, new progress or newly taken: the clock restarts
            continue
        if j["status"] == "leased" and t - seen[1] >= SHARD_STALL_SECONDS:
            stuck.append((i, j))
        elif j["status"] == "queued" and t - seen[1] >= SHARD_STALL_SECONDS and n_done > 0:
            unclaimed.append((i, j))
    if unclaimed:
        # nobody took these for SHARD_STALL_SECONDS while the round's other pieces are done: the round goes on
        # with the finished pieces (averaged as usual and checked on the probe) instead of waiting for good
        with ctx.db.tx() as c:
            for i, j in unclaimed:
                c.execute(training_jobs.update().where(training_jobs.c.id == j["id"], training_jobs.c.status == "queued")
                          .values(status="cancelled", updated_at=t, error="no computer took it; the round went on without it"))
                watch.pop(str(j["id"]), None)
        st.setdefault("skipped", {}).setdefault(str(r), []).extend(i for i, _ in unclaimed)
        MEM.event(ctx, "distributed.skipped", f"Experiment #{exp['id']}: round {r + 1}: no computer took "
                  f"{len(unclaimed)} part(s) for {SHARD_STALL_SECONDS // 60} minutes; the round continues with the "
                  "finished parts", level="warning", cycle_id=exp["cycle_id"], experiment_id=exp["id"])
        return True
    if not stuck:
        return _hand_to_faster(ctx, exp, st, r, ids, rows, pending)
    with ctx.db.tx() as c:
        for i, j in stuck:
            c.execute(training_jobs.update().where(training_jobs.c.id == j["id"], training_jobs.c.status == "leased")
                      .values(status="cancelled", lease_expires_at=None, updated_at=t,
                              error=f"taken back: no progress for {SHARD_STALL_SECONDS // 60} minutes"))
            watch.pop(str(j["id"]), None)
    from moth_server import models as M
    _create_round_jobs(ctx, exp, M.release(ctx, exp["base_version"]), {**st, "worker_ids": None},
                       int((exp["resources"] or {}).get("need_bytes") or 0), only=[i for i, _ in stuck])
    MEM.event(ctx, "distributed.taken_back", f"Experiment #{exp['id']}: round {r + 1}: "
              + ", ".join(f"worker {j['worker_id']}" for _, j in stuck)
              + f" made no progress for {SHARD_STALL_SECONDS // 60} minutes (asleep, paused or busy); "
              "its part was taken back and goes to the next free computer", level="warning",
              cycle_id=exp["cycle_id"], experiment_id=exp["id"])
    return True


PLATEAU_ROUNDS = 6     # 2.5: stop a shared run whose held-out loss has not improved for this many rounds
PLATEAU_GAIN = 0.01    # ... by at least 1 %
SHARED_SPEED_KEY = "shared_successor_speed_factor"
STEAL_MIN_SECONDS = 120  # 2.4.2: never judge a part's pace before it has run this long
STEAL_MARGIN = 1.5  # the idle computer must be expected to finish at least this much sooner


def _hand_to_faster(ctx: Ctx, exp: dict, st: dict, r: int, ids: dict, rows: dict, pending: list[int]) -> bool:
    """2.4.2: a computer that finished its part sits idle while a slower one is still well behind (seen: a GPU
    idle while MOTH Cloud's busy CPU trained at 38%, slower than its measured speed). When an idle participant would
    train that part from the start clearly sooner than the slow one will finish it, the part moves to it."""
    t = now()
    since = st.setdefault("leased_since", {})
    measured = ctx.db.get_config("compute_throughput", {}) or {}
    with ctx.db.tx() as c:
        busy = {row[0] for row in c.execute(select(training_jobs.c.worker_id).where(training_jobs.c.status == "leased"))}
        people = [w for w in participants(ctx, int((exp["resources"] or {}).get("need_bytes") or 0), st.get("worker_ids"))
                  if w["id"] not in busy]
        for i in pending:
            j = rows.get(ids[i])
            if not j or j["status"] != "leased" or not j.get("worker_id"):
                continue
            key = str(j["id"])
            since.setdefault(key, t)
            ran, p = t - since[key], float(j.get("progress") or 0.0)
            if ran < STEAL_MIN_SECONDS or p < 0.05 or p >= 0.95:
                continue
            remaining = ran * (1 - p) / p
            spec = json.loads(j["spec"] or "{}")
            tokens_per_step = int(spec["train"].get("batch_size") or 1) * int(spec["train"].get("seq_len") or 1)
            slow = float(measured.get(f"worker:{j['worker_id']}") or 0)
            best = None
            for w in people:
                fast = float(measured.get(f"worker:{w['id']}") or 0)
                if fast <= max(slow, 1.0) * STEAL_MARGIN:
                    continue
                steps = steps_for(c, {**spec, "train": {**spec["train"], "steps": int(spec["train"].get("base_steps") or spec["train"]["steps"])}},
                                  w["hw"], measured, w["id"])
                fresh = steps * tokens_per_step / fast
                if remaining > STEAL_MARGIN * fresh + 60 and (best is None or fresh < best[1]):
                    best = (w, fresh)
            if not best:
                continue
            w, fresh = best
            c.execute(training_jobs.update().where(training_jobs.c.id == j["id"], training_jobs.c.status == "leased")
                      .values(status="cancelled", lease_expires_at=None, updated_at=t,
                              error=f"handed to faster idle worker {w['id']}"))
            since.pop(key, None)
            st.get("watch", {}).pop(key, None)
            break
        else:
            return False
    # 2.4.3: remember the slow computer's real pace (it was slower than measured, e.g. MOTH Cloud's CPU also serving
    # chat), so the next round gives it a part it can finish in time instead of handing over every round
    steps_done = p * int(spec["train"]["steps"])
    C.record_throughput(ctx, f"worker:{j['worker_id']}", steps_done * tokens_per_step, ran)
    from moth_server import models as M
    _create_round_jobs(ctx, exp, M.release(ctx, exp["base_version"]), {**st, "worker_ids": [w["id"]]},
                       int((exp["resources"] or {}).get("need_bytes") or 0), only=[i])
    MEM.event(ctx, "distributed.handed_over", f"Experiment #{exp['id']}: round {r + 1}: worker {j['worker_id']} was at "
              f"{p:.0%} and needed about {remaining / 60:.0f} more minutes; idle worker {w['id']} ({w['name']}) trains that "
              f"part from the start in about {fresh / 60:.0f} minutes", cycle_id=exp["cycle_id"], experiment_id=exp["id"])
    return True


def _save(ctx: Ctx, exp: dict, st: dict) -> None:
    MEM.update_experiment(ctx, exp["id"], resources={**(exp["resources"] or {}), "distributed": st},
                          progress=min(1.0, st["round"] / max(1, st["rounds"])))
    exp["resources"] = {**(exp["resources"] or {}), "distributed": st}


def _package(ctx: Ctx, exp: dict, base: dict, st: dict, rd: Path) -> dict[str, Any]:
    import torch

    from moth.model.registry import sha256_file

    from moth.model.config import MothConfig
    from moth.model.tokenizer import Tokenizer

    final = torch.load(_round_weights(rd, st["round"]), map_location="cpu", weights_only=True)
    bdir = Path(base["path"])
    ref = torch.load(bdir / "model.pt", map_location="cpu", weights_only=True)
    dtype = ref[next(iter(ref))].dtype
    pkg = rd / "export" / f"moth-evolution-e{exp['id']}"
    shutil.rmtree(pkg, ignore_errors=True)
    pkg.mkdir(parents=True)
    torch.save({k: v.to(dtype) if v.is_floating_point() else v for k, v in final.items()}, pkg / "model.pt")
    mc = model_config(exp, base)
    (pkg / "config.json").write_text(MothConfig.from_dict(mc).to_json())
    tok_path, tok_fp = tokenizer_info(exp, base)
    if tok_fp and Tokenizer.load(tok_path).fingerprint() != tok_fp:
        raise ValueError("the successor's tokenizer does not match its data")
    shutil.copy2(tok_path, pkg / "tokenizer.json")
    manifest = json.loads((bdir / "manifest.json").read_text())
    for key in ("model_version", "display_name", "initialization"):
        manifest.pop(key, None)
    method = "from_scratch" if exp["config"].get("rebirth") else "continued"
    manifest.update(tokenizer_fingerprint=tok_fp, context_length=mc.get("max_seq_len"),
                    params=MothConfig.from_dict(mc).num_params())
    tokens = sum(h["tokens"] for h in st["history"])
    steps = sum(h['steps'] for h in st['history']) if all(h.get('steps') is not None for h in st['history']) else None
    manifest.update(name=f"moth-evolution-e{exp['id']}", created=now(), sha256=sha256_file(pkg / "model.pt"),
                    training={"method": method, "backend": "distributed", "rounds": st["rounds"],
                              "steps": steps, "train_loss": st['history'][-1].get('train_loss') if st['history'] else None,
                              "participants": max((h["participants"] for h in st["history"]), default=0),
                              "tokens": tokens, "history": st["history"]},
                    lineage={"base_sha256": base["sha256"], "base_name": base["name"], "method": method})
    (pkg / "manifest.json").write_text(json.dumps(manifest, indent=2))
    result = {"ok": True, "reason": "completed", "package": str(pkg), "sha256": manifest["sha256"],
              "backend": "distributed", "tokens": tokens, "step": steps,
              "max_steps": st["rounds"] * st["local_steps"], "rounds": st["history"],
              "seconds": round(time.time() - float((exp["resources"] or {}).get("started") or time.time()), 1)}
    (rd / "result.json").write_text(json.dumps(result))
    return result


def _learn_shared_speed(ctx: Ctx, exp: dict, st: dict) -> None:
    """2.5: a successor planned at "about 0.8 h at the measured speed" took ~10 h when shared (merging, waiting for
    the slowest computer, small batches). The ratio of real to planned speed is remembered and applied to the next
    successor's plan, so its time and length are realistic."""
    rb = (exp.get("config") or {}).get("rebirth") or {}
    real = real_speed(st.get("history") or [])
    planned = float(rb.get("planned_tokens") or 0) / max(1.0, float(rb.get("planned_hours") or 0) * 3600)
    if not real or not planned or not rb.get("planned_hours"):
        return
    ratio = max(0.01, min(2.0, real / planned))
    old = ctx.db.get_config(SHARED_SPEED_KEY, None)
    ctx.db.set_config(SHARED_SPEED_KEY, round(ratio if old is None else 0.5 * float(old) + 0.5 * ratio, 4))


def shared_speed_factor(ctx: Ctx) -> float:
    try:
        return float(ctx.db.get_config(SHARED_SPEED_KEY, 1.0) or 1.0)
    except (TypeError, ValueError):
        return 1.0


def real_speed(hist: list[dict]) -> float | None:
    """2.5: tokens per second a shared run really achieves (rounds after the first, waiting and merging included)."""
    if len(hist) < 2 or any(h.get("at") is None for h in hist):
        return None
    span = float(hist[-1]["at"]) - float(hist[0]["at"])
    return sum(int(h.get("tokens") or 0) for h in hist[1:]) / span if span > 0 else None


def _stalled(hist: list[dict], rounds: int) -> bool:
    """2.5: the held-out probe has not improved by PLATEAU_GAIN for PLATEAU_ROUNDS rounds, past a third of the run:
    more rounds would only memorise the training data (training loss falls, held-out loss does not)."""
    if len(hist) < max(PLATEAU_ROUNDS + 2, rounds // 3):
        return False
    probes = [float(h["probe_after"]) for h in hist if h.get("accepted") and h.get("probe_after") is not None]
    earlier = [float(hist[0]["probe_before"])] + probes[:-PLATEAU_ROUNDS] if hist[0].get("probe_before") else probes[:-PLATEAU_ROUNDS]
    recent = probes[-PLATEAU_ROUNDS:]
    if not earlier:
        return False
    return not recent or min(recent) > min(earlier) * (1 - PLATEAU_GAIN)


def report(exp: dict) -> dict[str, Any]:
    """0.10.0: live progress of a shared run for the live view (rounds as steps, probe loss as validation)."""
    st = (exp.get("resources") or {}).get("distributed") or {}
    if not st:
        return {}
    per = int(st.get("local_steps") or 0)
    hist = st.get("history") or []
    points = []
    for h in hist:
        step = (int(h["round"]) + 1) * per
        points.append({"step": step, "loss": h.get("probe_after"), "split": "val"})
        if h.get("train_loss") is not None:
            points.append({"step": step, "loss": h["train_loss"], "split": "train"})
    last = hist[-1] if hist else {}
    tps = real_speed(hist)
    return {"tokens_per_sec": round(tps, 1) if tps else None, "step": int(st.get("round") or 0) * per, "max_steps": int(st.get("rounds") or 0) * per,
            "fraction": min(1.0, int(st.get("round") or 0) / max(1, int(st.get("rounds") or 1))),
            "train_loss": last.get("train_loss"), "val_loss": last.get("probe_after"),
            "tokens_seen": sum(int(h.get("tokens") or 0) for h in hist), "history": points[-120:],
            "participants": st.get("shards"), "round": st.get("round"), "rounds": st.get("rounds")}
