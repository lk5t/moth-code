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
            "gpu_memory_fraction": float(lim["gpu_memory_fraction"]) if device == "cuda" else None,
            "from_scratch": cfg.get("method") == "from_scratch"}
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


def progress(ctx: Ctx, exp: dict) -> dict[str, Any]:
    """Measured progress from the trainer's own events (no estimates without data)."""
    p = run_dir(ctx, exp) / "events.jsonl"
    out: dict[str, Any] = {"step": 0, "max_steps": exp["config"].get("steps")}
    if not p.exists():
        return out
    starts: list[tuple[float, int]] = []
    last_train = last_val = None
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("kind") == "metrics" and e.get("split") == "train":
                last_train = e
                starts.append((e.get("_ts") or 0, e["step"]))
            elif e.get("kind") == "metrics" and e.get("split") == "val":
                last_val = e
            elif e.get("kind") == "error":
                out["error"] = e.get("message")
    if last_train:
        out.update(step=last_train["step"], train_loss=last_train.get("loss"),
                   tokens_per_sec=last_train.get("tokens_per_sec"))
    if last_val:
        out["val_loss"] = last_val.get("loss")
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
def register_candidate(ctx: Ctx, exp: dict, package: Path) -> dict:
    from moth_server import models as M

    cfg = exp["config"]
    ds = DS.get(ctx, exp["dataset_id"])
    source = {"type": "evolution", "cycle_id": exp["cycle_id"], "experiment_id": exp["id"],
              "base_version": exp["base_version"], "dataset_id": exp["dataset_id"]}
    name = f"moth-evolution-v{exp['base_version']}-e{exp['id']}"
    version = M.reserve(ctx, name, source, None)
    rel = M.finalize(ctx, version, package, None)
    MEM.record_lineage(ctx, version, exp["base_version"], cfg.get("method", "continued"), exp["cycle_id"], exp["id"],
                       [ds["sha256"]])
    return rel


# ---- worker backend -----------------------------------------------------------------------------------
def create_worker_job(ctx: Ctx, exp: dict) -> int:
    from moth.community.protocol import PROTOCOL
    from moth.model.registry import sha256_file

    from moth_server import models as M

    cfg = exp["config"]
    base = M.release(ctx, exp["base_version"])
    ds = DS.get(ctx, exp["dataset_id"])
    rd = run_dir(ctx, exp)
    shard_sha = DS.write_shard(ds, rd / "shard.bin")
    weights = Path(base["path"]) / "model.pt"
    spec = {"evolution_experiment": exp["id"], "round": -exp["id"], "model_version": base["version"],
            "base_sha256": sha256_file(weights),
            "model_config": json.loads((Path(base["path"]) / "config.json").read_text()),  # exact architecture
            "tokenizer_fingerprint": base["info"].get("tokenizer_fingerprint"),
            "shard_id": f"evolution-{exp['id']}", "shard_sha256": shard_sha, "shard_license": ds["license"],
            "job_id": f"evolution-{exp['id']}",
            "train": {"steps": cfg["steps"], "lr": cfg["lr"], "batch_size": cfg["batch_size"],
                      "seq_len": cfg["seq_len"], "weight_decay": cfg["weight_decay"]},
            "protocol": PROTOCOL}
    with ctx.db.tx() as c:
        res = c.execute(training_jobs.insert().values(kind="evolve_train", status="queued", spec=json.dumps(spec),
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
    return Path(base["path"]) / "model.pt", run_dir(ctx, exp) / "shard.bin"


def accept_worker_result(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    """Validate a worker's weight update for an evolution job and turn it into a candidate package."""
    import torch

    from moth.community.aggregation import apply_delta
    from moth.community.validation import deserialize_state, tensor_bytes_sha256, validate_delta
    from moth.model.registry import sha256_file

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
    state = torch.load(bdir / "model.pt", map_location="cpu", weights_only=True)
    base_f = {k: v.float() for k, v in state.items()}
    # Shapes, finiteness and a sanity bound on the update size (a whole experiment changes weights far more
    # than one network round; quality is decided by the evaluation gates, not by this check).
    report = validate_delta(base_f, delta, max_relative_norm=EVOLUTION_MAX_RELATIVE_NORM)
    if not report.ok:
        return {"accepted": False, "reasons": report.reasons}
    new = apply_delta(base_f, delta)
    rd = run_dir(ctx, exp)
    pkg = rd / "export" / f"moth-evolution-e{exp['id']}"
    shutil.rmtree(pkg, ignore_errors=True)
    pkg.mkdir(parents=True)
    dtype = state[next(iter(state))].dtype
    torch.save({k: v.to(dtype) if v.is_floating_point() else v for k, v in new.items()}, pkg / "model.pt")
    for f in ("config.json", "tokenizer.json"):
        shutil.copy2(bdir / f, pkg / f)
    manifest = json.loads((bdir / "manifest.json").read_text())
    manifest.update(name=f"moth-evolution-e{exp['id']}", created=now(), sha256=sha256_file(pkg / "model.pt"),
                    training={"method": "continued", "backend": "worker", "steps": meta.get("steps"),
                              "tokens": meta.get("tokens"), "loss_before": meta.get("loss_before"),
                              "loss_after": meta.get("loss_after")},
                    lineage={"base_sha256": base["sha256"], "base_name": base["name"], "method": "continued"})
    (pkg / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (rd / "result.json").write_text(json.dumps({"ok": True, "reason": "completed", "package": str(pkg),
                                                "sha256": manifest["sha256"], "backend": "worker",
                                                "loss_before": meta.get("loss_before"),
                                                "loss_after": meta.get("loss_after"), "tokens": meta.get("tokens")}))
    return {"accepted": True, **report.stats}
