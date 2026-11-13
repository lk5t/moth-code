"""Training backends for evolution experiments.

* **local** — ``python -m moth.training.continue_run`` as a separate, lower-priority process with a
  thread limit (and GPU memory fraction / duty cycle when configured). Pausing writes ``STOP``: the
  trainer checkpoints and exits; resuming starts the same spec again, which continues from that
  checkpoint. A server restart re-attaches to a still-running process or resumes from the checkpoint.
* **worker** — a ``evolve_train`` job for a MOTH worker (GPU), using the existing lease, heartbeat,
  checkpoint/resume and verification protocol, so already-installed workers run it unchanged. The
  returned weight update is validated (shapes, finiteness, size) before it becomes a candidate.

Either way the result is a **new model release** (``source.type = "evolution"``) with recorded lineage;
the active model is never modified.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from moth_server.evolution.native_reset import next_job_values
from moth_server.context import Ctx
from moth_server.db import now, training_jobs
from moth_server.evolution import datasets as DS
from moth_server.evolution import memory as MEM

EVOLUTION_MAX_RELATIVE_NORM = 10.0


def runs_root(ctx: Ctx) -> Path:
    p = ctx.settings.data_dir / "evolution" / "runs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run_dir(ctx: Ctx, exp: dict) -> Path:
    return runs_root(ctx) / f"exp-{exp['id']:05d}"


# ---- local process ----------------------------------------------------------------------------------
def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie (exited, not yet reaped) is not alive
        state = Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0]
        return state != "Z"
    except OSError:
        return True


def _ours(pid: int, spec_path: Path) -> bool:
    try:
        return str(spec_path) in Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode()
    except OSError:
        return True  # no /proc: trust the recorded pid


def start_local(ctx: Ctx, exp: dict, device: str, settings: dict) -> dict:
    import moth

    from moth_server import models as M

    cfg = exp["config"]
    base = M.release(ctx, exp["base_version"])
    ds = DS.get(ctx, exp["dataset_id"])
    rd = run_dir(ctx, exp)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "result.json").unlink(missing_ok=True)
    (rd / "STOP").unlink(missing_ok=True)
    lim = settings["limits"]
    spec = {"name": f"moth-evolution-e{exp['id']}", "base_package": base["path"], "dataset": ds["path"],
            "run_dir": str(rd), "steps": cfg["steps"], "lr": cfg["lr"], "batch_size": cfg["batch_size"],
            "seq_len": cfg["seq_len"], "weight_decay": cfg["weight_decay"], "seed": cfg["seed"],
            "eval_interval": cfg["eval_interval"], "checkpoint_interval": cfg["checkpoint_interval"],
            "device": device, "threads": int(lim["cpu_threads"]), "nice": 10, "duty_cycle": float(lim["duty_cycle"]),
            "gpu_memory_fraction": float(lim["gpu_memory_fraction"]) if device.startswith("cuda") else None,
            "from_scratch": cfg.get("method") == "from_scratch"}
    spec.update(_v2_spec(base, cfg, exp, rd))
    spec["batch_autotune"] = bool(cfg.get("batch_autotune", True))
    spec_path = rd / "spec.json"
    spec_path.write_text(json.dumps(spec, indent=2))
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(Path(moth.__file__).resolve().parents[1])]
                                        + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    env["OMP_NUM_THREADS"] = str(int(lim["cpu_threads"]))
    log = open(rd / "train.log", "ab")
    proc = subprocess.Popen([sys.executable, "-m", "moth.training.continue_run", "--spec", str(spec_path)],
                            stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                            start_new_session=True, cwd=str(rd))
    log.close()
    ctx.extras.setdefault("evolution_procs", {})[exp["id"]] = proc
    return {"pid": proc.pid, "device": device, "spec": str(spec_path), "started": now()}


def _v2_spec(base: dict, cfg: dict, exp: dict, rd: Path | None = None) -> dict:
    """Evolution 2.0 additions: curriculum mixture, development checkpoint, growth, lineage counters."""
    out: dict = {}
    if cfg.get("mixture"):
        out["dataset"] = cfg["mixture"]["path"]
        out["mixture"] = cfg["mixture"]["weights"]
    dev = base["info"].get("dev_checkpoint") or {}
    if dev.get("path"):
        out["init_checkpoint"], out["init_checkpoint_sha256"] = dev["path"], dev.get("sha256")
    if cfg.get("resume") and not cfg.get("grow") and rd is not None:  # 0.9.0: continue from a worker's progress
        out["init_checkpoint"] = str(rd / "resume-base.pt")
        out["init_checkpoint_sha256"] = cfg["resume"]["sha256"]
    if cfg.get("grow"):
        out["grow"] = {"add_layers": cfg["grow"]["add_layers"], "ffn_hidden": cfg["grow"]["ffn_hidden"]}
    tr = base["info"].get("training") or {}
    out["lineage"] = {"lineage_id": base["info"].get("lineage_id"), "parent_version": base["version"],
                      "base_tokens": (base["info"].get("lineage_totals") or {}).get("tokens", tr.get('tokens')),
                      "base_steps": (base["info"].get("lineage_totals") or {}).get("steps", tr.get("step"))}
    return out


def local_state(ctx: Ctx, exp: dict) -> str:
    """running | finished | gone (process ended without a result: interrupted)."""
    rd = run_dir(ctx, exp)
    res = exp.get("resources") or {}
    proc = (ctx.extras.get("evolution_procs") or {}).get(exp["id"])
    if proc is not None and proc.poll() is None:
        return "running"
    if proc is None and _alive(res.get("pid")) and _ours(res["pid"], Path(res.get("spec", rd / "spec.json"))):
        return "running"  # re-attached after a server restart
    return "finished" if (rd / "result.json").exists() else "gone"


def pause_local(ctx: Ctx, exp: dict, wait_s: float = 120.0) -> bool:
    """Ask the trainer to checkpoint and exit. Returns True once it has stopped."""
    rd = run_dir(ctx, exp)
    (rd / "STOP").write_text("pause")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if local_state(ctx, exp) != "running":
            return True
        time.sleep(0.5)
    return False


def kill_local(ctx: Ctx, exp: dict) -> None:
    pid = (exp.get("resources") or {}).get("pid")
    proc = (ctx.extras.get("evolution_procs") or {}).pop(exp["id"], None)
    try:
        if proc is not None and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
        elif _alive(pid):
            os.killpg(pid, signal.SIGTERM)
    except OSError:
        pass


def worker_report(ctx: Ctx, exp: dict) -> dict[str, Any]:
    """0.9.0: what the worker last reported for a running worker experiment (step, tokens, training loss,
    checkpoint step and what it is doing), with the planned steps; empty when nothing was reported yet."""
    j = job(ctx, exp["job_id"]) if exp.get("job_id") else None
    if not j or j["status"] != "leased":
        return {}
    try:
        rep = (json.loads(j.get("result") or "{}").get("progress")) or {}
    except (TypeError, ValueError):
        return {}
    out = {k: v for k, v in rep.items() if v is not None}
    if out:
        out["max_steps"] = (exp.get("config") or {}).get("steps")
        if out.get("tokens") is not None:
            out["tokens_seen"] = out["tokens"]
    return out


def progress(ctx: Ctx, exp: dict) -> dict[str, Any]:
    """Measured progress from the trainer's own events (no estimates without data)."""
    p = run_dir(ctx, exp) / "events.jsonl"
    out: dict[str, Any] = {"step": 0, "max_steps": exp["config"].get("steps")}
    if not p.exists():
        return out
    starts: list[tuple[float, int]] = []
    last_train = last_val = None
    history = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("kind") == "metrics" and e.get("loss") is not None:
                history.append({"step": e.get("step"), "loss": e['loss'], "split": e.get('split')})
            if e.get("kind") == "metrics" and e.get("split") == "train":
                last_train = e
                starts.append((e.get("_ts") or 0, e["step"]))
            elif e.get("kind") == "metrics" and e.get("split") == "val":
                last_val = e
            elif e.get("kind") == "checkpoint" and e.get("path"):
                out["checkpoint"] = {"name": Path(e["path"]).name, "step": e.get("step")}
            elif e.get("kind") == "error":
                out["error"] = e.get("message")
    if last_train:
        out.update(step=last_train["step"], train_loss=last_train.get("loss"),
                   tokens_per_sec=last_train.get("tokens_per_sec"))
        if last_train.get("tokens_seen") is not None:
            out["tokens_seen"] = last_train["tokens_seen"]
    if last_val:
        out["val_loss"] = last_val.get("loss")
        if last_val.get("tokens_seen") is not None and "tokens_seen" not in out:
            out["tokens_seen"] = last_val["tokens_seen"]
    out["history"] = history[-120:]
    steps = out.get("max_steps") or 0
    if steps:
        out["fraction"] = min(1.0, out["step"] / steps)
    tps = out.get("tokens_per_sec")
    if tps and steps and out["step"] < steps:
        per_step = exp["config"]["batch_size"] * exp["config"]["seq_len"]
        out["eta_seconds"] = round((steps - out["step"]) * per_step / tps)
    return out


