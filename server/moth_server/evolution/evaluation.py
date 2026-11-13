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
    if len(items)>200:raise ValueError("task suites support at most 200 items")
    for i, it in enumerate(items):
        if not isinstance(it, dict) or "prompt" not in it or "answer" not in it:
            raise ValueError(f"line {i + 1}: each line needs \"prompt\" and \"answer\"")
        if not all(isinstance(it[k],str) and it[k].strip() for k in ("prompt","answer")):
            raise ValueError(f"line {i + 1}: prompt and answer must be non-empty text")
        if capability == "consistency" and not (isinstance(it.get("paraphrase"),str) and it["paraphrase"].strip()):
            raise ValueError(f"line {i + 1}: consistency needs a paraphrase and reference answer")
        if "max_tokens" in it and (type(it["max_tokens"]) is not int or not 1 <= it["max_tokens"] <= 256):
            raise ValueError(f"line {i + 1}: max_tokens must be between 1 and 256")
    sha = hashlib.sha256(data).hexdigest()
    sid = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:40] or sha[:12]
    (suites_root(ctx) / f"{sid}.jsonl").write_bytes(data)
    meta = {"id": sid, "name": name[:80], "capability": capability[:32], "sha256": sha, "items": len(items)}
    (suites_root(ctx) / f"{sid}.json").write_text(json.dumps(meta))
    return meta


CAPABILITY_LIMITS = {"math": 50, "reasoning": 200, "code": 50, "instruction": 30, "holdout": 200}


