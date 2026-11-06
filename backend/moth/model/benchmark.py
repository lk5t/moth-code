"""Deterministic benchmark suites for comparing MOTH model versions (run in an isolated subprocess).

    python -m moth.model.benchmark --package DIR --suites suites.json --out report.json

Every suite is deterministic (greedy decoding, fixed windows), so two versions evaluated on the same
suite get directly comparable numbers. Suites:

* ``heldout`` — held-out score on a text (bits per byte) or token (mean token loss) dataset. Used for
  the primary score and for **retention**: the datasets earlier versions were evaluated or trained on
  are re-scored to detect catastrophic forgetting.
* ``code_syntax`` — coding: greedy completions of Python function stubs; the fraction whose completed
  body parses as valid Python (``ast``). Deterministic and executed for real, never sandboxed code
  execution.
* ``tasks`` — a JSON Lines suite of ``{"prompt", "answer"}`` (exact or ``contains`` match) supplied by
  the Owner for reasoning, instruction following or factual accuracy; the share of wrong answers is
  reported as the error (hallucination) rate. Without a supplied suite these capabilities are reported
  as *not measured* — never estimated.
* ``performance`` — load time, generation speed (tokens/s) and peak memory.

Lower is better for ``heldout``; higher is better for ``code_syntax`` and ``tasks`` accuracy.
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from moth.model.evaluate import EvalError, _peak_rss, score_text, score_tokens

# Python stubs whose bodies the model completes. Kept small and fixed so results stay comparable.
CODE_PROMPTS = (
    "def add(a, b):\n",
    "def is_even(n):\n",
    "def reverse_string(s):\n",
    "def factorial(n):\n",
    "def maximum(values):\n",
    "def count_words(text):\n",
    "class Stack:\n    def __init__(self):\n",
    "def read_lines(path):\n",
)
CODE_TOKENS = 48
TASK_TOKENS = 32
MAX_TASKS = 200


def _complete(model, tok, prompt: str, max_new: int) -> tuple[str, Any]:
    from moth.model.generation import GenerationParams, generate

    return generate(model, tok, prompt, GenerationParams(max_new_tokens=max_new, temperature=0.0, top_k=1))


def _parses(prompt: str, completion: str) -> bool:
    """Does the stub plus the completed body (up to the end of the indented block) parse?"""
    lines = (prompt + completion).splitlines()
    body: list[str] = []
    seen_body = False
    for i, line in enumerate(lines):
        if i < prompt.count("\n"):
            body.append(line)
            continue
        if line.strip() and not line.startswith((" ", "\t")):
            break  # the block ended: a new top-level statement starts
        if line.strip():
            seen_body = True
        body.append(line)
    if not seen_body:
        return False
    # the last line may be cut by the token limit: drop it if it alone breaks parsing
    for candidate in (body, body[:-1]):
        if not candidate:
            continue
        try:
            ast.parse("\n".join(candidate) + "\n")
            return any(line.strip() for line in candidate[prompt.count("\n"):])
        except SyntaxError:
            continue
    return False


def code_syntax(model, tok) -> dict[str, Any]:
    ok, samples = 0, []
    for p in CODE_PROMPTS:
        text, _ = _complete(model, tok, p, CODE_TOKENS)
        good = _parses(p, text)
        ok += good
        samples.append({"prompt": p.splitlines()[0], "valid": good})
    return {"metric": "valid_python_rate", "value": ok / len(CODE_PROMPTS), "n": len(CODE_PROMPTS),
            "higher_is_better": True, "samples": samples}


def tasks_suite(model, tok, path: Path) -> dict[str, Any]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(json.loads(line))
        if len(items) >= MAX_TASKS:
            break
    if not items:
        raise EvalError("the task suite is empty")
    correct = 0
    for it in items:
        out, _ = _complete(model, tok, str(it["prompt"]), int(it.get("max_tokens", TASK_TOKENS)))
        ans = str(it["answer"]).strip()
        got = out.strip()
        hit = (ans in got) if it.get("match") == "contains" else got.split("\n")[0].strip() == ans
        correct += hit
    acc = correct / len(items)
    return {"metric": "accuracy", "value": acc, "error_rate": 1 - acc, "n": len(items), "higher_is_better": True}


def heldout(model, tok, ds: dict[str, Any]) -> dict[str, Any]:
    if ds["kind"] == "text":
        score = score_text(model, tok, Path(ds["path"]).read_text(encoding="utf-8", errors="replace"))
    elif ds["kind"] == "tokens":
        fp = ds.get("tokenizer_fingerprint")
        if fp and fp != tok.fingerprint():
            raise EvalError("token dataset was made with a different tokenizer")
        dtype = np.dtype(ds.get("dtype") or "uint32")
        score = score_tokens(model, np.fromfile(ds["path"], dtype=dtype)[:64 * 1024].astype(np.int64))
    else:
        raise EvalError(f"unknown dataset kind {ds['kind']!r}")
    score["higher_is_better"] = False
    return score


def run(package: Path, suites: list[dict[str, Any]]) -> dict[str, Any]:
    from moth.model.registry import load_model

    t0 = time.time()
    model, tok, manifest = load_model(package, device="cpu", verify=True)
    load_s = time.time() - t0
    out: dict[str, Any] = {"suites": {}, "sha256": manifest["sha256"]}
    speeds = []
    for s in suites:
        try:
            if s["kind"] == "heldout":
                r = heldout(model, tok, s["dataset"])
            elif s["kind"] == "code_syntax":
                r = code_syntax(model, tok)
            elif s["kind"] == "tasks":
                r = tasks_suite(model, tok, Path(s["path"]))
            else:
                raise EvalError(f"unknown suite kind {s['kind']!r}")
            r["ok"] = math.isfinite(float(r["value"]))
        except EvalError as e:
            r = {"ok": False, "error": str(e)}
        out["suites"][s["id"]] = {**r, "kind": s["kind"], "name": s.get("name", s["id"])}
    for p in ("def ", "import "):
        _, stats = _complete(model, tok, p, 32)
        if stats.generated_tokens:
            speeds.append(stats.tokens_per_sec)
    out["performance"] = {"load_seconds": round(load_s, 3), "tokens_per_second": round(float(np.mean(speeds)), 2)
                          if speeds else 0.0, "peak_memory_bytes": _peak_rss(), "params": manifest.get("params")}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Benchmark a MOTH model package")
    ap.add_argument("--package", required=True)
    ap.add_argument("--suites", required=True, help="JSON list of suite specs")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    try:
        import torch

        torch.manual_seed(0)
        torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
        report = run(Path(args.package), json.loads(Path(args.suites).read_text()))
        report["ok"] = True
    except Exception as e:  # noqa: BLE001
        report = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    Path(args.out).write_text(json.dumps(report))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