def log_tail(ctx: Ctx, exp: dict, lines: int = 200) -> list[str]:
    """The experiment's training log (metrics and messages only — training text never appears in it)."""
    out: list[str] = []
    rd = run_dir(ctx, exp)
    for name in ("events.jsonl", "train.log"):
        p = rd / name
        if p.exists():
            out += [f"[{name}] {l}" for l in p.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]]
    return out[-lines:]


def cleanup_run(ctx: Ctx, exp: dict) -> None:
    """Free disk after an experiment finished: drop checkpoints and exports, keep logs and result."""
    rd = run_dir(ctx, exp)
    for sub in ("checkpoints", "export"):
        shutil.rmtree(rd / sub, ignore_errors=True)
    for f in ("shard.bin",):
        (rd / f).unlink(missing_ok=True)


# ---- candidate registration ---------------------------------------------------------------------------
def register_candidate(ctx: Ctx, exp: dict, package: Path, result: dict | None = None) -> dict:
    from moth_server import models as M

    cfg = exp["config"]
    ds = DS.get(ctx, exp["dataset_id"])
    source = {"type": "evolution", "cycle_id": exp["cycle_id"], "experiment_id": exp["id"],
              "base_version": exp["base_version"], "dataset_id": exp["dataset_id"]}
    name = f"moth-evolution-v{exp['base_version']}-e{exp['id']}"
    version = M.reserve(ctx, name, source, None)
    rel = M.finalize(ctx, version, package, None)
    datasets = (cfg["mixture"].get("build_shas") or [cfg["mixture"]["build_sha256"]]) if cfg.get("mixture") else [ds["sha256"]]
    MEM.record_lineage(ctx, version, exp["base_version"], cfg.get("method", "continued"), exp["cycle_id"], exp["id"],
                       datasets)
    # Evolution 2.0: keep the full training checkpoint (weights + optimizer) so a promoted candidate's
    # successors continue exactly where it stopped; carry the lineage identity and its cumulative totals
    base = M.release(ctx, exp["base_version"])
    info = dict(rel["info"])
    for k in ("family", "lineage_id"):
        if base["info"].get(k) and not info.get(k):
            info[k] = base["info"][k]
    prev = base["info"].get("lineage_totals") or {}
    tr = base['info'].get('training') or {}
    tokens = (result or {}).get('tokens')
    steps = (result or {}).get('step')
    base_steps = prev.get('steps', tr.get('step', tr.get('steps')))
    base_tokens = prev.get('tokens', tr.get('tokens', 0 if base_steps == 0 else None))
    info["lineage_totals"] = {"tokens": int(base_tokens) + int(tokens) if base_tokens is not None and tokens is not None else None,
                              "steps": int(base_steps) + int(steps) if base_steps is not None and steps is not None else None,
                              "cycles": int(prev.get("cycles", 0)) + 1}
    if cfg.get("grow"):
        info["growth"] = cfg["grow"]
    if (result or {}).get("dev_checkpoint"):
        from moth_server.evolution.v2 import store_dev_checkpoint

        dev = store_dev_checkpoint(ctx, version, result["dev_checkpoint"], result["dev_checkpoint_sha256"])
        if dev:
            info["dev_checkpoint"] = dev
    M._set(ctx, version, None, info=json.dumps(info))
    return M.release(ctx, version)


