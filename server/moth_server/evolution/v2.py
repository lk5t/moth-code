"""Evolution 2.0 (0.5.3): curriculum mixtures, the lineage's development checkpoint, the research lab's
experiment variants, early stopping, Adaptive Parameter Growth and model versions.

* **Continuous improvement.** Experiments continue the stable model from its *development checkpoint*
  (full weights + AdamW state kept from the cycle that produced it); the very first cycle after an
  imported model starts from its weights. Never from random weights.
* **Curriculum mixtures.** When a dataset-library build with the lineage's tokenizer exists, experiments
  train on all capability domains at once with the curriculum's weights, tilted toward measured
  weaknesses — instead of one dataset at a time.
* **Research laboratory.** Each cycle tries a few controlled variants (learning rates ranked by past
  results, a weakness-tilted vs. a balanced mixture); configurations already tried are never repeated
  (config hash); a run whose held-out loss stops improving is stopped early.
* **Adaptive Parameter Growth.** When the evidence says the model has plateaued (and does not overfit),
  a growth experiment proposes a function-preserving expansion sized by that evidence and the compute
  budget; above the approval threshold it waits for the Owner. It is a candidate like any other: the
  stable model is never modified, and a rejected expansion is simply discarded.
* **Model versions.** A candidate that passes monitoring becomes the next model version (MOTH 0.1 →
  0.2 → 0.3 …), independent of application versions; each version is recorded once.
"""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any

from moth_server.context import Ctx
from moth_server.evolution import memory as MEM


# ---- data: the dataset library's mixture ---------------------------------------------------------------
def mixture_source(ctx: Ctx, base: dict) -> dict[str, Any] | None:
    from sqlalchemy import select

    from moth_server.db import library_builds
    from moth_server.evolution import datasets as DS

    fp = base["info"].get("tokenizer_fingerprint")
    rows = ctx.db.all(select(library_builds).where(library_builds.c.status == "ready")
                      .order_by(library_builds.c.id.desc()))
    for b in rows:
        if b["tokenizer_fingerprint"] != fp or not b["path"]:
            continue
        mix_file = Path(b["path"]) / "tokens" / "mixture.json"
        if not mix_file.exists():
            continue
        mix = json.loads(mix_file.read_text())
        anchor = next((d for d in DS.approved(ctx, fp) if f"(build {b['id']})" in d["name"]), None)
        if anchor is None:
            continue
        source = {"build_id": b["id"], "path": str(mix_file.parent), "build_sha256": b["content_sha256"],
                "dataset_id": anchor["id"],
                "domain_tokens": {d: v["tokens"]["train"] for d, v in mix["domains"].items()}}
        return _replay_source(ctx, base, source, rows, DS.approved(ctx, fp))
    return None


def _replay_source(ctx, base, source, builds, approved):
    """Compose current data with bounded historical samples; never alter original builds."""
    import numpy as np
    from moth_server.evolution.datasets import _sha

    used = MEM.datasets_used_by_lineage(ctx, base["version"])
    allowed = {d["sha256"]: d["id"] for d in approved}
    selected = [b for b in builds if b["id"] == source["build_id"] or b["content_sha256"] in used]
    selected.sort(key=lambda b: b["id"] != source["build_id"])
    parts, shas, ids = {}, [], set()
    for b in selected:
        if b["content_sha256"] in shas:
            continue
        root = Path(b["path"]) / "tokens"
        if not (root / "mixture.json").exists():
            continue
        mix = json.loads((root / "mixture.json").read_text())
        if mix["tokenizer_fingerprint"] != base["info"]["tokenizer_fingerprint"]:
            continue
        added = False
        for domain, info in mix["domains"].items():
            path = (root / info["dir"]).resolve()
            digest = _sha(path / "train.bin")
            if digest in allowed:
                parts.setdefault(domain, []).append((path, b["id"] == source["build_id"]))
                ids.add(allowed[digest])
                added = True
        if added:
            shas.append(b["content_sha256"])
    if len(shas) == 1 and set(parts) == set(source["domain_tokens"]):
        return source
    digest = MEM.config_hash({"builds": shas, "datasets": sorted(ids), "replay_tokens": 65536})
    dest = Path(ctx.settings.data_dir) / "evolution" / "mixtures" / digest
    if not (dest / "mixture.json").exists():
        dest.mkdir(parents=True, exist_ok=True)
        original = json.loads((Path(source["path"]) / "mixture.json").read_text())
        mixture = {**original, "build_sha256": digest, "domains": {}}
        for domain, paths in parts.items():
            target = dest / domain
            target.mkdir(exist_ok=True)
            meta = json.loads((paths[0][0] / "meta.json").read_text())
            sources = set()
            counts = {}
            for split in ("train", "val"):
                count = 0
                with open(target / f"{split}.bin", "wb") as toks, open(target / f"{split}.mask", "wb") as masks:
                    for path, current in paths:
                        old_meta = json.loads((path / "meta.json").read_text())
                        sources.update(json.dumps(s, sort_keys=True) for s in old_meta.get("sources", []))
                        tokens = np.memmap(path / f"{split}.bin", dtype=old_meta["dtype"], mode="r")
                        mask = np.memmap(path / f"{split}.mask", dtype=np.uint8, mode="r")
                        n = len(tokens) if current else min(len(tokens), 65536)
                        np.asarray(tokens[:n], dtype=meta["dtype"]).tofile(toks)
                        np.asarray(mask[:n], dtype=np.uint8).tofile(masks)
                        count += n
                counts[split] = count
            (target / "meta.json").write_text(json.dumps({**meta, "tokens": counts,
                                                        "sources": [json.loads(s) for s in sorted(sources)]}))
            mixture["domains"][domain] = {"dir": domain, "tokens": counts}
        tmp = dest / "mixture.json.tmp"
        tmp.write_text(json.dumps(mixture))
        tmp.replace(dest / "mixture.json")
    mixture = json.loads((dest / "mixture.json").read_text())
    return {**source, "path": str(dest), "build_sha256": digest, "build_shas": shas, "dataset_ids": sorted(ids),
            "domain_tokens": {d: v["tokens"]["train"] for d, v in mixture["domains"].items()}}


