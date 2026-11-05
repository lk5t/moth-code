"""Real evaluation of a MOTH model package (run by MOTH Cloud in an isolated subprocess).

    python -m moth.model.evaluate --package DIR --dataset dataset.json --out report.json

The model is loaded from disk with checksum verification, then actually run:

* **generation** — several prompts must produce tokens and decodable text; speed is measured;
* **held-out score** on an evaluation dataset:
  - ``text`` datasets (UTF-8 text): **bits per byte** using the model's *own* tokenizer, so
    models with different tokenizers are scored on the same footing;
  - ``tokens`` datasets (uint32 ids, e.g. the training coordinator's probe set): mean token
    loss, valid only for models whose tokenizer fingerprint matches the dataset's;
* **resources** — peak memory of the evaluation process and load time.

Nothing here decides deployment; the server applies the gate to this report.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

PROMPTS = ("def ", "class ", "# ", "import ")
MAX_TEXT_BYTES = 192 * 1024
MAX_WINDOWS = 24


class EvalError(RuntimeError):
    pass


def _peak_rss() -> int | None:
    try:
        import resource

        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(kb * (1 if sys.platform == "darwin" else 1024))
    except Exception:  # noqa: BLE001
        return None


def _windows(ids: list[int] | np.ndarray, seq: int) -> list[tuple[np.ndarray, np.ndarray]]:
    ids = np.asarray(ids, dtype=np.int64)
    n = min(MAX_WINDOWS, (len(ids) - 1) // seq)
    if n < 1:
        raise EvalError(f"evaluation dataset is too small: {len(ids)} tokens, need at least {seq + 1}")
    return [(ids[i * seq:(i + 1) * seq], ids[i * seq + 1:(i + 1) * seq + 1]) for i in range(n)]


def score_text(model, tok, text: str) -> dict[str, Any]:
    import torch

    raw = text.encode("utf-8")[:MAX_TEXT_BYTES].decode("utf-8", errors="ignore")
    ids = tok.encode(raw)
    seq = min(256, model.cfg.max_seq_len)
    total_nats, total_bytes, tokens = 0.0, 0, 0
    device = next(model.parameters()).device
    with torch.no_grad():
        for x, y in _windows(ids, seq):
            logits, _ = model(torch.from_numpy(x)[None].to(device))
            logp = torch.log_softmax(logits.float(), dim=-1)[0]
            nll = -logp[torch.arange(len(y)), torch.from_numpy(y).to(device)]
            total_nats += float(nll.sum())
            total_bytes += sum(len(tok.decode_bytes([int(t)], skip_special=False)) for t in y)
            tokens += len(y)
    if total_bytes == 0:
        raise EvalError("evaluation text produced no scorable bytes")
    bpb = total_nats / total_bytes / math.log(2)
    return {"metric": "bits_per_byte", "value": bpb, "tokens": tokens, "bytes": total_bytes,
            "token_loss": total_nats / tokens}


def score_tokens(model, ids: np.ndarray) -> dict[str, Any]:
    import torch

    if len(ids) and int(ids.max()) >= model.cfg.vocab_size:
        raise EvalError("evaluation token set uses a different tokenizer than this model")
    seq = min(256, model.cfg.max_seq_len)
    device = next(model.parameters()).device
    losses = []
    with torch.no_grad():
        for x, y in _windows(ids, seq):
            _, loss = model(torch.from_numpy(x)[None].to(device), torch.from_numpy(y)[None].to(device))
            losses.append(float(loss))
    return {"metric": "token_loss", "value": float(np.mean(losses)), "tokens": len(losses) * seq}


def evaluate_package(package: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    from moth.model.generation import GenerationParams, generate
    from moth.model.package import inspect_package
    from moth.model.registry import load_model

    report: dict[str, Any] = {"checks": {}, "dataset": {k: dataset.get(k) for k in ("id", "name", "kind", "sha256",
                                                                                    "source")}}
    insp = inspect_package(package, deep=True)
    report["checks"]["package_valid"] = insp["ok"]
    if not insp["ok"]:
        raise EvalError("; ".join(insp["problems"]))
    t0 = time.time()
    model, tok, manifest = load_model(package, device="cpu", verify=True)
    report["load_seconds"] = round(time.time() - t0, 2)
    report["checks"]["loads_and_checksum"] = True
    samples, speeds = [], []
    for prompt in PROMPTS:
        text, stats = generate(model, tok, prompt, GenerationParams(max_new_tokens=24, temperature=0.0, top_k=1))
        samples.append({"prompt": prompt, "output": text[:200], "tokens": stats.generated_tokens})
        if stats.generated_tokens:
            speeds.append(stats.tokens_per_sec)
    report["samples"] = samples
    report["tokens_per_second"] = round(float(np.mean(speeds)), 1) if speeds else 0.0
    report["checks"]["generates"] = any(s["tokens"] > 0 and len(s["output"]) > 0 for s in samples)
    # informational, not a gate: an undertrained model often repeats whitespace or one token
    report["output_is_whitespace_only"] = all(not s["output"].strip() for s in samples)
    if dataset["kind"] == "text":
        text = Path(dataset["path"]).read_text(encoding="utf-8", errors="replace")
        score = score_text(model, tok, text)
    elif dataset["kind"] == "tokens":
        fp = dataset.get("tokenizer_fingerprint")
        if fp and fp != tok.fingerprint():
            raise EvalError("evaluation token set was made with a different tokenizer; use a text dataset")
        score = score_tokens(model, np.fromfile(dataset["path"], dtype=np.uint32)[:64 * 1024])
    else:
        raise EvalError(f"unknown evaluation dataset kind {dataset['kind']!r}")
    score.update({"dataset_id": dataset.get("id"), "dataset_sha256": dataset.get("sha256")})
    report["score"] = score
    report["checks"]["finite_score"] = math.isfinite(score["value"])
    report["peak_memory_bytes"] = _peak_rss()
    report["params"] = manifest.get("params")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate a MOTH model package")
    ap.add_argument("--package", required=True)
    ap.add_argument("--dataset", required=True, help="JSON file describing the evaluation dataset")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        import torch

        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        report = evaluate_package(Path(args.package), json.loads(Path(args.dataset).read_text()))
        report["ok"] = True
    except Exception as e:  # noqa: BLE001 — every failure becomes a readable report
        report = {"ok": False, "error": f"{type(e).__name__}: {e}" if not isinstance(e, EvalError) else str(e),
                  "peak_memory_bytes": _peak_rss()}
    Path(args.out).write_text(json.dumps(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