# ---- worker backend -----------------------------------------------------------------------------------
MASK_WORKER_VERSION = "0.6.4"  # MOTH Workers from this version apply the loss mask of a job (0.6.3 did not)


def worker_training_supported(ctx: Ctx, exp: dict, masks: bool = False) -> bool:
    """Whether a worker may train this experiment. Private (user-contributed) data never leaves
    MOTH Cloud. ``masks``: the job carries the loss mask (whole-experiment worker jobs, 0.6.3);
    without it, assistant-masked data needs local training (token-only, e.g. sharded rounds)."""
    import numpy as np

    dataset = DS.get(ctx, exp.get('dataset_id')) if exp.get('dataset_id') else None
    if dataset and dataset.get('contains_user_data'):
        return False  # training consent is not permission to redistribute private source data
    private_shas = {d['sha256'] for d in DS.all_(ctx) if d.get('contains_user_data')}
    mix = exp["config"].get("mixture")
    if mix:
        root = Path(mix["path"])
        info = json.loads((root / "mixture.json").read_text())
        paths = [root / v["dir"] for d, v in info["domains"].items() if mix["weights"].get(d, 0) > 0]
    else:
        paths = [Path(DS.get(ctx, exp["dataset_id"])["path"])]
    for path in paths:
        from moth.model.registry import sha256_file
        if private_shas and sha256_file(path / "train.bin") in private_shas:
            return False
        if masks:
            continue
        mask = np.memmap(path / "train.mask", dtype=np.uint8, mode="r")
        if any(np.any(mask[i:i + 1048576] == 0) for i in range(0, len(mask), 1048576)):
            return False
    return True


