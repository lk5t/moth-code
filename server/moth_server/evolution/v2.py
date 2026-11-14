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
def mixture_source(ctx: Ctx, base: dict, fingerprint: str | None = None) -> dict[str, Any] | None:
    """The curriculum data for ``base``'s tokenizer (or, for a successor, for ``fingerprint``'s)."""
    from sqlalchemy import select

    from moth_server.db import library_builds
    from moth_server.evolution import datasets as DS

    fp = fingerprint or base["info"].get("tokenizer_fingerprint")
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
        if fingerprint:  # a successor's own build: nothing earlier was trained with its tokenizer
            return source
        return _replay_source(ctx, base, source, rows, DS.approved(ctx, fp))
    return None


REPLAY_VERSION = 2
REPLAY_SHARE = 0.10
REPLAY_MIN = 65_536
REPLAY_MAX = 5_000_000


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
    digest = MEM.config_hash({"builds": shas, "datasets": sorted(ids), "replay": REPLAY_VERSION})
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
                        # 1.0 "never forget": each older build contributes up to 10 % of the current
                        # build's tokens for that domain (at least 64k, at most 5M), not a fixed 64k
                        quota = min(REPLAY_MAX, max(REPLAY_MIN, int(REPLAY_SHARE * int(
                            (source.get("domain_tokens") or {}).get(domain) or 0))))
                        n = len(tokens) if current else min(len(tokens), quota)
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