def write_mixture_shard(mix_path: str, weights: dict[str, float], n_tokens: int, seed: int, dest: Path) -> str:
    """A worker's training shard (uint32 tokens) sampled from the mixture's domains by weight."""
    import hashlib

    import numpy as np

    rng = np.random.default_rng(seed)
    mix = json.loads((Path(mix_path) / "mixture.json").read_text())
    parts = []
    names = [d for d in weights if d in mix["domains"] and weights[d] > 0]
    probs = np.array([weights[d] for d in names], dtype=np.float64)
    probs /= probs.sum()
    window = 512
    per = {d: int(round(n_tokens * p)) for d, p in zip(names, probs)}
    for d in names:
        meta = json.loads((Path(mix_path) / mix["domains"][d]["dir"] / "meta.json").read_text())
        toks = np.memmap(Path(mix_path) / mix["domains"][d]["dir"] / "train.bin", dtype=np.dtype(meta["dtype"]), mode="r")
        if len(toks) <= window + 1:
            continue
        k = max(1, per[d] // window)
        for s in rng.integers(0, len(toks) - window - 1, size=k):
            parts.append(np.asarray(toks[s:s + window], dtype=np.uint32))
    rng.shuffle(parts)
    out = np.concatenate(parts) if parts else np.zeros(0, dtype=np.uint32)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.tofile(dest)
    return hashlib.sha256(dest.read_bytes()).hexdigest()


# ---- planning ---------------------------------------------------------------------------------------------
def growth_evidence(ctx: Ctx, base: dict) -> dict[str, Any]:
    """Measured improvements of the last completed cycles on this lineage, and the stable model's losses."""
    imps: list[float] = []
    lineage_versions = {base["version"]} | {a["version"] for a in MEM.ancestors(ctx, base["version"])}
    for c in reversed(MEM.cycles(ctx, 30)):  # oldest first
        if c.get("base_version") not in lineage_versions:
            continue
        if c["status"] in ("completed", "rejected") and c.get("result"):
            best = None
            for e in MEM.experiments(ctx, c["id"]):
                v = (e.get("metrics") or {}).get("primary_improvement")
                if v is not None:
                    best = v if best is None else max(best, v)
            if best is not None:
                imps.append(float(best))
    tr = (base["info"].get("training") or {})
    return {"recent_improvements": imps, "train_loss": tr.get("train_loss"),
            "val_loss": tr.get("best_val") if tr.get("best_val") is not None else tr.get("val_loss")}


def plan(ctx: Ctx, base: dict, settings: dict, cycle_seed: int) -> dict[str, Any]:
    """Experiments on the curriculum mixture (empty when no compatible library build exists)."""
    from moth.model.config import MothConfig
    from moth.model.growth import plan_growth

    from moth_server.evolution.planner import _lr_ranking, architecture_key
    from moth_server.intelligence import curriculum, feedback, weakness

    out: dict[str, Any] = {"experiments": [], "skipped": [], "weaknesses": [], "notes": [], "growth": None}
    if not settings.get("use_curriculum", True):
        return out
    src = mixture_source(ctx, base)
    if src is None:
        out["notes"].append("no dataset-library build uses this model's tokenizer: build one in Owner Dashboard → "
                            "Intelligence to train on the curriculum")
        return out
    parent = (MEM.ancestors(ctx, base["version"])[1:2] or [{}])[0].get("version")
    analysis = weakness.analyse(ctx, base["version"], parent, feedback.summary(ctx))
    out["weaknesses"] = analysis["ranked"]
    tr = settings["training"]
    budget = int(tr["steps"]) * int(tr["batch_size"]) * int(tr["seq_len"])
    tilted = curriculum.plan(ctx, budget, analysis, tokens=src["domain_tokens"])
    balanced = curriculum.plan(ctx, budget, None, tokens=src["domain_tokens"])
    arch = architecture_key(base)
    lrs = _lr_ranking(ctx, arch, float(tr["lr"]))
    dev = (base["info"].get("dev_checkpoint") or {})
    variants = [("weakness-tilted curriculum", tilted, lrs[0]), ("weakness-tilted curriculum", tilted, lrs[1]),
                ("balanced curriculum", balanced, lrs[0])]
    for why, mix, lr in variants:
        if not mix.get("weights"):
            continue
        cfg = _config(base, arch, src, mix, lr, int(tr["steps"]), settings, cycle_seed)
        _add(ctx, out, cfg, src, f"{why} (stage {mix['stage']}); lr {lr:.2e}, {cfg['steps']} steps"
             + ("; continues the development checkpoint" if dev else ""), int(settings["max_experiments_per_cycle"]))
    g = settings.get("growth") or {}
    if g.get("enabled", True):
        cfg_model = MothConfig.from_dict(json.loads((Path(base["path"]) / "config.json").read_text()))
        decision = plan_growth(cfg_model, growth_evidence(ctx, base) | {"plateau_threshold": float(
            g.get("plateau_threshold", 0.01))}, {"max_params": int(g.get("max_params", 0)) or None,
                                                  "max_ratio": float(g.get("max_ratio", 1.5))},
            approval_ratio=float(g.get("approval_ratio", 1.25)))
        out["growth"] = decision
        if decision["grow"]:
            cfg = _config(base, arch, src, tilted if tilted.get("weights") else balanced, lrs[0],
                          int(tr["steps"]) * int(g.get("steps_multiplier", 2)), settings, cycle_seed)
            cfg["method"] = "expansion"
            cfg["grow"] = {"add_layers": decision["add_layers"], "ffn_hidden": decision["ffn_hidden"],
                           "params_before": decision["params_before"], "params_after": decision["params_after"],
                           "ratio": decision["ratio"]}
            cfg["requires_approval"] = bool(decision["requires_approval"])
            _add(ctx, out, cfg, src, "Adaptive Parameter Growth: " + decision["reason"]
                 + (" — needs the Owner's approval" if decision["requires_approval"] else ""), 99)
        else:
            out["notes"].append("parameter growth not proposed: " + decision["reason"])
    return out


def _config(base, arch, src, mix, lr, steps, settings, seed) -> dict[str, Any]:
    tr = settings["training"]
    return {"method": "continued", "base_version": base["version"], "base_sha256": base["sha256"],
            "architecture_key": arch, "dataset_id": src["dataset_id"], "dataset_sha256": src["build_sha256"],
            "mixture": {"build_id": src["build_id"], "path": src["path"], "build_sha256": src["build_sha256"],
                        "weights": {d: round(w, 3) for d, w in mix["weights"].items()}, "stage": mix["stage"],
                        **({"build_shas": src["build_shas"], "dataset_ids": src["dataset_ids"]} if src.get("build_shas") else {})},
            "steps": steps, "lr": lr, "batch_size": int(tr["batch_size"]), "seq_len": int(tr["seq_len"]),
            "batch_autotune": bool(tr.get("batch_autotune", True)),
            "weight_decay": float(tr["weight_decay"]), "eval_interval": int(tr["eval_interval"]),
            "checkpoint_interval": int(tr["checkpoint_interval"]), "seed": seed}


def _add(ctx: Ctx, out: dict, cfg: dict, src: dict, rationale: str, limit: int) -> None:
    if len([e for e in out["experiments"] if e["config"].get("method") != "expansion"]) >= limit \
            and cfg.get("method") != "expansion":
        return
    h = MEM.config_hash({k: v for k, v in cfg.items() if k != "seed"} | {"seed": 0})
    prev = MEM.tried(ctx, h)
    if prev:
        out["skipped"].append({"config_hash": h, "reason": f"already tried in experiment #{prev['id']} ({prev['status']})"})
        return
    if any(e["config_hash"] == h for e in out["experiments"]):
        return
    out["experiments"].append({"config": cfg, "config_hash": h, "dataset_id": src["dataset_id"], "rationale": rationale})


# ---- training: early stopping ------------------------------------------------------------------------------
def val_history(events_path: Path) -> list[float]:
    out = []
    if not events_path.exists():
        return out
    for line in events_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("kind") == "metrics" and e.get("split") == "val" and e.get("loss") is not None:
            out.append(float(e["loss"]))
    return out


def early_stop_reason(history: list[float], settings: dict) -> str | None:
    """Why a run should stop now (wasted compute), or None. Uses the run's own held-out losses."""
    es = settings.get("early_stopping") or {}
    if not es.get("enabled", True):
        return None
    min_evals, patience = int(es.get("min_evals", 3)), int(es.get("patience", 3))
    if len(history) < min_evals:
        return None
    if any(not math.isfinite(x) for x in history):
        return "held-out loss became non-finite (diverged)"
    best_i = min(range(len(history)), key=history.__getitem__)
    if history[-1] > history[0] * 1.05 and len(history) >= min_evals:
        return f"held-out loss rose from {history[0]:.3f} to {history[-1]:.3f}"
    if len(history) - 1 - best_i >= patience:
        return f"no held-out improvement for {patience} evaluations (best {history[best_i]:.3f})"
    return None


# ---- evaluation: improvement of a mixture run -------------------------------------------------------------
def mixture_improvement(cand_scores: dict, base_scores: dict, weights: dict[str, float]) -> float | None:
    """Weighted mean relative improvement of the capability held-out losses (lower is better)."""
    total, wsum = 0.0, 0.0
    for d, w in weights.items():
        c = (cand_scores.get(f"capability:holdout:{d}") or {})
        b = (base_scores.get(f"capability:holdout:{d}") or {})
        if c.get("ok") and b.get("ok") and b.get("value"):
            total += w * (float(b["value"]) - float(c["value"])) / abs(float(b["value"]))
            wsum += w
    return total / wsum if wsum else None


# ---- the lineage's development checkpoint ----------------------------------------------------------------------
def store_dev_checkpoint(ctx: Ctx, version: int, src: str, sha: str) -> dict[str, Any] | None:
    from moth.training.checkpoint import file_sha256

    p = Path(src)
    if not p.exists() or file_sha256(p) != sha:
        return None
    dest = Path(ctx.settings.data_dir) / "lineage" / "dev" / f"v{version:05d}.pt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dest)
    if file_sha256(dest) != sha:
        dest.unlink(missing_ok=True)
        return None
    return {"path": str(dest), "sha256": sha}


# ---- model versions ---------------------------------------------------------------------------------------
def _parse(v: str | None) -> tuple[int, int] | None:
    try:
        a, b = str(v).split(".")[:2]
        return int(a), int(b)
    except (ValueError, AttributeError):
        return None


def assign_model_version(ctx: Ctx, version: int) -> str | None:
    """Give a newly stable model the next MOTH model version of its lineage (once)."""
    from moth_server import models as M

    rel = M.release(ctx, version)
    if not rel or rel["info"].get("model_version"):
        return rel["info"].get("model_version") if rel else None
    used = [_parse((r["info"] or {}).get("model_version")) for r in M.list_releases(ctx)
            if r['status'] == 'deployed' or r.get('previously_deployed')]
    used = [u for u in used if u]
    anc = MEM.ancestors(ctx, version)
    parent_mv = None
    for a in anc[1:]:
        pr = M.release(ctx, a["version"])
        if pr and _parse(pr["info"].get("model_version")):
            parent_mv = _parse(pr["info"]["model_version"])
            break
    major = parent_mv[0] if parent_mv else 0
    minor = max([u[1] for u in used if u[0] == major] + [parent_mv[1] if parent_mv else 0]) + 1
    mv = f"{major}.{minor:02d}"
    info = {**rel["info"], "model_version": mv, "display_name": f"MOTH {mv}",
            "family": rel["info"].get("family") or "MOTH"}
    M._set(ctx, version, None, info=json.dumps(info))
    MEM.event(ctx, "model.version", f"Release v{version} is MOTH {mv}", model_version=mv)
    return mv