def create_worker_job(ctx: Ctx, exp: dict, need_bytes: int = 0, worker_ids: list[int] | None = None) -> int:
    from moth.community.protocol import PROTOCOL
    from moth.model.registry import sha256_file

    from moth_server import models as M

    cfg = exp["config"]
    if not worker_training_supported(ctx, exp, masks=True):
        raise ValueError("private training data never leaves MOTH Cloud")
    base = M.release(ctx, exp["base_version"])
    ds = DS.get(ctx, exp["dataset_id"])
    rd = run_dir(ctx, exp)
    rd.mkdir(parents=True, exist_ok=True)
    weights = Path(base["path"]) / "model.pt"
    model_config = json.loads((Path(base["path"]) / "config.json").read_text())
    if cfg.get("grow"):
        import torch
        from moth.model.config import MothConfig
        from moth.model.growth import grow_checkpoint, assert_function_preserved
        from moth.training.checkpoint import atomic_torch_save

        dev = base["info"].get("dev_checkpoint") or {}
        src = Path(dev["path"]) if dev.get("path") else weights
        expected = dev.get("sha256") if dev.get("path") else base["sha256"]
        if not src.is_file() or not expected or sha256_file(src) != expected:
            raise ValueError("worker growth requires a verified base checkpoint")
        raw = torch.load(src, map_location="cpu", weights_only=False)
        ck = raw if "model" in raw else {"model": raw, "model_config": model_config}
        grown = grow_checkpoint(ck, cfg["grow"]["add_layers"], cfg["grow"]["ffn_hidden"], cfg["seed"])
        before, after = MothConfig.from_dict(ck["model_config"]), MothConfig.from_dict(grown["model_config"])
        assert_function_preserved(ck["model"], before, grown["model"], after,
                                  torch.zeros((1, min(16, before.max_seq_len)), dtype=torch.long))
        weights = rd / "growth-base.pt"
        atomic_torch_save(grown["model"], weights)
        model_config = grown["model_config"]
    resume = cfg.get("resume") if not cfg.get("grow") else None
    if resume:  # 0.9.0: continue from the progress kept when the previous compute lost the job
        weights = rd / "resume-base.pt"
        if not weights.is_file() or sha256_file(weights) != resume.get("sha256"):
            raise ValueError("the kept progress of this experiment is missing or damaged")
    if cfg.get("mixture"):  # a curriculum shard: tokens sampled from every domain by weight
        from moth_server.evolution.v2 import write_mixture_shard

        need = int(cfg["steps"]) * int(cfg["batch_size"]) * int(cfg["seq_len"]) * 2
        shard_sha = write_mixture_shard(cfg["mixture"]["path"], cfg["mixture"]["weights"], need, int(cfg["seed"]),
                                        rd / "shard.bin", mask_dest=rd / "shard.mask")
    else:
        shard_sha = DS.write_shard(ds, rd / "shard.bin")
        if (rd / "shard.mask").exists():
            (rd / "shard.mask").unlink()
    mask_sha = sha256_file(rd / "shard.mask") if (rd / "shard.mask").exists() else None
    spec = {"evolution_experiment": exp["id"], "round": -exp["id"], "model_version": base["version"],
            "worker_ids": worker_ids,
            "base_sha256": sha256_file(weights),
            "model_config": model_config, "expanded": bool(cfg.get("grow")), "resume_base": bool(resume),
            "tokenizer_fingerprint": base["info"].get("tokenizer_fingerprint"),
            "shard_id": f"evolution-{exp['id']}", "shard_sha256": shard_sha, "shard_license": ds["license"],
            "job_id": f"evolution-{exp['id']}",
            "train": {"steps": cfg["steps"], "lr": cfg["lr"], "batch_size": cfg["batch_size"],
                      "batch_autotune": bool(cfg.get("batch_autotune", True)),
                      "seq_len": cfg["seq_len"], "weight_decay": cfg["weight_decay"]},
            "protocol": PROTOCOL,
            # conversation data learns only the assistant's replies: the mask travels with the tokens,
            # and only workers that apply it may claim the job
            **({"mask_sha256": mask_sha, "min_worker_version": MASK_WORKER_VERSION} if mask_sha else {}),
            # assignment: only workers with enough memory get it; a GPU worker is preferred briefly
            "requirements": {"memory_bytes": int(need_bytes)}, "prefer_gpu": True}
    with ctx.db.tx() as c:
        res = c.execute(training_jobs.insert().values(**next_job_values(ctx,c), kind="evolve_train", status="queued", spec=json.dumps(spec),
                                                      attempts=0, max_attempts=int(exp["max_attempts"]),
                                                      created_at=now(), updated_at=now()))
        return res.inserted_primary_key[0]


