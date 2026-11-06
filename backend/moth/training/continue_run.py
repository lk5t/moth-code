"""Continued training of an existing MOTH model package (one evolution experiment), as a subprocess.

    python -m moth.training.continue_run --spec spec.json

* Starts from the base package's weights (``init_from``) with the base model's *exact* architecture —
  never from random weights unless the spec explicitly says ``from_scratch`` (a configured migration).
* Resumable: checkpoints go to ``<run_dir>/checkpoints``; running the same spec again continues from
  the latest checkpoint (model, optimizer, RNG and data position), e.g. after a pause or a restart.
* Pausable: creating ``<run_dir>/STOP`` makes the trainer checkpoint and exit (``result.reason`` =
  ``stopped``).
* On completion the best checkpoint (by validation loss) is exported as a model package to
  ``<run_dir>/package``. Whether it is *better* is decided by the server's evaluation, not here.

Progress and metrics are appended to ``<run_dir>/events.jsonl`` (numbers only: no training text).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any


def run(spec: dict[str, Any]) -> dict[str, Any]:
    import torch

    from moth.model.config import MothConfig
    from moth.model.registry import export_model, sha256_file
    from moth.training.checkpoint import latest_checkpoint
    from moth.training.trainer import TrainConfig, Trainer

    if spec.get("threads"):
        torch.set_num_threads(max(1, int(spec["threads"])))
    if spec.get("nice"):
        try:
            os.nice(int(spec["nice"]))
        except OSError:
            pass
    run_dir = Path(spec["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    base = Path(spec["base_package"])
    base_cfg = MothConfig.from_dict(json.loads((base / "config.json").read_text()))
    manifest = json.loads((base / "manifest.json").read_text())
    if sha256_file(base / "model.pt") != manifest["sha256"]:
        raise ValueError("the base model's weights do not match its manifest (corrupted)")
    meta = json.loads((Path(spec["dataset"]) / "meta.json").read_text())
    if meta["tokenizer_fingerprint"] != manifest["tokenizer_fingerprint"] and not spec.get("from_scratch"):
        raise ValueError("the dataset was tokenized with a different tokenizer than the base model "
                         "(an architecture/tokenizer migration is required, not continued training)")
    seq_len = min(int(spec.get("seq_len", 256)), base_cfg.max_seq_len)
    cfg = TrainConfig(
        run_name=spec.get("name", "evolution"), dataset=str(spec["dataset"]), out_dir=str(run_dir),
        preset="moth-tiny", model_overrides={k: v for k, v in base_cfg.to_dict().items() if k not in ("vocab_size", "name")},
        seq_len=seq_len, batch_size=int(spec.get("batch_size", 8)),
        grad_accum=int(spec.get("grad_accum", 1)), max_steps=int(spec["steps"]), lr=float(spec["lr"]),
        min_lr=float(spec.get("min_lr", float(spec["lr"]) / 10)), warmup_steps=int(spec.get("warmup_steps", 0)),
        weight_decay=float(spec.get("weight_decay", 0.0)), eval_interval=int(spec.get("eval_interval", 50)),
        eval_iters=int(spec.get("eval_iters", 8)), log_interval=int(spec.get("log_interval", 5)),
        checkpoint_interval=int(spec.get("checkpoint_interval", 50)), keep_checkpoints=2,
        device=spec.get("device", "auto"), seed=int(spec.get("seed", 1337)),
        duty_cycle=float(spec.get("duty_cycle", 1.0)), gpu_memory_fraction=spec.get("gpu_memory_fraction"),
        init_from=None if spec.get("from_scratch") else str(base / "model.pt"),
    )
    trainer = Trainer(cfg)
    # continued training keeps the base architecture exactly (vocabulary padding included)
    if trainer.tokenizer.vocab_size > base_cfg.vocab_size:
        raise ValueError("the dataset tokenizer has more tokens than the base model's vocabulary")
    trainer.model_cfg = base_cfg
    resumed = latest_checkpoint(run_dir) is not None
    t0 = time.time()
    res = trainer.run()
    out: dict[str, Any] = {"reason": res["reason"], "step": res["step"], "max_steps": cfg.max_steps,
                           "best_val": res["best_val"] if res["best_val"] != float("inf") else None,
                           "resumed": resumed, "seconds": round(time.time() - t0, 2), "device": trainer.device}
    try:
        import resource

        out["peak_memory_bytes"] = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
    except Exception:  # noqa: BLE001 — not available on every platform
        pass
    if res["reason"] == "completed":
        best = run_dir / "checkpoints" / "best.pt"
        ckpt = best if best.exists() else latest_checkpoint(run_dir)
        pkg_parent = run_dir / "export"
        shutil.rmtree(pkg_parent, ignore_errors=True)
        exported = export_model(ckpt, pkg_parent, spec.get("name", "evolution-candidate"),
                                extra={"lineage": {"base_sha256": manifest["sha256"], "base_name": manifest["name"],
                                                   "method": "from_scratch" if spec.get("from_scratch") else
                                                   "continued"}})
        out["package"] = exported["path"]
        out["sha256"] = exported["sha256"]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Continue training a MOTH model package")
    ap.add_argument("--spec", required=True)
    args = ap.parse_args(argv)
    spec = json.loads(Path(args.spec).read_text())
    result_path = Path(spec["run_dir"]) / "result.json"
    try:
        result = {"ok": True, **run(spec)}
    except Exception as e:  # noqa: BLE001 — every failure becomes a readable result
        result = {"ok": False, "error": f"{type(e).__name__}: {e}"[:2000]}
    tmp = result_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result))
    tmp.replace(result_path)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
