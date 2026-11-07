"""Evaluate a MOTH model package on the capability benchmarks and check the release criteria.

    python scripts/evaluate-model.py --package DIR --eval-dir EVAL --out report.json [--quick]

``EVAL`` holds the Data Factory's held-out files (``math.jsonl``, ``reasoning.jsonl``, ``code.jsonl``,
``holdout_<domain>.jsonl``). The report lists every suite's measurement, the generation speed on one
CPU thread and the release-criteria result. Run by the model-release workflow before anything is
signed, so the published numbers are reproduced independently of the machine that trained the model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

LIMITS = {"math": 50, "reasoning": 200, "code": 50, "instruction": 30, "holdout": 200}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--eval-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--quick", action="store_true", help="small item counts (smoke tests only)")
    a = ap.parse_args()

    import torch

    torch.manual_seed(0)
    torch.set_num_threads(1)  # speed is reported for one CPU thread: comparable across machines
    from moth.model.capabilities import run_suite
    from moth.model.generation import GenerationParams, GenerationStats, generate_stream
    from moth.model.registry import load_model
    from moth.model.release_criteria import check
    from moth.policy.engine import with_safety_baseline

    t0 = time.time()
    model, tok, manifest = load_model(a.package, device="cpu", verify=True)
    limits = {k: (3 if a.quick else v) for k, v in LIMITS.items()}
    suites: dict[str, dict] = {}
    files: dict[str, str] = {}
    specs = [("math", "math.jsonl"), ("reasoning", "reasoning.jsonl"), ("code", "code.jsonl"),
             ("instruction", "holdout_conversation.jsonl")]
    specs += [(f"holdout:{p.stem.split('_', 1)[1]}", p.name) for p in sorted(a.eval_dir.glob("holdout_*.jsonl"))]
    for name, fname in specs:
        p = a.eval_dir / fname
        if not p.exists():
            continue
        cap = name.split(":")[0]
        files[fname] = hashlib.sha256(p.read_bytes()).hexdigest()
        ts = time.time()
        r = run_suite(model, tok, {"capability": cap, "path": str(p), "limit": limits[cap]})
        r["ok"] = True
        r["seconds"] = round(time.time() - ts, 1)
        suites[name] = r
        print(f"{name}: {r.get('metric')} = {r['value']:.4f} ({r.get('n', r.get('tokens'))} items, {r['seconds']} s)",
              flush=True)
    r = run_suite(model, tok, {"capability": "safety", "policy": with_safety_baseline({})})
    r["ok"] = True
    suites["safety"] = r
    print(f"safety: refusal rate {r['value']:.2f}", flush=True)
    # speed: greedy generation of 64 tokens, one thread
    speeds = []
    for prompt in ("Once upon a time", "The capital of France is", "def add(a, b):"):
        st = GenerationStats()
        "".join(generate_stream(model, tok, [tok.bos_id] + tok.encode(prompt),
                                GenerationParams(max_new_tokens=64, temperature=0.0, top_k=0), stop_ids=set(),
                                stats=st))
        speeds.append(st.tokens_per_sec)
    perf = {"tokens_per_second": round(sum(speeds) / len(speeds), 2), "threads": 1,
            "params": manifest.get("params"), "load_seconds": round(time.time() - t0, 1)}
    report = {"model": {k: manifest.get(k) for k in ("name", "display_name", "model_version", "params", "sha256",
                                                     "tokenizer_fingerprint", "context_length")},
              "suites": suites, "performance": perf, "eval_files": files, "limits": limits,
              "torch": torch.__version__, "created": time.time()}
    report["criteria"] = check(report)
    a.out.write_text(json.dumps(report, indent=1))
    for c in report["criteria"]["criteria"]:
        print(f"  {'PASS' if c['passed'] else 'FAIL'}  {c['id']}: {c['measured']} {c['op']} {c['value']} — {c['why']}")
    print("RELEASE CRITERIA:", "PASSED" if report["criteria"]["passed"] else "NOT MET")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