def job(ctx: Ctx, job_id: int) -> dict | None:
    return ctx.db.one(select(training_jobs).where(training_jobs.c.id == job_id))


def job_files(ctx: Ctx, spec: dict) -> tuple[Path, Path]:
    """(weights, shard) a worker downloads for an evolution job."""
    from moth_server import models as M

    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    base = M.release(ctx, exp["base_version"])
    if spec.get("resume_base"):  # 0.9.0: continuing a taken-back experiment from its kept progress
        return run_dir(ctx, exp) / "resume-base.pt", run_dir(ctx, exp) / "shard.bin"
    return (run_dir(ctx, exp) / "growth-base.pt" if spec.get("expanded") else Path(base["path"]) / "model.pt"), run_dir(ctx, exp) / "shard.bin"


def job_mask(ctx: Ctx, spec: dict) -> Path:
    """The loss mask of an evolution job's shard (exists only when the spec names one)."""
    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    return run_dir(ctx, exp) / "shard.mask"


def _with_resume(exp: dict, key: str, value):
    """Totals include the steps and tokens trained before a resume (0.9.0)."""
    done = ((exp.get("config") or {}).get("resume") or {}).get(key)
    return (int(value) + int(done)) if done and value is not None else value


def accept_snapshot(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    """0.9.0: keep a worker's verified progress (a weight delta after ``step`` steps) for a possible resume."""
    import torch

    from moth.community.validation import deserialize_state, tensor_bytes_sha256, validate_delta
    from moth.training.checkpoint import atomic_torch_save

    spec = json.loads(job_row["spec"])
    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    steps = int(spec["train"]["steps"])
    try:
        step, tokens = int(meta.get("step")), int(meta.get("tokens") or 0)
    except (TypeError, ValueError):
        return {"accepted": False, "reasons": ["missing step count"]}
    reasons = []
    if meta.get("base_sha256") != spec["base_sha256"]:
        reasons.append("the snapshot is based on different weights than the job's base model")
    if tensor_bytes_sha256(payload) != meta.get("delta_sha256"):
        reasons.append("checksum mismatch")
    if not 0 < step < steps:
        reasons.append("the step count is outside the job")
    if (exp.get("config") or {}).get("grow") or spec.get("expanded"):
        reasons.append("growth experiments restart from their verified grown base")
    rd = run_dir(ctx, exp)
    prev = rd / "snapshot.pt"
    if not reasons and prev.exists():
        old = torch.load(prev, map_location="cpu", weights_only=False)
        if old.get("job_id") == job_row["id"] and int(old.get("step", 0)) >= step:
            reasons.append("an equal or later snapshot is already kept")
    if reasons:
        return {"accepted": False, "reasons": reasons}
    try:
        delta = deserialize_state(payload)
    except Exception as e:  # noqa: BLE001
        return {"accepted": False, "reasons": [f"unreadable snapshot: {e}"]}
    state = torch.load(job_files(ctx, spec)[0], map_location="cpu", weights_only=True)
    report = validate_delta({k: v.float() for k, v in state.items()}, delta, max_relative_norm=EVOLUTION_MAX_RELATIVE_NORM)
    if not report.ok:
        return {"accepted": False, "reasons": report.reasons}
    atomic_torch_save({"delta": delta, "step": step, "tokens": tokens, "job_id": job_row["id"],
                       "base_sha256": spec["base_sha256"], "worker_id": job_row["worker_id"], "at": now()}, prev)
    MEM.update_experiment(ctx, exp["id"], resources={**(exp.get("resources") or {}),
                                                     "snapshot": {"step": step, "tokens": tokens, "at": now()}})
    return {"accepted": True, "step": step}


def resume_from_snapshot(ctx: Ctx, exp: dict, spec: dict) -> dict | None:
    """Turn the kept snapshot into the experiment's new starting weights; the remaining steps continue
    from there on whichever compute takes it next. None when there is nothing (valid) to resume from."""
    import torch

    from moth.community.aggregation import apply_delta
    from moth.model.registry import sha256_file
    from moth.training.checkpoint import atomic_torch_save

    rd = run_dir(ctx, exp)
    snap = rd / "snapshot.pt"
    cfg = exp.get("config") or {}
    if not snap.exists() or cfg.get("grow"):
        return None
    try:
        s = torch.load(snap, map_location="cpu", weights_only=False)
        if s.get("base_sha256") != spec.get("base_sha256"):
            return None
        state = torch.load(job_files(ctx, spec)[0], map_location="cpu", weights_only=True)
        new = apply_delta({k: v.float() for k, v in state.items()}, s["delta"])
        dtype = state[next(iter(state))].dtype
        dest = rd / "resume-base.pt"
        atomic_torch_save({k: v.to(dtype) if v.is_floating_point() else v for k, v in new.items()}, dest)
    except Exception:  # noqa: BLE001 — a damaged snapshot only means starting over
        return None
    prev = cfg.get("resume") or {}
    done_steps = int(prev.get("step", 0)) + int(s["step"])
    resume = {"step": done_steps, "tokens": int(prev.get("tokens", 0)) + int(s.get("tokens") or 0),
              "sha256": sha256_file(dest), "planned_steps": int(prev.get("planned_steps") or cfg["steps"])}
    remaining = max(1, int(cfg["steps"]) - int(s["step"]))
    MEM.update_experiment(ctx, exp["id"], config={**cfg, "steps": remaining, "resume": resume})
    snap.unlink(missing_ok=True)
    return {**resume, "remaining": remaining}


def accept_worker_result(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    """Validate a worker's weight update for an evolution job and turn it into a candidate package."""
    import torch

    from moth.community.aggregation import apply_delta
    from moth.community.validation import deserialize_state, tensor_bytes_sha256, validate_delta
    from moth.model.registry import sha256_file
    from moth.model.config import MothConfig

    from moth_server import models as M

    spec = json.loads(job_row["spec"])
    exp = MEM.experiment(ctx, int(spec["evolution_experiment"]))
    reasons = []
    if meta.get("base_sha256") != spec["base_sha256"]:
        reasons.append("the update is based on different weights than the job's base model")
    if tensor_bytes_sha256(payload) != meta.get("delta_sha256"):
        reasons.append("checksum mismatch")
    if reasons:
        return {"accepted": False, "reasons": reasons}
    try:
        delta = deserialize_state(payload)
    except Exception as e:  # noqa: BLE001
        return {"accepted": False, "reasons": [f"unreadable update: {e}"]}
    base = M.release(ctx, exp["base_version"])
    bdir = Path(base["path"])
    state = torch.load(job_files(ctx, spec)[0], map_location="cpu", weights_only=True)
    base_f = {k: v.float() for k, v in state.items()}
    # Shapes, finiteness and a sanity bound on the update size (a whole experiment changes weights far more
    # than one network round; quality is decided by the evaluation gates, not by this check).
    norm_reference = base_f
    if spec.get("expanded"):
        from moth.model.growth import ZERO_INIT

        # New residual projections start at zero. Use the model's initialization scale for their
        # norm bound, while applying accepted deltas to the real, function-preserving zero weights.
        norm_reference = {k: torch.full_like(w, 0.02) if k.endswith(ZERO_INIT) and not torch.count_nonzero(w)
                          else w for k, w in base_f.items()}
    report = validate_delta(norm_reference, delta, max_relative_norm=EVOLUTION_MAX_RELATIVE_NORM)
    if not report.ok:
        return {"accepted": False, "reasons": report.reasons}
    new = apply_delta(base_f, delta)
    rd = run_dir(ctx, exp)
    pkg = rd / "export" / f"moth-evolution-e{exp['id']}"
    shutil.rmtree(pkg, ignore_errors=True)
    pkg.mkdir(parents=True)
    dtype = state[next(iter(state))].dtype
    torch.save({k: v.to(dtype) if v.is_floating_point() else v for k, v in new.items()}, pkg / "model.pt")
    shutil.copy2(bdir / "tokenizer.json", pkg / "tokenizer.json")
    (pkg / "config.json").write_text(json.dumps(spec["model_config"]))
    manifest = json.loads((bdir / "manifest.json").read_text())
    for key in ("model_version", "display_name", "initialization"):
        manifest.pop(key, None)  # a candidate receives its own version only after acceptance
    manifest.update(name=f"moth-evolution-e{exp['id']}", created=now(), sha256=sha256_file(pkg / "model.pt"),
                    params=MothConfig.from_dict(spec["model_config"]).num_params(),
                    training={"method": exp["config"].get("method", "continued"), "backend": "worker",
                              "steps": _with_resume(exp, "step", meta.get("steps")),
                              "tokens": _with_resume(exp, "tokens", meta.get("tokens")), "loss_before": meta.get("loss_before"),
                              "train_loss": meta.get("train_loss"),
                              "loss_after": meta.get("loss_after")},
                    lineage={"base_sha256": base["sha256"], "base_name": base["name"], "method": exp["config"].get("method", "continued")})
    (pkg / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (rd / "result.json").write_text(json.dumps({"ok": True, "reason": "completed", "package": str(pkg),
                                                "sha256": manifest["sha256"], "backend": "worker",
                                                "loss_before": meta.get("loss_before"),
                                                "step": _with_resume(exp, "step", meta.get('steps')),
                                                "train_loss": meta.get('train_loss'), "loss_after": meta.get("loss_after"),
                                                "tokens": _with_resume(exp, "tokens", meta.get("tokens")),
                                                "batch_tuning": meta.get("batch_tuning")}))
    return {"accepted": True, **report.stats}
