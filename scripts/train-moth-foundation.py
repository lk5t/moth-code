"""Train MOTH 0.1 — Foundation from the approved dataset library (the root of the MOTH model lineage).

    python scripts/train-moth-foundation.py --data /path/to/moth-data [--steps 3000] [--threads 3]

Steps (each is skipped when its verified output already exists, so the command can be re-run safely):

1. download and verify the approved datasets (``<data>/cache``);
2. build the cleaned, deduplicated, decontaminated corpus (``<data>/build-1``);
3. train the 16,384-token BPE tokenizer and tokenize every domain;
4. train the ~49M-parameter model with the curriculum's foundation mixture, resuming from the newest
   verified checkpoint if the run was interrupted (``<data>/moth-0.1/run``).

Stop at any time with Ctrl+C or by creating ``<data>/moth-0.1/run/STOP``; re-run to resume exactly.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from moth.datafactory import build as factory  # noqa: E402
from moth.datafactory.curriculum import plan_mixture  # noqa: E402
from moth.model.tokenizer import Tokenizer, train_bpe  # noqa: E402
from moth.training.trainer import Trainer, TrainConfig  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--steps", type=int, default=3000)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--seq-len", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--preset", default="moth-50m")
    ap.add_argument("--checkpoint-interval", type=int, default=100)
    ap.add_argument("--prepare-only", action="store_true", help="prepare approved data and configuration without training")
    ap.add_argument("--sources", help="comma-separated approved catalog IDs (default: full approved catalog)")
    ap.add_argument("--max-source-chars", type=int, help="optional corpus cap per approved source for development checks")
    ap.add_argument("--vocab-size", type=int, default=16384)
    ap.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    ap.add_argument("--no-batch-autotune", action="store_true")
    a = ap.parse_args()

    data = a.data.resolve()
    build_dir, home = data / "build-1", data / "moth-0.1"
    home.mkdir(parents=True, exist_ok=True)
    has_progress = any((home / "run" / "checkpoints").glob("*.pt*"))
    if has_progress:
        required = [build_dir / "manifest.json", home / "tokenizer.json",
                    build_dir / "tokens" / "mixture.json", home / "lineage.json"]
        if any(not p.is_file() for p in required):
            raise ValueError("existing training progress has missing preparation metadata; refusing to rebuild or overwrite it")
    if not (build_dir / "manifest.json").exists():
        config = {}
        if a.sources:
            config["sources"] = a.sources.split(",")
        if a.max_source_chars:
            from moth.datafactory.catalog import SOURCES

            config["max_chars"] = {s["id"]: a.max_source_chars for s in SOURCES}
        factory.build(data / "cache", build_dir, config)
    manifest = json.loads((build_dir / "manifest.json").read_text())
    if a.sources and set(a.sources.split(",")) != {s["id"] for s in manifest["sources"]}:
        raise ValueError("existing corpus uses different sources; choose a new data directory")
    tok_path = home / "tokenizer.json"
    if not tok_path.exists():
        tok = train_bpe(factory.iter_texts(build_dir, per_domain_chars=4_000_000), a.vocab_size)
        tok.save(tok_path)
    tok = Tokenizer.load(tok_path)
    tokens = build_dir / "tokens"
    mix_file = tokens / "mixture.json"
    if mix_file.exists() and json.loads(mix_file.read_text())["tokenizer_fingerprint"] != tok.fingerprint():
        raise ValueError("existing tokenized data belongs to another tokenizer; use a new data directory")
    if not mix_file.exists():
        factory.tokenize_build(build_dir, tok, tok_path)
    mix = json.loads(mix_file.read_text())
    if mix["build_sha256"] != manifest["content_sha256"]:
        raise ValueError("existing tokenized corpus does not match the prepared build")
    budget = a.steps * a.batch_size * a.grad_accum * a.seq_len
    plan = plan_mixture({d: v["tokens"]["train"] for d, v in mix["domains"].items()}, budget, "foundation")
    lineage_file = home / "lineage.json"
    if lineage_file.exists():
        lineage = json.loads(lineage_file.read_text())
        if lineage["dataset_build"] != mix["build_sha256"]:
            raise ValueError("existing lineage belongs to another corpus build; refusing to replace its training data")
        plan = lineage["mixture"]  # retain the original replay mixture when resuming
    else:
        lineage = {"lineage_id": f"moth-{uuid.uuid4().hex[:12]}", "model_name": "MOTH", "model_version": "0.1",
                   "stage": "foundation", "parent": None, "base_tokens": 0, "base_steps": 0,
                   "dataset_build": mix["build_sha256"], "mixture": plan}
        lineage_file.write_text(json.dumps(lineage, indent=1))
    cfg = TrainConfig(run_name="moth-0.1-foundation", dataset=str(tokens), out_dir=str(home / "run"),
                      preset=a.preset, seq_len=a.seq_len, batch_size=a.batch_size, grad_accum=a.grad_accum,
                      max_steps=a.steps, lr=a.lr, min_lr=a.lr / 10, warmup_steps=max(20, a.steps // 20),
                      eval_interval=max(10, a.checkpoint_interval), eval_iters=28, log_interval=5,
                      checkpoint_interval=a.checkpoint_interval, keep_checkpoints=3, device=a.device,
                      batch_autotune=not a.no_batch_autotune,
                      precision="auto", mixture=plan["weights"], threads=a.threads,
                      lineage={k: lineage[k] for k in ("lineage_id", "model_version", "stage", "base_tokens",
                                                       "base_steps")})
    if a.prepare_only:
        print(json.dumps({"status": "prepared_only", "training_complete": False, "config": cfg.to_dict(),
                          "tokenizer_fingerprint": tok.fingerprint(), "dataset_build": mix["build_sha256"]}, indent=2))
        return 0

    def show(e: dict) -> None:
        if e["kind"] == "metrics" and e.get("split") == "train" and e["step"] % 25 == 0:
            print(f"step {e['step']}/{a.steps} loss {e['loss']:.3f} lr {e['lr']:.2e} "
                  f"{e['tokens_per_sec']:.0f} tok/s", flush=True)
        elif e["kind"] == "metrics" and e.get("split") == "val":
            doms = " ".join(f"{d}={v:.2f}" for d, v in sorted((e.get("domains") or {}).items()))
            print(f"VAL step {e['step']} loss {e['loss']:.3f} ppl {e['perplexity']:.1f} | {doms}", flush=True)
        elif e["kind"] in ("start", "end", "error", "warning", "checkpoint"):
            print(e["kind"], {k: v for k, v in e.items() if k not in ("kind", "model_config")}, flush=True)

    result = Trainer(cfg, on_event=show).run()
    print("RESULT", json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
