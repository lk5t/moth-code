"""Experiment planning from training memory.

For a base model the planner proposes up to ``max_experiments_per_cycle`` reproducible experiments:

1. **Data**: approved datasets compatible with the base model's tokenizer, in priority order:
   data no ancestor was trained on (new data) → data tied to an identified weakness (a capability the
   base lost compared with its parent: replay; weak coding score: code-tagged data) → the rest.
2. **Hyper-parameters**: learning-rate variants ranked by measured improvement in earlier experiments
   on the same architecture (the best first), else the configured default and half of it.
3. **No repetition**: an exact configuration (same base weights, data, hyper-parameters and seed)
   that already finished is never run again; if every variant was tried, the planner tries longer
   training or a smaller learning rate once, and otherwise proposes nothing.

Incompatible bases (different tokenizer/architecture than the data) are reported as needing an
explicit migration; weights are never loaded across architectures.
"""

from __future__ import annotations

import json
from typing import Any

from moth_server.context import Ctx
from moth_server.evolution import datasets as DS
from moth_server.evolution import memory as MEM


def architecture_key(release: dict) -> str:
    cfg = (release.get("info") or {}).get("config") or {}
    keep = {k: v for k, v in cfg.items() if k not in ("name", "dropout")}
    return MEM.config_hash({"arch": release["info"].get("architecture"), "config": keep})[:24]


def weaknesses(ctx: Ctx, base_version: int) -> list[dict[str, Any]]:
    """Suites where the base model is weak: worse than its parent (forgetting) or a low coding score."""
    out = []
    base = {r["suite_sha"]: r for r in MEM.reports_for(ctx, base_version)}
    anc = MEM.ancestors(ctx, base_version)
    parent = anc[1]["version"] if len(anc) > 1 else None
    par = {r["suite_sha"]: r for r in MEM.reports_for(ctx, parent)} if parent else {}
    for sha, r in base.items():
        m = r["metrics"]
        if not m.get("ok"):
            continue
        p = (par.get(sha) or {}).get("metrics") or {}
        if p.get("ok"):
            worse = (m["value"] < p["value"]) if m.get("higher_is_better") else (m["value"] > p["value"])
            if worse:
                out.append({"suite": r["suite"], "suite_sha": sha, "kind": "regressed_vs_parent",
                            "value": m["value"], "parent_value": p["value"]})
        if r["suite"] == "code_syntax" and m["value"] < 0.5:
            out.append({"suite": "code_syntax", "suite_sha": sha, "kind": "weak_coding", "value": m["value"]})
    return out


def _lr_ranking(ctx: Ctx, arch_key: str, default_lr: float) -> list[float]:
    by_lr: dict[float, list[float]] = {}
    for e in MEM.history_for_architecture(ctx, arch_key):
        imp = (e.get("metrics") or {}).get("primary_improvement")
        lr = (e.get("config") or {}).get("lr")
        if imp is None or lr is None:
            continue
        by_lr.setdefault(float(lr), []).append(float(imp))
    ranked = sorted(by_lr, key=lambda lr: -sum(by_lr[lr]) / len(by_lr[lr]))
    out: list[float] = []
    for lr in ranked[:1] + [default_lr, default_lr * 0.5, (ranked[0] if ranked else default_lr) * 0.5,
                            default_lr * 2]:
        if all(abs(lr - x) > 1e-12 for x in out):
            out.append(lr)
    return out


def plan(ctx: Ctx, base: dict, settings: dict, cycle_seed: int) -> dict[str, Any]:
    tok_fp = base["info"].get("tokenizer_fingerprint")
    all_approved = DS.approved(ctx)
    compatible = [d for d in all_approved if d["tokenizer_fingerprint"] == tok_fp]
    min_tokens = int(settings["min_dataset_tokens"])
    big_enough = [d for d in compatible if d["tokens_train"] >= min_tokens]
    result: dict[str, Any] = {"experiments": [], "skipped": [], "weaknesses": [], "notes": []}
    incompatible = [d for d in all_approved if d["tokenizer_fingerprint"] != tok_fp]
    if incompatible:
        result["notes"].append(f"{len(incompatible)} approved dataset(s) use another tokenizer than the deployed "
                               "model; they need an explicit architecture migration and are not used")
    if not big_enough:
        result["notes"].append("no approved dataset for this model has enough training tokens "
                               f"(at least {min_tokens:,})")
        return result
    used = MEM.datasets_used_by_lineage(ctx, base["version"])
    weak = weaknesses(ctx, base["version"])
    result["weaknesses"] = weak
    weak_code = any(w["kind"] == "weak_coding" for w in weak)
    regressed_shas = {w["suite"].split(":", 1)[1] for w in weak if w["suite"].startswith("retention:")}

    def priority(d: dict) -> tuple:
        tags = json.loads(d["tags"] or "[]")
        new = d["sha256"] not in used
        replay = d["sha256"][:16] in regressed_shas
        code = weak_code and "code" in tags
        return (0 if new else 1, 0 if (replay or code) else 1, -d["tokens_train"], d["id"])

    ordered = sorted(big_enough, key=priority)
    tr = settings["training"]
    arch = architecture_key(base)
    lrs = _lr_ranking(ctx, arch, float(tr["lr"]))
    limit = int(settings["max_experiments_per_cycle"])
    for d in ordered:
        tags = json.loads(d["tags"] or "[]")
        if d["sha256"] not in used:
            why = "new approved data the current model has not been trained on"
        elif d["sha256"][:16] in regressed_shas:
            why = "replay: the current model got worse on this data than its predecessor"
        elif weak_code and "code" in tags:
            why = "coding is a measured weakness of the current model"
        else:
            why = "continued training on approved data"
        variants = [{"lr": lr, "steps": int(tr["steps"])} for lr in lrs]
        variants += [{"lr": lrs[0], "steps": int(tr["steps"]) * 2}, {"lr": lrs[0] * 0.25, "steps": int(tr["steps"])}]
        for v in variants:
            if len(result["experiments"]) >= limit:
                break
            cfg = {"method": "continued", "base_version": base["version"], "base_sha256": base["sha256"],
                   "architecture_key": arch, "dataset_id": d["id"], "dataset_sha256": d["sha256"],
                   "steps": v["steps"], "lr": v["lr"], "batch_size": int(tr["batch_size"]),
                   "seq_len": int(tr["seq_len"]), "weight_decay": float(tr["weight_decay"]),
                   "eval_interval": int(tr["eval_interval"]), "checkpoint_interval": int(tr["checkpoint_interval"]),
                   "seed": cycle_seed}
            h = MEM.config_hash({k: v2 for k, v2 in cfg.items() if k != "seed"} | {"seed": 0})
            prev = MEM.tried(ctx, h)
            if prev:
                result["skipped"].append({"config_hash": h, "reason": f"already tried in experiment #{prev['id']} "
                                                                      f"({prev['status']})"})
                continue
            if any(e["config_hash"] == h for e in result["experiments"]):
                continue
            result["experiments"].append({"config": cfg, "config_hash": h, "dataset_id": d["id"],
                                          "rationale": f"{why}; lr {v['lr']:.2e}, {v['steps']} steps"})
        if len(result["experiments"]) >= limit:
            break
    if not result["experiments"]:
        result["notes"].append("every planned configuration was already tried on this model and data; "
                               "waiting for new approved data or a new model")
    return result