def write_mixture_shard(mix_path: str, weights: dict[str, float], n_tokens: int, seed: int, dest: Path,
                        mask_dest: Path | None = None) -> str:
    """A worker's training shard (uint32 tokens) sampled from the mixture's domains by weight.

    With ``mask_dest``, the matching uint8 loss mask (1 = learn this token; conversation data learns
    only the assistant's replies) is written alongside — only when some token is masked out."""
    import hashlib

    import numpy as np

    rng = np.random.default_rng(seed)
    mix = json.loads((Path(mix_path) / "mixture.json").read_text())
    parts, mparts = [], []
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
        mpath = Path(mix_path) / mix["domains"][d]["dir"] / "train.mask"
        mask = np.memmap(mpath, dtype=np.uint8, mode="r") if mask_dest is not None and mpath.exists() else None
        k = max(1, per[d] // window)
        for s in rng.integers(0, len(toks) - window - 1, size=k):
            parts.append(np.asarray(toks[s:s + window], dtype=np.uint32))
            mparts.append(np.asarray(mask[s:s + window], dtype=np.uint8) if mask is not None
                          else np.ones(window, dtype=np.uint8))
    order = rng.permutation(len(parts))  # tokens and masks stay aligned
    parts = [parts[i] for i in order]
    mparts = [mparts[i] for i in order]
    out = np.concatenate(parts) if parts else np.zeros(0, dtype=np.uint32)
    dest.parent.mkdir(parents=True, exist_ok=True)
    out.tofile(dest)
    if mask_dest is not None:
        m = np.concatenate(mparts) if mparts else np.zeros(0, dtype=np.uint8)
        if m.size and not m.all():
            m.tofile(mask_dest)
        elif mask_dest.exists():
            mask_dest.unlink()
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
    from moth_server.evolution import autopilot as _AP

    tilted, data_note = _AP.apply_data_effects(ctx, tilted)  # measured: data that helped gets more weight
    if data_note:
        out["notes"].append(data_note)
        out["data_note"] = data_note
    balanced = curriculum.plan(ctx, budget, None, tokens=src["domain_tokens"])
    arch = architecture_key(base)
    lrs = _lr_ranking(ctx, arch, float(tr["lr"]))
    dev = (base["info"].get("dev_checkpoint") or {})
    variants = [("weakness-tilted curriculum", tilted, lrs[0], "weakness"), ("weakness-tilted curriculum", tilted, lrs[1], "weakness"),
                ("balanced curriculum", balanced, lrs[0], "balanced")]
    # Evolution memory: strategies that produced accepted improvements on this lineage go first.
    from moth_server.evolution import autopilot as AP

    ranked, note = AP.rank_strategies(ctx, [v[3] for v in variants])
    if note:
        out["notes"].append(note)
        out["strategy_note"] = note
    order = {k: i for i, k in enumerate(ranked)}
    variants.sort(key=lambda v: order.get(v[3], 99))
    suspended, why_not = AP.suspended_strategies(ctx, [v[3] for v in variants])
    if suspended:  # 0.7.2: repeated failures are not repeated again while something else works
        variants = [v for v in variants if v[3] not in suspended]
        out["notes"].append(why_not)
        out["suspended_strategies"] = sorted(suspended)
    for why, mix, lr, strategy in variants:
        if not mix.get("weights"):
            continue
        cfg = _config(base, arch, src, mix, lr, int(tr["steps"]), settings, cycle_seed)
        cfg["strategy"] = strategy
        _add(ctx, out, cfg, src, f"{why} (stage {mix['stage']}); lr {lr:.2e}, {cfg['steps']} steps"
             + ("; continues the development checkpoint" if dev else ""), int(settings["max_experiments_per_cycle"]))
    if not [e for e in out["experiments"] if e["config"].get("method") != "expansion"]:
        _explore(ctx, out, base, arch, src, tilted, balanced, lrs, settings, cycle_seed)
    g = settings.get("growth") or {}
    # 0.6.3 capability-based growth: the decision comes from measured capabilities, training progress
    # and resources (see capacity.py); the engine passes the assessment it already made this cycle.
    decision = settings.get("_capacity")
    if decision is None:
        from moth_server.evolution import capacity as CAP

        decision = CAP.assess(ctx, base, settings)
    out["growth"] = decision
    if decision.get("action") == "rebirth" and decision.get("rebirth"):
        _plan_rebirth(ctx, out, base, arch, src, tilted if tilted.get("weights") else balanced, settings,
                      cycle_seed, decision)
    if g.get("enabled", True):
        cfg_model = MothConfig.from_dict(json.loads((Path(base["path"]) / "config.json").read_text()))
        if decision["grow"]:
            cfg = _config(base, arch, src, tilted if tilted.get("weights") else balanced, lrs[0],
                          int(tr["steps"]) * int(g.get("steps_multiplier", 2)), settings, cycle_seed)
            cfg["method"] = "expansion"
            cfg["grow"] = {"add_layers": decision["add_layers"], "ffn_hidden": decision["ffn_hidden"],
                           "params_before": decision["params_before"], "params_after": decision["params_after"],
                           "ratio": decision["ratio"], "target_capabilities": decision.get("target_capabilities") or [],
                           "estimate": decision.get("estimate")}
            cfg["requires_approval"] = bool(decision["requires_approval"])
            _add(ctx, out, cfg, src, "Adaptive Parameter Growth: " + decision["reason"]
                 + (" — needs the Owner's approval" if decision["requires_approval"] else ""), 99)
        else:
            out["notes"].append("parameter growth not proposed: " + decision["reason"])
        req = ctx.db.get_config("growth_request", None)
        if req and not decision["grow"]:
            from moth.model.growth import growth_options

            opt = next((o for o in growth_options(cfg_model, 2.0) if o["add_layers"] == req.get("add_layers")
                        and o["ffn_hidden"] == req.get("ffn_hidden")), None)
            max_params = int(g.get("max_params", 0)) or None
            if opt is None or (max_params and opt["params"] > max_params):
                out["notes"].append("the requested growth does not fit this model or the parameter budget")
            else:
                cfg = _config(base, arch, src, tilted if tilted.get("weights") else balanced, lrs[0],
                              int(tr["steps"]) * int(g.get("steps_multiplier", 2)), settings, cycle_seed)
                cfg["method"] = "expansion"
                cfg["grow"] = {"add_layers": opt["add_layers"], "ffn_hidden": opt["ffn_hidden"],
                               "params_before": cfg_model.num_params(), "params_after": opt["params"],
                               "ratio": opt["ratio"], "requested_by": req.get("requested_by")}
                cfg["requires_approval"] = False  # the Owner asked for exactly this candidate
                cfg["approved_by"] = req.get("requested_by")
                _add(ctx, out, cfg, src, f"Owner-requested growth experiment ({cfg_model.num_params():,} → "
                     f"{opt['params']:,} parameters). It is trained as a separate candidate and must pass every "
                     "gate against the deployed model; otherwise it is discarded.", 99)
    return out


REBIRTH_LR = 1e-3          # a fresh model learns fastest with a larger rate than continued training
REBIRTH_MAX_HOURS = 10.0   # one successor run at most (it is checkpointed and resumable like any run)
REBIRTH_MIN_STEPS = 500


def _plan_rebirth(ctx: Ctx, out: dict, base: dict, arch: str, src: dict, mix: dict, settings: dict, seed: int,
                  decision: dict) -> None:
    """0.9.2: a right-sized successor, trained from scratch (see capacity.right_size).

    0.10.0: its speed is the measured speed of its own shape; it reads a 1024-token context; a byte-level
    lineage's successor trains on data prepared with its new BPE tokenizer; and it can be split across
    MOTH Cloud and the workers (shared rounds) instead of training on MOTH Cloud alone."""
    rs = decision["rebirth"]
    tr = settings["training"]
    tok = rs.get("tokenizer")
    if tok:
        own = mixture_source(ctx, base, tok["fingerprint"])
        if own is None:
            out["notes"].append("the successor's tokenizer data is not usable yet; the successor waits for it")
            return
        src = own
        from moth_server.intelligence import curriculum

        mix = {**mix, "weights": {d: w for d, w in mix["weights"].items() if d in own["domain_tokens"]}
               or curriculum.plan(ctx, 1, None, tokens=own["domain_tokens"])["weights"]}
    seq = int(rs.get("seq_len") or tr["seq_len"])
    # the same tokens per step as other runs: a longer context uses a smaller batch
    batch = max(1, int(tr["batch_size"]) * int(tr["seq_len"]) // seq)
    tokens_per_step = batch * seq
    speed = float(rs.get("successor_tokens_per_second")
                  or float(rs["tokens_per_second_now"]) * rs["params_before"] / max(1, rs["params_after"]))
    # a successor that did not beat the current model is retried once with twice the training
    retry = sum(1 for e in MEM.experiments(ctx, limit=200) if (e.get("config") or {}).get("rebirth")
                and int(e["config"]["rebirth"].get("params_after") or 0) == rs["params_after"]
                and e["status"] in ("rejected", "failed"))
    hours = min(REBIRTH_MAX_HOURS * (2 ** retry), float(settings["budget"]["max_cycle_hours"]) * 0.9)
    tokens = min(int(rs["tokens_target"]) * (2 ** retry), int(speed * hours * 3600))
    steps = max(REBIRTH_MIN_STEPS, tokens // max(1, tokens_per_step))
    cfg = _config(base, arch, src, mix, REBIRTH_LR, steps, settings, seed)
    cfg.update(method="from_scratch", strategy="rebirth", batch_size=batch, seq_len=seq, no_single_worker=True,
               rebirth={"architecture": rs["architecture"], "params_before": rs["params_before"], "attempt": retry + 1,
                        "params_after": rs["params_after"], "optimal_params": rs["optimal_params"],
                        "speed_basis": rs.get("speed_basis", "estimated"),
                        **({"tokenizer": tok} if tok else {}),
                        "planned_tokens": steps * tokens_per_step,
                        "planned_hours": round(steps * tokens_per_step / max(1.0, speed) / 3600, 1)})
    cfg["eval_interval"] = max(int(cfg["eval_interval"]), steps // 40)
    cfg["checkpoint_interval"] = max(int(cfg["checkpoint_interval"]), steps // 40)
    sched = chat_schedule(cfg["mixture"]["weights"])
    if sched:  # 0.10.1: chat warm-up first, a chat-heavy finish last
        cfg["mixture_schedule"] = sched
    a = rs["architecture"]
    _add(ctx, out, cfg, src, f"Right-sized successor: {rs['params_before']:,} → {rs['params_after']:,} parameters, "
         f"{a.get('max_seq_len', 0):,}-token context{', new BPE tokenizer' if tok else ''}, trained from scratch for "
         f"{steps:,} steps (about {cfg['rebirth']['planned_hours']} h at the measured speed; shared with the workers "
         "when they are online). It replaces the current model only if it passes every gate.", 99)


CHAT_WARMUP = 0.08   # the first 8 % of a successor's steps: conversations only
CHAT_FINISH = 0.85   # the last 15 %: mostly conversations (70 %), the rest as planned


def chat_schedule(weights: dict[str, float]) -> list[dict] | None:
    """0.10.1: a successor starts from nothing. It first learns the shape of a conversation (who speaks,
    when a reply ends), then the whole curriculum, and ends on mostly conversation so its replies finish
    cleanly — the check the first successor failed. None when the mixture has no conversation data."""
    if not weights.get("conversation"):
        return None
    rest = {d: w for d, w in weights.items() if d != "conversation"}
    total = sum(rest.values()) or 1.0
    finish = {"conversation": 0.7, **{d: round(0.3 * w / total, 4) for d, w in rest.items()}}
    return [{"until": CHAT_WARMUP, "weights": {"conversation": 1.0}, "phase": "chat warm-up"},
            {"until": CHAT_FINISH, "weights": dict(weights), "phase": "curriculum"},  # [1:] = regular runs
            {"until": 1.01, "weights": finish, "phase": "chat finish"}]


def blended_weights(weights: dict[str, float], schedule: list[dict] | None) -> dict[str, float]:
    """The average mixture over a schedule (shared rounds sample their shards once)."""
    if not schedule:
        return weights
    out: dict[str, float] = {}
    start = 0.0
    for ph in schedule:
        span = min(1.0, float(ph["until"])) - start
        for d, w in ph["weights"].items():
            out[d] = out.get(d, 0.0) + span * float(w)
        start = min(1.0, float(ph["until"]))
    return out


# 0.8.1: Evolution never runs out of work. Identical configurations are never repeated, so once every
# planned variant was tried on the current model, each further cycle explores a new one: a learning rate
# further from the best known one, longer training, a fresh data sample (the exploration number is part
# of the configuration) and the other curriculum; the data library is also asked to grow. Every candidate
# still passes the same gates, so exploration can never promote a worse model.
EXPLORE_LR = (0.5, 2.0, 0.25, 4.0, 0.7, 1.4, 0.125, 8.0)
EXPLORE_STEPS = (1, 2, 1, 3)


def _explore(ctx: Ctx, out: dict, base: dict, arch: str, src: dict, tilted: dict, balanced: dict,
             lrs: list[float], settings: dict, seed: int) -> None:
    key = f"evolution_explore:{base['version']}"
    n = int(ctx.db.get_config(key, 0) or 0)
    tr = settings["training"]
    limit = int(settings["max_experiments_per_cycle"])
    for i in range(n, n + 64):  # skip anything tried before, never loop forever
        if len(out["experiments"]) >= limit:
            break
        f = EXPLORE_LR[i % len(EXPLORE_LR)]
        lr = min(1e-2, max(1e-6, lrs[0] * f))
        mix = (tilted, balanced)[(i // len(EXPLORE_LR)) % 2]
        if not mix.get("weights"):
            mix = balanced if mix is tilted else tilted
        steps = int(tr["steps"]) * EXPLORE_STEPS[(i // 2) % len(EXPLORE_STEPS)]
        cfg = _config(base, arch, src, mix, lr, steps, settings, seed + i)
        cfg["strategy"] = "weakness" if mix is tilted else "balanced"
        cfg["exploration"] = i + 1
        before = len(out["experiments"])
        _add(ctx, out, cfg, src, f"exploration #{i + 1}: every earlier configuration on this model was tried, so "
             f"MOTH tries lr {lr:.2e} (×{f:g} of the best known), {steps} steps, the "
             f"{'weakness-tilted' if mix is tilted else 'balanced'} curriculum and a fresh data sample", limit)
        if len(out["experiments"]) > before:
            ctx.db.set_config(key, i + 1)
    if not n:  # the first time this model runs out of ideas: more data is the strongest new lever
        try:
            from moth_server.evolution import autopilot as AP

            AP.scale_data(ctx, force=True, reason="every planned configuration was tried on this model")
        except Exception:  # noqa: BLE001 — exploration continues without it
            pass
    if out["experiments"]:
        out["notes"].append("Every planned configuration was already tried on this model; exploring new learning "
                            "rates, longer training and fresh data samples instead of waiting.")


def _config(base, arch, src, mix, lr, steps, settings, seed) -> dict[str, Any]:
    tr = settings["training"]
    cfg = _base_config(base, arch, src, mix, lr, steps, settings, seed)
    # 1.0: every run ends on mostly conversation (the last 15 %), so replies finish cleanly — the check that
    # rejected both v124 and v125. Successors also get the chat warm-up (see _plan_rebirth).
    sched = chat_schedule(cfg["mixture"]["weights"])
    if sched:
        cfg["mixture_schedule"] = sched[1:]
    return cfg


def _base_config(base, arch, src, mix, lr, steps, settings, seed) -> dict[str, Any]:
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
    # divergence: the last two measurements are both clearly worse than the start (one noisy reading is not)
    if len(history) >= 2 and min(history[-2:]) > history[0] * 1.05:
        return f"held-out loss rose from {history[0]:.3f} to {history[-1]:.3f}"
    # 0.8.3: a plateau no longer ends a run (it stopped almost every run at ~10 % of its steps, so none
    # completed). Runs train all planned steps and the promotion gates decide. Owners can turn the
    # plateau rule back on with early_stopping.plateau.
    if es.get("plateau", False) and len(history) - 1 - best_i >= patience:
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
    """A verified upgrade (deployed and passed monitoring) is the next MOTH version: 0.0.1 → 0.0.2 → …
    (0.7.0, identity.py). Capability milestones are still measured and recorded with the version."""
    from moth_server import models as M
    from moth_server.evolution import identity, milestones
    rel = M.release(ctx, version)
    if not rel or rel['info'].get('model_version'):
        return rel['info'].get('model_version') if rel else None
    ancestors = [M.release(ctx, a['version']) for a in MEM.ancestors(ctx, version)[1:]]
    lineage = rel['info'].get('lineage_id')
    parent = next((r for r in ancestors if r and r['info'].get('model_version')
                   and (not lineage or not r['info'].get('lineage_id') or r['info']['lineage_id'] == lineage)), None)
    mv = identity.next_version(parent['info']['model_version']) if parent else identity.FIRST  # a new lineage: 0.0.1
    evidence = milestones.assess(ctx, rel, parent) if parent else {
        'eligible': False, 'reasons': ['Initial public identity; no earned improvement claimed']}
    info = {**rel['info'], 'model_version': mv, 'display_name': identity.display(mv),
            'family': rel['info'].get('family') or 'MOTH', 'milestone': evidence}
    M._set(ctx, version, None, info=json.dumps(info))
    MEM.event(ctx, 'model.milestone' if evidence['eligible'] else 'model.revision',
              f'Release v{version} is MOTH {mv}' + (' — a capability milestone' if evidence['eligible'] else ''),
              model_version=mv)
    return mv
