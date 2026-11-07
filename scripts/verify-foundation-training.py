"""Real 49.3M-parameter training/resume/export/inference smoke check, not a quality benchmark.

Uses a fresh directory and Python stdlib source (PSF-2.0). Never touches an existing run.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True, help="new, nonexistent output directory")
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    import torch
    from moth.model.config import preset
    from moth.model.generation import GenerationParams, GenerationStats, generate_stream
    from moth.model.registry import export_model, load_model
    from moth.model.tokenizer import train_bpe
    from moth.model.transformer import MothModel
    from moth.training.checkpoint import load_latest_verified
    from moth.training.data import prepare_dataset
    from moth.training.sources import SourceSpec, iter_source
    from moth.training.trainer import TrainConfig, Trainer

    torch.set_num_threads(args.threads)
    source = SourceSpec("stdlib", license="PSF-2.0", max_bytes=400_000)
    texts = [doc.text for doc in iter_source(source)]
    tok = train_bpe(texts, vocab_size=512)
    tokenizer = args.out / "tokenizer.json"
    tok.save(tokenizer)
    prepare_dataset([source], tok, tokenizer, args.out / "dataset", val_fraction=0.1)
    cfg = preset("moth-50m")  # full embeddings/architecture; tokenizer uses a compatible subset
    torch.manual_seed(1337)
    initial = {k: v.clone() for k, v in MothModel(cfg).state_dict().items()}
    tc = TrainConfig(dataset=str(args.out / "dataset"), out_dir=str(args.out / "run"),
                     seq_len=32, batch_size=2, grad_accum=1, max_steps=2, warmup_steps=0,
                     eval_interval=1, eval_iters=2, checkpoint_interval=1, precision="fp32",
                     threads=args.threads, batch_autotune=True)
    trainer = Trainer(tc)
    trainer.model_cfg = cfg
    result = trainer.run()
    _, checkpoint = load_latest_verified(args.out / "run")
    changed = [k for k, v in initial.items() if not torch.equal(v, checkpoint["model"][k])]
    assert len(changed) == len(initial), "not every weight tensor received an update"
    assert checkpoint["optimizer"]["state"] and checkpoint["step"] == 2
    del initial, checkpoint
    tc.max_steps = 3
    trainer = Trainer(tc)
    trainer.model_cfg = cfg
    resumed = trainer.run()
    path, checkpoint = load_latest_verified(args.out / "run")
    assert checkpoint["step"] == 3 and checkpoint["tokens_seen"] == 3 * 2 * 32
    exported = export_model(path, args.out / "models", "foundation-architecture-smoke", dtype="float32")
    model, tokenizer, manifest = load_model(Path(exported["path"]), device="cpu", verify=True)
    stats = GenerationStats()
    pieces = list(generate_stream(model, tokenizer, [tokenizer.bos_id] + tokenizer.encode("def add(a, b):"),
                                 GenerationParams(max_new_tokens=8, temperature=0), stats=stats))
    assert stats.generated_tokens > 0
    report = {"purpose": "architecture training/resume/inference smoke only", "params": model.num_params(),
              "trained_foundation_quality_verified": False, "weight_tensors_updated": len(changed),
              "training": result, "resumed": resumed, "tokens_seen": checkpoint["tokens_seen"],
              "generated_tokens": stats.generated_tokens, "stream_chunks": len(pieces),
              "weights_sha256": manifest["sha256"], "batch_tuning": checkpoint["batch_tuning"]}
    (args.out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