def capability_suites(ctx: Ctx) -> list[dict[str, Any]]:
    """0.5.1 capability benchmarks from the latest dataset-library build (never-trained held-out data).

    They are scored from text, so models with different tokenizers or sizes are compared fairly. The
    suite hash covers the items and the limit, so results are cached per model version."""
    from moth_server.intelligence import library

    d = library.eval_dir(ctx)
    if d is None:
        return []
    out: list[dict[str, Any]] = []

    def file_sha(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    names = {"math": "Maths (GSM8K)", "reasoning": "Reasoning (ARC-Easy)", "code": "Code (MBPP, executed)"}
    for cap in ("math", "reasoning", "code"):
        p = d / f"{cap}.jsonl"
        if p.exists():
            lim = CAPABILITY_LIMITS[cap]
            out.append({"id": f"capability:{cap}:{p.stem}", "kind": "capability", "capability": cap, "path": str(p),
                        "limit": lim, "name": names[cap], "sha": _sha(f"capability/v1:{cap}:{lim}:{file_sha(p)}")})
    conv = d / "holdout_conversation.jsonl"
    if conv.exists():
        lim = CAPABILITY_LIMITS["instruction"]
        out.append({"id": "capability:instruction:conversation", "kind": "capability", "capability": "instruction",
                    "path": str(conv), "limit": lim, "name": "Instruction following",
                    "sha": _sha(f"capability/v1:instruction:{lim}:{file_sha(conv)}")})
    for p in sorted(d.glob("holdout_*.jsonl")):
        dom = p.stem.split("_", 1)[1]
        lim = CAPABILITY_LIMITS["holdout"]
        out.append({"id": f"capability:holdout:{dom}", "kind": "capability", "capability": "holdout", "path": str(p),
                    "limit": lim, "name": f"Held-out {dom}", "sha": _sha(f"capability/v1:holdout:{lim}:{file_sha(p)}")})
    from moth_server.evolution import settings as _S

    if (_S.get(ctx).get("evaluation") or {}).get("builtin_suites", True):
        out += builtin_suites()
    out.append({"id": "capability:safety:baseline", "kind": "capability", "capability": "safety",
                "name": "Safety (harmful requests refused)", "sha": _sha("capability/v1:safety:1"),
                "policy": _serving_policy(ctx)})
    return out


def builtin_suites() -> list[dict[str, Any]]:
    """0.8.0: conversation and coding benchmarks that need no dataset build. Their items come from
    value lists and functions that never appear in training data (moth.datafactory.dialogue/coding);
    the suite hash covers the items, so a changed benchmark is never compared with old results."""
    from moth.datafactory import coding, dialogue

    conv = json.dumps(list(dialogue.conversations(48, 0, "eval")), sort_keys=True)
    out = [{"id": "capability:dialogue:builtin", "kind": "capability", "capability": "dialogue", "limit": 48,
            "name": "Conversation (multi-turn, held out)", "sha": _sha("capability/v1:dialogue:" + conv)}]
    for kind, name in (("codegen", "Code generation (executed, held out)"), ("debugging", "Debugging (executed, held out)")):
        items = json.dumps(coding.eval_items(kind), sort_keys=True)
        out.append({"id": f"capability:{kind}:builtin", "kind": "capability", "capability": kind,
                    "name": name, "sha": _sha(f"capability/v1:{kind}:" + items)})
    return out


# 0.8.0: capability groups that must stay balanced (conversation and coding are the priorities)
GROUPS = {"conversation": ("dialogue", "instruction", "holdout_conversation"),
          "coding": ("codegen", "debugging", "code", "holdout_code")}


def group_changes(suites: list[dict], base: dict, cand: dict) -> dict[str, dict[str, Any]]:
    """Mean change per capability group (accuracy: points; held-out loss: relative improvement)."""
    out: dict[str, dict[str, Any]] = {}
    for s in suites:
        if s.get("kind") != "capability":
            continue
        key = f"holdout_{s['id'].split(':')[2]}" if s.get("capability") == "holdout" else s.get("capability")
        group = next((g for g, members in GROUPS.items() if key in members), None)
        b, c = base.get(s["id"]) or {}, cand.get(s["id"]) or {}
        if group is None or not (b.get("ok") and c.get("ok")):
            continue
        bv, cv = float(b["value"]), float(c["value"])
        change = (cv - bv) if c.get("higher_is_better") else ((bv - cv) / bv if bv else 0.0)
        g = out.setdefault(group, {"changes": {}, "mean": 0.0})
        g["changes"][key] = round(change, 4)
    for g in out.values():
        g["mean"] = round(sum(g["changes"].values()) / len(g["changes"]), 4)
    return out


def _serving_policy(ctx: Ctx) -> dict[str, Any]:
    from moth.policy.engine import with_safety_baseline

    from moth_server.routes.admin import flags

    p = ctx.db.get_config("content_policy", {}) or {}
    return with_safety_baseline(p) if flags(ctx).get("safety_baseline") else p


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
    suites += capability_suites(ctx)
    for t in task_suites(ctx):
        suites.append({"id": f"tasks:{t['id']}", "kind": "tasks", "name": f"{t['name']} ({t['capability']})",
                       "path": t["path"], "capability": t["capability"], "sha": _sha(f"tasks/v2:{t['sha256']}:{t['capability']}")})
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


def gate(ctx: Ctx, candidate: dict, base: dict, target_dataset: dict, settings: dict,
         mixture: dict | None = None, growth: dict | None = None) -> dict[str, Any]:
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
        elif s["kind"] == "capability" and not higher:  # held-out loss of one capability domain
            entry.update(passed=rel_imp >= -float(g["retention_tolerance"]),
                         detail=f"memory protection: held-out loss may not get worse by more than "
                                f"{float(g['retention_tolerance']):.1%} (changed {rel_imp:+.2%})")
        elif s["kind"] == "capability":
            # accuracy on n items: a drop within sampling noise (2 standard errors) is not a regression
            n = max(1, int(c.get("n") or b.get("n") or 1))
            p_ = min(max(float(b["value"]), 0.0), 1.0)
            noise = 2 * (p_ * (1 - p_) / n) ** 0.5
            allowed = max(float(g["task_tolerance"]), noise)
            drop = float(b["value"]) - float(c["value"])
            entry.update(passed=drop <= allowed, detail=f"{s['name']}: {float(b['value']):.1%} → "
                                                        f"{float(c['value']):.1%} (allowed drop {allowed:.1%})")
        elif s["kind"] == "code_syntax":
            drop = float(b["value"]) - float(c["value"])
            entry.update(passed=drop <= float(g["code_tolerance"]),
                         detail=f"valid-Python rate {float(b['value']):.0%} → {float(c['value']):.0%}")
        else:
            drop = float(b["value"]) - float(c["value"])
            entry.update(passed=drop <= float(g["task_tolerance"]),
                         detail=f"accuracy {float(b['value']):.0%} → {float(c['value']):.0%}")
        gates.append(entry)
    if mixture:  # curriculum runs: the improvement is the weighted held-out gain over all trained domains
        from moth_server.evolution.v2 import mixture_improvement

        mi = mixture_improvement(cand_scores["suites"], base_scores["suites"], mixture.get("weights") or {})
        gates = [g for g in gates if g["gate"] != "target_improvement"]
        improvement = mi
        gates.append({"gate": "target_improvement", "passed": mi is not None and mi >= float(g["min_improvement"]),
                      "change": mi, "detail": "the curriculum's held-out loss (weighted over its domains) must "
                                              f"improve by ≥ {float(g['min_improvement']):.1%}"
                                              + (f" (changed {mi:+.2%})" if mi is not None else " (not measurable)")})
    if improvement is None:
        gates.append({"gate": "target_improvement", "passed": False,
                      "detail": "the training data's validation split could not be scored"})
    if growth and growth.get("target_capabilities"):
        gates.append(growth_gate(growth["target_capabilities"], suites, base_scores["suites"], cand_scores["suites"]))
    groups = group_changes(suites, base_scores["suites"], cand_scores["suites"])
    if groups:  # 0.8.0: a better loss elsewhere never excuses worse conversation or coding as a whole
        tol = float(g["task_tolerance"])
        worse = {k: v["mean"] for k, v in groups.items() if v["mean"] < -tol}
        gates.append({"gate": "balanced_capabilities", "passed": not worse, "groups": groups,
                      "detail": "; ".join(f"{k}: mean change {v['mean']:+.1%}" for k, v in groups.items())
                                + (f" — {', '.join(worse)} got worse beyond {tol:.0%}" if worse else
                                   " — no capability group got worse")})
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


def growth_gate(targets: list[str], suites: list[dict], base: dict, cand: dict) -> dict[str, Any]:
    """A larger candidate grown because of stalled capabilities must improve at least one of them on
    the same benchmark: beyond two standard errors for an accuracy, by at least 1% for a held-out loss.
    Lower loss elsewhere alone does not justify the extra size."""
    detail = []
    for s in suites:
        if s.get("kind") != "capability":
            continue
        cap = s.get("capability")
        key = f"holdout_{s['id'].split(':')[2]}" if cap == "holdout" else cap
        if key not in targets:
            continue
        b, c = base.get(s["id"]) or {}, cand.get(s["id"]) or {}
        if not (b.get("ok") and c.get("ok")):
            detail.append(f"{s['name']}: not measurable")
            continue
        bv, cv = float(b["value"]), float(c["value"])
        if c.get("higher_is_better"):
            n = max(1, int(c.get("n") or b.get("n") or 1))
            p_ = min(max(bv, 0.0), 1.0)
            need = 2 * (p_ * (1 - p_) / n) ** 0.5 or 1.0 / n
            ok = cv - bv > need
            detail.append(f"{s['name']}: {bv:.1%} → {cv:.1%} (needs > +{need:.1%})")
        else:
            rel = (bv - cv) / bv if bv else 0.0
            ok = rel >= 0.01
            detail.append(f"{s['name']} loss: {bv:.3f} → {cv:.3f} ({rel:+.1%}, needs ≥ +1.0%)")
        if ok:
            return {"gate": "growth_justified", "passed": True,
                    "detail": "the larger model improved a capability that motivated it: " + "; ".join(detail)}
    return {"gate": "growth_justified", "passed": False,
            "detail": "the larger model did not improve the capabilities that motivated it beyond noise: "
                      + ("; ".join(detail) or "none of them could be measured")}
