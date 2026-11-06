"""Candidate evaluation: consistent benchmark suites and promotion gates.

A candidate is compared with its base (normally the deployed model) on the same deterministic suites
(``moth.model.benchmark``), run in an isolated subprocess. It is promoted only if **every** gate passes:

* ``release_checks`` — the existing release gate (``models.evaluate``): loads with a valid checksum,
  generates, finite score, and not worse than the deployed model on the general evaluation dataset;
* ``target_improvement`` — held-out score on the validation split of the data it was trained on
  improves by at least ``gates.min_improvement`` (a lower *training* loss is never enough);
* ``retention:*`` — no dataset an ancestor learned, and no uploaded evaluation dataset, gets worse by
  more than ``gates.retention_tolerance`` (catastrophic forgetting);
* ``code_syntax`` — the valid-Python completion rate does not drop by more than ``gates.code_tolerance``;
* ``tasks:*`` — Owner-supplied task suites (reasoning, instruction following, accuracy) do not drop by
  more than ``gates.task_tolerance``;
* ``speed`` / ``memory`` — generation speed and peak memory stay within the configured limits.

Results are stored per model version and suite (``evaluation_reports``) so versions can be compared
and the planner can find weaknesses. Suites a model cannot be scored on are reported, not invented.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from moth_server.context import Ctx
from moth_server.evolution import datasets as DS
from moth_server.evolution import memory as MEM

BENCH_TIMEOUT_S = 3600
CODE_SUITE_SHA = hashlib.sha256(b"code_syntax/v1").hexdigest()


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def suites_root(ctx: Ctx) -> Path:
    p = ctx.settings.data_dir / "evolution" / "suites"
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_suites(ctx: Ctx) -> list[dict[str, Any]]:
    out = []
    for meta_p in sorted(suites_root(ctx).glob("*.json")):
        m = json.loads(meta_p.read_text())
        data = meta_p.with_suffix(".jsonl")
        if data.exists():
            out.append({**m, "path": str(data)})
    return out


def add_task_suite(ctx: Ctx, name: str, capability: str, data: bytes) -> dict[str, Any]:
    items = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    if not items:
        raise ValueError("the task suite is empty")
    for i, it in enumerate(items[:1000]):
        if not isinstance(it, dict) or "prompt" not in it or "answer" not in it:
            raise ValueError(f"line {i + 1}: each line needs \"prompt\" and \"answer\"")
    sha = hashlib.sha256(data).hexdigest()
    sid = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:40] or sha[:12]
    (suites_root(ctx) / f"{sid}.jsonl").write_bytes(data)
    meta = {"id": sid, "name": name[:80], "capability": capability[:32], "sha256": sha, "items": len(items)}
    (suites_root(ctx) / f"{sid}.json").write_text(json.dumps(meta))
    return meta


def build_suites(ctx: Ctx, release: dict) -> list[dict[str, Any]]:
    """The benchmark suites a model of this tokenizer is compared on (same list for base and candidate)."""
    from moth_server import evalsets

    fp = release["info"].get("tokenizer_fingerprint")
    suites: list[dict[str, Any]] = []
    for d in DS.all_(ctx):
        if d["tokenizer_fingerprint"] != fp or d["status"] == "pending":
            continue
        suites.append({"id": f"retention:{d['sha256'][:16]}", "kind": "heldout", "name": f"{d['name']} (held-out)",
                       "dataset": DS.val_suite(d), "sha": _sha(f"heldout/v1:{d['sha256']}:val")})
    for ds in evalsets.all_datasets(ctx):
        ok, _ = evalsets.compatible(ds, fp)
        if ok:
            suites.append({"id": f"heldout:{ds['id']}", "kind": "heldout", "name": ds.get("name") or ds["id"],
                           "dataset": evalsets.spec(ds), "sha": _sha(f"heldout/v1:{ds['sha256']}")})
    suites.append({"id": "code_syntax", "kind": "code_syntax", "name": "Python completion validity",
                   "sha": CODE_SUITE_SHA})
    for t in task_suites(ctx):
        suites.append({"id": f"tasks:{t['id']}", "kind": "tasks", "name": f"{t['name']} ({t['capability']})",
                       "path": t["path"], "capability": t["capability"], "sha": _sha(f"tasks/v1:{t['sha256']}")})
    return suites


def _run(package: Path, suites: list[dict], timeout: int = BENCH_TIMEOUT_S) -> dict:
    import moth

    with tempfile.TemporaryDirectory(prefix="moth-bench-") as tmp:
        spec, out = Path(tmp) / "suites.json", Path(tmp) / "report.json"
        spec.write_text(json.dumps(suites))
        env = dict(os.environ)
        roots = [str(Path(moth.__file__).resolve().parents[1])]
        env["PYTHONPATH"] = os.pathsep.join(roots + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run([sys.executable, "-m", "moth.model.benchmark", "--package", str(package),
                                   "--suites", str(spec), "--out", str(out)],
                                  capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"benchmarks did not finish within {timeout // 60} minutes"}
        if out.exists():
            return json.loads(out.read_text())
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return {"ok": False, "error": f"the benchmark process crashed: {' '.join(tail)[:500]}"}


def benchmark(ctx: Ctx, version: int, package: Path, suites: list[dict]) -> dict[str, Any]:
    """Scores of ``version`` on ``suites`` (cached per version and suite) plus a fresh performance run."""
    have = {s["id"]: MEM.report(ctx, version, s["sha"]) for s in suites}
    missing = [s for s in suites if have[s["id"]] is None]
    rep = _run(package, missing or [])
    if not rep.get("ok"):
        raise RuntimeError(rep.get("error") or "benchmark failed")
    for s in missing:
        r = rep["suites"].get(s["id"]) or {"ok": False, "error": "not run"}
        MEM.save_report(ctx, version, s["id"], s["sha"], r)
        have[s["id"]] = r
    perf = rep.get("performance") or {}
    MEM.save_report(ctx, version, "performance", _sha("performance/v1"), perf)
    return {"suites": have, "performance": perf}


def _better(c: float, b: float, higher: bool) -> float:
    """Relative improvement of candidate over base (positive = better)."""
    if b == 0:
        return 0.0 if c == b else (1.0 if (c > b) == higher else -1.0)
    return (c - b) / abs(b) if higher else (b - c) / abs(b)


def gate(ctx: Ctx, candidate: dict, base: dict, target_dataset: dict, settings: dict) -> dict[str, Any]:
    from moth_server import models as M

    g = settings["gates"]
    gates: list[dict[str, Any]] = []
    rel = M.evaluate(ctx, candidate["version"])
    ev = rel.get("evaluation") or {}
    gates.append({"gate": "release_checks", "passed": rel["status"] == "published",
                  "detail": "loads with a valid checksum, generates, and is not worse than the deployed model on "
                            "the general evaluation dataset" if rel["status"] == "published" else
                  (rel.get("error") or f"release gate result: {rel['status']}"),
                  "candidate": (ev.get("score") or {}).get("value"),
                  "baseline": ((ev.get("baseline") or {}).get("score") or {}).get("value")})
    suites = build_suites(ctx, candidate)
    base_scores = benchmark(ctx, base["version"], Path(base["path"]), suites)
    cand_scores = benchmark(ctx, candidate["version"], Path(candidate["path"]), suites)
    target_id = f"retention:{target_dataset['sha256'][:16]}"
    improvement = None
    for s in suites:
        b, c = base_scores["suites"].get(s["id"]) or {}, cand_scores["suites"].get(s["id"]) or {}
        entry = {"gate": s["id"], "name": s["name"], "candidate": c.get("value"), "baseline": b.get("value")}
        if not c.get("ok"):
            entry.update(passed=not b.get("ok"), detail=("not measurable for either model: " if not b.get("ok")
                                                         else "the candidate could not be scored: ") + str(c.get("error")))
            gates.append(entry)
            continue
        if not b.get("ok"):
            entry.update(passed=True, detail="no baseline score (the base model could not be scored on it)")
            gates.append(entry)
            continue
        higher = bool(c.get("higher_is_better"))
        rel_imp = _better(float(c["value"]), float(b["value"]), higher)
        entry["change"] = rel_imp
        if s["id"] == target_id:
            improvement = rel_imp
            entry.update(gate="target_improvement", passed=rel_imp >= float(g["min_improvement"]),
                         detail=f"held-out score on the training data's validation split must improve by "
                                f"≥ {float(g['min_improvement']):.1%} (changed {rel_imp:+.2%})")
        elif s["kind"] == "heldout":
            entry.update(passed=rel_imp >= -float(g["retention_tolerance"]),
                         detail=f"retention: may not get worse by more than {float(g['retention_tolerance']):.1%} "
                                f"(changed {rel_imp:+.2%})")
        elif s["kind"] == "code_syntax":
            drop = float(b["value"]) - float(c["value"])
            entry.update(passed=drop <= float(g["code_tolerance"]),
                         detail=f"valid-Python rate {float(b['value']):.0%} → {float(c['value']):.0%}")
        else:
            drop = float(b["value"]) - float(c["value"])
            entry.update(passed=drop <= float(g["task_tolerance"]),
                         detail=f"accuracy {float(b['value']):.0%} → {float(c['value']):.0%}")
        gates.append(entry)
    if improvement is None:
        gates.append({"gate": "target_improvement", "passed": False,
                      "detail": "the training data's validation split could not be scored"})
    bp, cp = base_scores["performance"], cand_scores["performance"]
    if bp.get("tokens_per_second") and cp.get("tokens_per_second") is not None:
        ratio = cp["tokens_per_second"] / bp["tokens_per_second"]
        gates.append({"gate": "speed", "passed": ratio >= 1 - float(g["max_speed_regression"]),
                      "candidate": cp["tokens_per_second"], "baseline": bp["tokens_per_second"],
                      "detail": f"generation speed {ratio:.0%} of the base model's"})
    if bp.get("peak_memory_bytes") and cp.get("peak_memory_bytes"):
        ratio = cp["peak_memory_bytes"] / bp["peak_memory_bytes"]
        gates.append({"gate": "memory", "passed": ratio <= 1 + float(g["max_memory_growth"]),
                      "candidate": cp["peak_memory_bytes"], "baseline": bp["peak_memory_bytes"],
                      "detail": f"peak memory {ratio:.0%} of the base model's"})
    return {"passed": all(x["passed"] for x in gates), "gates": gates, "primary_improvement": improvement,
            "release_status": rel["status"], "performance": {"candidate": cp, "base": bp}}
