"""Capability-based growth: decide from measured intelligence, not only from training loss.

Every cycle the planner asks :func:`assess` what limits MOTH now. The answer is built only from
recorded measurements:

* **Capabilities** — the held-out benchmark reports of the deployed version and its ancestors
  (arithmetic: GSM8K, reasoning: ARC-Easy, coding: MBPP executed, instruction following: well-formed
  replies, and held-out loss on language / conversation / knowledge text). A capability is *limited*
  when its score is below the next target for a small model (``weakness.TARGETS``) and *stalled* when
  over the last ``capability_window`` measured versions it did not improve by more than sampling noise
  (two standard errors). Loss-based domains have no absolute target: they are only judged by trend.
* **Training progress** — the held-out loss improvement of recent cycles, the train/validation gap and
  how many tokens the lineage has trained on per parameter (measured parameters, 0.6.3).

Possible causes are checked in order, each with its evidence: overfitting (data), too little training
for the model's size (tokens per parameter), replies that never end (generation/format, not size),
too little data for a stalled capability's domains (data), and the tokenizer (reported only — changing
it needs a new Genesis). Only when none of these explains the limitation — the model has had enough
training for its size and a capability stays limited while its data exists, or loss itself has
plateaued — is a capacity limit the conclusion, and a larger candidate is proposed. Even then it is
subject to the parameter ceiling, the step-size limit, memory that some authorized compute actually
has, a cooldown after a rejected growth candidate and a cap on failed attempts.

The decision is one of ``continue_training``, ``improve_data``, ``adjust_training``,
``foundation_training``, ``grow`` — always with a plain-language headline and the numbers behind it.
A growth candidate is a separate experiment that must beat the current model on the same benchmarks
(including the capability that motivated it) before it can be promoted; otherwise it is discarded.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from moth_server.context import Ctx
from moth_server.evolution import memory as MEM

# capability → (display name, Data Factory domains that train it)
CAPS: dict[str, tuple[str, list[str]]] = {
    "math": ("Arithmetic", ["math"]),
    "reasoning": ("Reasoning", ["reasoning", "knowledge"]),
    "code": ("Coding", ["code"]),
    "instruction": ("Instruction following", ["conversation", "writing"]),
    "holdout_language": ("Language understanding", ["language"]),
    "holdout_conversation": ("Coherent conversation", ["conversation"]),
    "holdout_knowledge": ("Knowledge", ["knowledge"]),
}
DEFAULTS = {"min_tokens_per_param": 20.0, "foundation_tokens_per_param": 2.0, "capability_window": 3,
            "cooldown_cycles": 3, "max_failed_attempts": 3, "min_domain_share": 0.03}
ACTIONS = ("continue_training", "improve_data", "adjust_training", "foundation_training", "grow", "rebirth")

# 0.9.2: right-sizing. Growth adds layers or FFN width step by step (≤ 1.5× each, behind several gates):
# from a 100k-parameter seed it would take weeks to reach a size that can write sentences, and it can never
# widen the model. When the model is far smaller than what the measured compute can train properly in a
# day, MOTH instead trains a properly sized *successor* from scratch: same tokenizer (so held-out losses
# stay comparable), same curriculum, same promotion gates — it replaces the current model only if it is
# measurably better. Shapes grow in width and depth together, like the presets.
SHAPES = ((128, 4, 4, 384), (192, 6, 6, 576), (256, 6, 4, 768), (320, 8, 5, 960), (384, 8, 6, 1152),
          (512, 8, 8, 1536), (512, 12, 8, 1536), (640, 12, 10, 1920), (768, 12, 12, 2304))
REBIRTH_FACTOR = 4.0          # (before 2.1) a successor was planned only when the right size was ≥ 4× larger
# 2.1 gradual growth: MOTH grows in small steps (100K → 300K → 900K …), each a few hours at most and starting
# from the previous model's weights, instead of one huge jump trained from scratch for days.
GROWTH_STEP = 3.0             # a successor is at most 3× the current model's parameters
GROWTH_MIN = 1.8              # … and at least 1.8× (smaller steps are not worth a new model)
BPE_MIN_PARAMS = 2_000_000    # small steps keep the byte-level tokenizer (weights carry over); the BPE switch
                              # comes once the model is big enough that its larger vocabulary is a small share


def _shapes():
    """Candidate shapes from tiny to large (d_model, layers, heads, ffn): fine steps so growth can be gradual."""
    out = []
    for d in (32, 48, 64, 80, 96, 128, 160, 192, 224, 256, 320, 384, 448, 512, 640, 768):
        heads = max(1, d // 32)
        while (d // heads) % 2:
            heads -= 1
        for layers in (2, 3, 4, 6, 8, 10, 12):
            if layers > max(2, d // 24):
                continue
            out.append((d, layers, heads, 3 * d))
    return out
TOKENS_PER_PARAM_TARGET = 20.0
DAY_SECONDS = 86400.0


def _cfg(settings: dict) -> dict:
    g = settings.get("growth") or {}
    return {**DEFAULTS, **{k: g[k] for k in DEFAULTS if k in g}}


def _noise(value: float, n: int) -> float:
    p = min(max(value, 0.0), 1.0)
    return 2 * math.sqrt(p * (1 - p) / max(1, n)) if n else 1.0


def capability_history(ctx: Ctx, version: int, window: int) -> dict[str, list[dict]]:
    """Per capability, the measurements of the newest ``window`` measured versions of this lineage
    (newest first): ``{cap: [{version, value, n, higher_is_better}]}``."""
    from moth_server.intelligence import weakness

    versions = [version] + [a["version"] for a in MEM.ancestors(ctx, version)[1:]]
    out: dict[str, list[dict]] = {}
    for v in versions:
        for cap, m in weakness.capability_reports(ctx, v).items():
            if cap in CAPS and m.get("value") is not None and len(out.setdefault(cap, [])) < window:
                out[cap].append({"version": v, "value": float(m["value"]), "n": int(m.get("n") or 0),
                                 "higher_is_better": bool(m.get("higher_is_better", True)),
                                 "failures": m.get("failures")})
    return out


def judge_capabilities(history: dict[str, list[dict]], window: int) -> list[dict]:
    """Each measured capability: value, target, limited, trend over the window, stalled."""
    from moth_server.intelligence.weakness import TARGETS

    rows = []
    for cap, hist in history.items():
        name, domains = CAPS[cap]
        cur = hist[0]
        row: dict[str, Any] = {"capability": cap, "name": name, "value": cur["value"], "n": cur["n"],
                               "higher_is_better": cur["higher_is_better"], "versions": len(hist),
                               "domains": domains}
        if cap in TARGETS:
            floor, target = TARGETS[cap]
            row["target"] = target
            row["limited"] = cur["value"] < target
        else:
            row["target"], row["limited"] = None, None  # loss: judged by its trend only
        if len(hist) >= window:
            old = hist[window - 1]["value"]
            if cur["higher_is_better"]:
                gain = cur["value"] - old
                row["change"] = gain
                row["stalled"] = gain <= _noise(old, cur["n"])
            else:  # held-out loss: relative improvement below 1% across the window = stalled
                rel = (old - cur["value"]) / old if old else 0.0
                row["change"] = rel
                row["stalled"] = rel < 0.01
        else:
            row["change"], row["stalled"] = None, None
        rows.append(row)
    return sorted(rows, key=lambda r: list(CAPS).index(r["capability"]))


def _tokens_and_params(base: dict) -> tuple[int, int]:
    info = base.get("info") or {}
    params = int(((info.get("params_measured") or {}).get("total")) or info.get("params") or 0)
    tokens = int((info.get("lineage_totals") or {}).get("tokens") or (info.get("training") or {}).get("tokens") or 0)
    return tokens, params


def _domain_shares(ctx: Ctx) -> dict[str, float] | None:
    from moth_server.intelligence import library

    build = library.latest_ready(ctx)
    if not build:
        return None
    manifest = build.get("manifest")
    manifest = json.loads(manifest) if isinstance(manifest, str) else (manifest or {})
    counts = {d: int(v.get("train", 0)) if isinstance(v, dict) else int(v or 0)
              for d, v in (manifest.get("token_counts") or {}).items()}
    total = sum(counts.values())
    return {d: c / total for d, c in counts.items()} if total else None


def growth_attempts(ctx: Ctx, limit: int = 200) -> list[dict]:
    return [e for e in MEM.experiments(ctx, limit=limit) if (e.get("config") or {}).get("grow")]


def _cooldown(ctx: Ctx, c: dict) -> str | None:
    attempts = growth_attempts(ctx)
    failed = [e for e in attempts if e["status"] in ("rejected", "failed")]
    if any(e["status"] not in ("passed", "rejected", "failed", "cancelled") for e in attempts):
        return "a growth candidate is already being trained or evaluated"
    recent_cycles = [cy["id"] for cy in MEM.cycles(ctx, 40) if cy["status"] in MEM.TERMINAL_CYCLE]
    if failed:
        last = failed[0]
        since = len([cid for cid in recent_cycles if cid > (last["cycle_id"] or 0)])
        if since < int(c["cooldown_cycles"]):
            return (f"a larger candidate (experiment #{last['id']}) was rejected {since} cycle(s) ago; the next "
                    f"attempt waits {int(c['cooldown_cycles']) - since} more cycle(s) for new evidence")
        window = set(recent_cycles[:20])
        if len([e for e in failed if e["cycle_id"] in window]) >= int(c["max_failed_attempts"]):
            return (f"{int(c['max_failed_attempts'])} larger candidates were rejected in the last 20 cycles; growth "
                    "pauses until capabilities change")
    return None


def estimate(ctx: Ctx, base: dict, cfg_model, option: dict, settings: dict) -> dict[str, Any]:
    """Memory the larger candidate needs to train, which authorized compute has it, and the time the
    last run on this model took scaled by size (None when there is no measurement yet)."""
    from moth.model.growth import grown_config

    from moth_server.evolution import compute as C

    tr = settings["training"]
    new = grown_config(cfg_model, option["add_layers"], option["ffn_hidden"])
    need = C.estimate_training_memory(option["params"], int(tr["batch_size"]), int(tr["seq_len"]), new.d_model,
                                      new.n_layers)
    be = settings.get("backends") or {}
    local_ok = False
    if be.get("local_cpu") or be.get("local_gpu"):
        try:
            loc = C.local(ctx)
            mem = (loc.get("memory") or {}).get("available") or 0
            gpus = [g.get("memory_free") or 0 for g in (loc.get("gpus") or [])]
            local_ok = (be.get("local_cpu") and mem >= need) or (be.get("local_gpu") and any(f >= need for f in gpus))
        except Exception:  # noqa: BLE001
            local_ok = False
    workers = C.worker_capacity(ctx, need, settings.get("worker_ids")) if be.get("workers") else {"usable": 0}
    seconds = None
    for e in MEM.experiments(ctx, limit=60):
        steps = ((e.get("metrics") or {}).get("training") or {}).get("step") or (e.get("config") or {}).get("steps")
        if e["status"] in ("passed", "rejected") and e["base_version"] == base["version"] and e["compute_seconds"] and steps:
            per_step = float(e["compute_seconds"]) / float(steps)
            seconds = per_step * option["ratio"] * int(tr["steps"]) * int((settings.get("growth") or {}).get("steps_multiplier", 2))
            break
    return {"memory_bytes": need, "fits_server": bool(local_ok), "workers_that_fit": int(workers.get("usable") or 0),
            "training_seconds": seconds, "params_after": option["params"], "ratio": option["ratio"]}


def _tpp(v: float) -> str:
    """2.2: tokens per parameter readable at any size ("0.0" hid a model that had seen 0.4 tokens/param)."""
    return "0" if v <= 0 else f"{v:.1f}" if v >= 1 else f"{v:.2g}"


def assess(ctx: Ctx, base: dict, settings: dict) -> dict[str, Any]:
    """What limits MOTH now, and what to do about it (see the module docstring)."""
    from moth.model.config import MothConfig
    from moth.model.growth import growth_options

    from moth_server.evolution.v2 import growth_evidence

    c = _cfg(settings)
    g = settings.get("growth") or {}
    window = int(c["capability_window"])
    caps = judge_capabilities(capability_history(ctx, base["version"], window), window)
    ev = growth_evidence(ctx, base)
    imps = [float(x) for x in ev.get("recent_improvements") or [] if x is not None and math.isfinite(float(x))]
    tokens, params = _tokens_and_params(base)
    tpp = tokens / params if params else 0.0
    loss_improving = bool(imps) and imps[-1] >= float(g.get("plateau_threshold", 0.01))
    loss_plateau = len(imps) >= 3 and max(imps[-3:]) < float(g.get("plateau_threshold", 0.01))
    limited = [r for r in caps if r["limited"]]
    stalled = [r for r in caps if r["stalled"] and (r["limited"] or r["limited"] is None)]
    names = lambda rows: ", ".join(r["name"].lower() for r in rows)  # noqa: E731
    out: dict[str, Any] = {"capabilities": caps, "params": params, "tokens": tokens,
                           "tokens_per_param": round(tpp, 2), "loss_improvements": imps[-3:],
                           "loss_improving": loss_improving, "loss_plateau": loss_plateau,
                           "causes": [], "grow": False, "params_before": params}

    def cause(name: str, found: bool | None, detail: str) -> None:
        out["causes"].append({"cause": name, "found": found, "detail": detail})

    def decide(action: str, headline: str, reason: str) -> dict:
        out.update(action=action, headline=headline, reason=reason)
        return out

    # 0.9.2: a model far too small for the available compute is replaced, not grown step by step
    # (0.10.0: not measured again while a successor trains: the measurement would compete with it)
    try:
        rs = None if successor_running(ctx) else right_size(ctx, base, settings)
    except Exception as exc:  # noqa: BLE001 — sizing only refines the plan (the reason is kept)
        rs = None
        cause("sizing_unavailable", None, f"{type(exc).__name__}: {exc}"[:300])
    if rs:
        blocked = rebirth_blocked(ctx, rs["params_after"])
        cause("too_small", True, f"{params:,} parameters, while the measured compute can train about "
              f"{rs['optimal_params']:,} properly in a day")
        from moth_server.intelligence import library

        waiting = None
        if not blocked and not rs.get("tokenizer") and not rs.get("keep_bytes") and library.byte_level(base):
            waiting = library.ensure_successor_tokenizer(ctx)  # 0.10.0: a BPE successor needs its own data
        if waiting:
            cause("successor_tokenizer", True, waiting)
            out["successor_waiting"] = waiting
        elif not blocked:
            out.update(rebirth=rs, params_after=rs["params_after"])
            return decide("rebirth", f"Growing MOTH one step: {rs['params_before']:,} → {rs['params_after']:,} parameters.",
                          f"the measured compute can train about {rs['optimal_params']:,} parameters properly in a day; "
                          f"MOTH grows gradually (at most {GROWTH_STEP:.0f}× per step"
                          f"{', starting from the current model' + chr(39) + 's weights' if not rs.get('tokenizer') else ''}) on the same "
                          f"curriculum{' with a new BPE tokenizer' if rs.get('tokenizer') else ''} "
                          f"({rs['architecture']['max_seq_len']}-token context; speed {rs['speed_basis']}: "
                          f"{rs['successor_tokens_per_second']:,.0f} tokens/s) and replaces the current model only "
                          f"if it is measurably better")
    if not caps and not imps:
        return decide("continue_training", "Measuring MOTH's capabilities before deciding anything else.",
                      "no capability benchmark or held-out result has been recorded for this model yet")
    focus = stalled or limited
    if focus:
        lead = (f"{focus[0]['name']} remains limited" if focus[0]["limited"] else f"{focus[0]['name']} has stopped improving")
        out["investigating"] = f"{lead}. Evaluating possible causes."
    # 1. overfitting
    tl, vl = ev.get("train_loss"), ev.get("val_loss")
    over = tl is not None and vl is not None and vl - tl > 0.3
    cause("overfitting", over, f"validation loss {vl:.2f} vs training loss {tl:.2f}" if tl is not None and vl is not None
          else "train/validation losses not recorded")
    if over:
        return decide("improve_data", "MOTH is memorising its training data. Adding more and broader data.",
                      f"held-out loss is {vl - tl:.2f} above training loss: more data, not more parameters")
    # 2. not enough training for this size
    cause("insufficient_training", tpp < float(c["min_tokens_per_param"]),
          f"{tokens:,} tokens trained for {params:,} parameters ({tpp:.1f} per parameter; "
          f"{float(c['min_tokens_per_param']):g} is the usual minimum before a model of this size is saturated)")
    if params and tpp < float(c["foundation_tokens_per_param"]):
        return decide("foundation_training", "MOTH has seen very little text for its size. Running longer foundation training.",
                      f"only {_tpp(tpp)} tokens per parameter so far" + (f"; {names(focus)} cannot be judged yet" if focus else ""))
    if params and tpp < float(c["min_tokens_per_param"]):
        return decide("continue_training", "More training on the current architecture comes first.",
                      f"{_tpp(tpp)} tokens per parameter is below {float(c['min_tokens_per_param']):g}: a larger model "
                      "would be even less trained")
    # 3. generation / format: replies that never end
    inst = next((r for r in caps if r["capability"] == "instruction"), None)
    fails = (capability_history(ctx, base["version"], 1).get("instruction") or [{}])[0].get("failures") or {}
    total_f = sum(int(v) for v in fails.values()) if fails else 0
    gen = bool(inst and inst["limited"] and total_f and int(fails.get("no_end", 0)) / total_f >= 0.6)
    cause("generation", gen if fails else None,
          f"{int(fails.get('no_end', 0))} of {total_f} failed replies never ended on their own" if fails
          else "reply failure reasons not measured for this version")
    if gen and inst in focus:
        return decide("adjust_training", "Replies rarely end on their own. Training more on complete conversations.",
                      "most instruction-following failures are replies that run to the length limit — an end-of-turn "
                      "format problem, which a larger model would not fix by itself")
    # 4. data for the stalled capabilities
    shares = _domain_shares(ctx)
    # only capabilities that stopped improving need different data; limited-but-improving ones are learning
    thin = sorted({d for r in stalled for d in r["domains"] if shares is not None and shares.get(d, 0.0) < float(c["min_domain_share"])})
    cause("data", bool(thin) if shares is not None else None,
          (f"little or no prepared data for: {', '.join(thin)}" if thin else "every stalled capability has training data")
          if shares is not None else "no prepared data library to inspect")
    if thin:
        return decide("improve_data", f"{stalled[0]['name']} has too little training data. Growing the data library.",
                      f"the prepared library has under {float(c['min_domain_share']):.0%} {', '.join(thin)} data")
    # 5. tokenizer and decoding, measured on the deployed model's own replies (0.7.0)
    vocab = int(((base.get("info") or {}).get("config") or {}).get("vocab_size") or 0)
    coh = coherence_for(ctx, base)
    out["coherence"] = coh
    if coh:
        cause("tokenizer", not coh["tokenizer_ok"], ("decode(encode(text)) returns the text exactly"
              if coh["tokenizer_ok"] else "the tokenizer does not give back the same text") +
              f"; {coh['tokens_per_char']} tokens per character" + (" (byte-level: changing it needs a new Genesis)"
                                                                     if vocab and vocab <= 512 else ""))
        cause("decoding", coh["decoding_helps"], f"greedy replies repeat {coh['greedy_repetition']:.0%} of word pairs, "
              f"replies with the serving settings {coh['served_repetition']:.0%}")
        if not coh["tokenizer_ok"]:
            return decide("continue_training", "Replies are garbled by the tokenizer. A larger model would not fix this.",
                          coh["explanation"][:1].lower() + coh["explanation"][1:].rstrip(".") +
                          "; replacing the tokenizer needs a new Genesis")
    elif vocab:
        cause("tokenizer", None, f"{vocab}-token vocabulary" + (" (byte-level: every word is several tokens, which "
              "shortens the usable context; changing it needs a new Genesis)" if vocab <= 512 else ""))
    # 6. capacity
    improving = [r for r in caps if r["stalled"] is False]
    capacity = bool(stalled) or (loss_plateau and not improving)
    cause("capacity", capacity,
          (f"{names(stalled)} did not improve over the last {window} measured versions despite "
           f"{tpp:.0f} tokens per parameter" + (" while held-out loss still improved" if loss_improving else ""))
          if stalled else (f"held-out loss improved less than {float(g.get('plateau_threshold', 0.01)):.0%} in each of "
                           "the last 3 cycles and no capability is measurably improving" if capacity
                           else "capabilities are still improving"))
    if not capacity:
        return decide("continue_training",
                      "Capabilities are still improving. Continuing to train the current architecture."
                      if caps else "Held-out results are still improving. Continuing to train the current architecture.",
                      "no evidence that the architecture limits progress")
    if not g.get("enabled", True):
        return decide("continue_training", "The current architecture may be limiting progress, but growth is turned off.",
                      "architecture growth is turned off in AI Settings")
    blocked = _cooldown(ctx, c)
    if blocked:
        return decide("continue_training", "Keeping the current architecture for now.", blocked)
    cfg_model = MothConfig.from_dict(json.loads((Path(base["path"]) / "config.json").read_text()))
    max_params = int(g.get("max_params", 0)) or None
    max_ratio = float(g.get("max_ratio", 1.5))
    if max_params:
        max_ratio = min(max_ratio, max_params / max(1, params))
    if max_ratio < 1.03:
        return decide("continue_training", "MOTH has reached the largest size its budget allows.",
                      f"the parameter ceiling ({max_params:,}) leaves no room to grow")
    target = min(1.4, 1.1 + 0.1 * max(1, len(stalled)))
    opts = [o for o in growth_options(cfg_model, max_ratio) if o["ratio"] <= max_ratio]
    if not opts:
        return decide("continue_training", "No larger architecture fits the budget.", "no valid growth fits the budget")
    best = min(opts, key=lambda o: (abs(o["ratio"] - target), o["ffn_hidden"] != cfg_model.ffn_hidden, -o["add_layers"]))
    est = estimate(ctx, base, cfg_model, best, settings)
    out["estimate"] = est
    if not est["fits_server"] and not est["workers_that_fit"]:
        return decide("continue_training", "A larger model would need more memory than any available computer has.",
                      f"training {best['params']:,} parameters needs about {est['memory_bytes'] / 2**30:.1f} GB; no "
                      "allowed compute (this server or an online MOTH worker) has that much free")
    out.update(grow=True, add_layers=best["add_layers"], ffn_hidden=best["ffn_hidden"], params_after=best["params"],
               ratio=best["ratio"], target_ratio=round(target, 3),
               requires_approval=best["ratio"] > float(g.get("approval_ratio", 1.25)),
               target_capabilities=[r["capability"] for r in stalled])
    return decide("grow", "Current architecture may be limiting progress. Testing a larger candidate.",
                  out["causes"][-1]["detail"] + f": grow {best['ratio'] - 1:.0%} ({params:,} → {best['params']:,} parameters)")


SUCCESSOR_CONTEXT = 2048      # 2.1: successors read 2,048 tokens at once (0.10.0: 1,024; RoPE positions, no learned table)
PROBE_TTL = DAY_SECONDS       # measured shape speeds are reused for a day


def _probe(ctx: Ctx, model_config: dict, seq_len: int) -> float | None:
    """Measured training speed (tokens/s) of a shape on this server, cached (moth.training.speed_probe)."""
    key = "speed_probe:" + MEM.config_hash({**model_config, "seq": seq_len, "cpus": os.cpu_count(),
                                            "day": int(time.time() // DAY_SECONDS)})[:40]  # one day's probes together
    hit = ctx.db.get_config(key, None)
    if hit and time.time() - float(hit.get("at", 0)) < PROBE_TTL:
        return float(hit["tokens_per_second"])
    try:
        from moth.training.speed_probe import measure

        tps = measure(model_config, seq_len)
    except Exception:  # noqa: BLE001 — without a measurement the compute rule is used instead
        return None
    ctx.db.set_config(key, {"tokens_per_second": tps, "at": time.time()})
    return tps


def right_size(ctx: Ctx, base: dict, settings: dict, probe: bool = True) -> dict | None:
    """The architecture MOTH's compute can train properly in about a day (≈ 20 tokens per parameter),
    or None when the current model is already close to it or nothing has been measured yet.

    0.10.0: each candidate shape's real training speed is measured on this server (a few steps on random
    tokens) instead of being derived from the "6 × parameters" rule, which underestimated small models
    3.5×; worker speed is added in proportion. Successors get a 1024-token context, and a byte-level
    lineage's successor uses the new BPE tokenizer once its data is prepared (about 4× fewer tokens per
    text, so each token carries more meaning)."""
    from moth.model.config import MothConfig

    from moth_server.evolution import compute as C
    from moth_server.intelligence import library

    g = settings.get("growth") or {}
    if not g.get("enabled", True) or g.get("rebirth", True) is False:
        return None
    cfg_model = MothConfig.from_dict(json.loads((Path(base["path"]) / "config.json").read_text()))
    params = cfg_model.num_params()
    tp = C.throughput(ctx)
    local = float(tp.get("local:cuda") or tp.get("local:cpu") or 0.0)
    if local <= 0:
        return None  # nothing measured yet: the first runs measure it
    workers = sum(float(v) for k, v in tp.items() if k.startswith("worker:") and v)
    share = (local + workers) / local      # the workers add speed in proportion to the server's
    max_params = int(g.get("max_params", 0)) or None
    byte = library.byte_level(base)
    keep_bytes = byte and params * GROWTH_STEP < BPE_MIN_PARAMS  # 2.1: small steps stay byte-level
    tok = library.successor_tokenizer(ctx) if byte and not keep_bytes else None
    vocab = ((int(tok["vocab_size"]) + 63) // 64) * 64 if tok else cfg_model.vocab_size
    cap = params * GROWTH_STEP if not tok else max(params * GROWTH_STEP, BPE_MIN_PARAMS)
    context = max(cfg_model.max_seq_len, SUCCESSOR_CONTEXT)
    seq = min(context, int(((settings.get("training") or {}).get("seq_len")) or 256) * 8)
    flops_rate = 6.0 * params * (local + workers)  # the old compute rule, only to skip hopeless shapes
    best = None
    basis = "measured"
    # Calibration: the current shape is timed the same way, at the same moment. Its real training speed is
    # known (``local``), so the ratio corrects the probes for whatever else this server is doing right now
    # and for the difference between a short probe and a real run.
    here = _probe(ctx, {**cfg_model.to_dict()}, seq) if probe else None
    factor = min(100.0, max(0.1, local / here)) if here else 1.0
    shapes = []
    for d, layers, heads, ffn in _shapes():
        c = MothConfig.from_dict({**cfg_model.to_dict(), "d_model": d, "n_layers": layers, "n_heads": heads,
                                  "n_kv_heads": heads, "ffn_hidden": ffn, "vocab_size": vocab, "max_seq_len": context})
        shapes.append((c.num_params(), c))
    for n, c in sorted(shapes, key=lambda x: x[0]):
        if n <= params * 1.05:
            continue
        if n > cap or (max_params and n > max_params):
            break
        need = TOKENS_PER_PARAM_TARGET * n / DAY_SECONDS   # tokens/s that trains it properly in a day
        estimate = flops_rate / (6.0 * n)
        if estimate * 8 < need:
            break                                            # even 8× faster than the rule would not do
        tps = _probe(ctx, c.to_dict(), seq) if probe and here else None
        if tps is None:
            tps, basis = estimate * share, "estimated"
        else:
            tps *= factor * share
        if tps < need:
            break
        best = (n, c, tps)
    if best is None:
        return None
    n, cfg_new, tps = best
    if n < params * GROWTH_MIN:
        return None
    arch = {k: getattr(cfg_new, k) for k in ("d_model", "n_layers", "n_heads", "n_kv_heads", "ffn_hidden",
                                               "vocab_size", "max_seq_len")}
    return {"params_before": params, "params_after": n, "optimal_params": int(tps * DAY_SECONDS / TOKENS_PER_PARAM_TARGET),
            "architecture": arch, "tokens_per_second_now": local + workers,
            "successor_tokens_per_second": round(tps, 1), "speed_basis": basis, "seq_len": seq,
            "tokenizer": tok, "tokens_target": int(TOKENS_PER_PARAM_TARGET * n), "keep_bytes": bool(keep_bytes),
            "gradual": True}


def successor_running(ctx: Ctx) -> bool:
    return any((e.get("config") or {}).get("rebirth") and e["status"] in ("planned", "waiting", "running", "paused",
                                                                           "trained", "evaluating")
               for e in MEM.experiments(ctx, limit=200))


def rebirth_blocked(ctx: Ctx, params_after: int) -> str | None:
    """A successor of this size is not tried again while one is running or soon after one was rejected."""
    recent = [e for e in MEM.experiments(ctx, limit=200) if (e.get("config") or {}).get("rebirth")]
    same = [e for e in recent if int(e["config"]["rebirth"].get("params_after") or 0) == params_after]
    if any(e["status"] in ("planned", "waiting", "running", "paused", "trained", "evaluating") for e in recent):
        return "a right-sized successor is already being trained"
    failed = [e for e in same if e["status"] in ("rejected", "failed")]
    if len(failed) >= 2:
        return f"two successors of this size ({params_after:,} parameters) did not beat the current model"
    return None


def coherence_for(ctx: Ctx, base: dict) -> dict | None:
    """The coherence diagnosis of a model version (moth.model.coherence), measured once per weights file."""
    key = f"coherence:{str(base.get('sha256'))[:40]}"  # server_config keys are at most 64 characters
    cached = ctx.db.get_config(key, None)
    if cached:
        return cached
    try:
        from moth.model.coherence import diagnose
        from moth.model.registry import load_model

        model, tok, _ = load_model(base["path"], verify=False)
        d = diagnose(model, tok)
    except Exception:  # noqa: BLE001 — a diagnosis never blocks planning
        return None
    summary = {"version": base.get("version"), "tokenizer_ok": d["tokenizer"]["ok"],
               "tokens_per_char": d["tokenizer"]["tokens_per_char"], "incoherent": d["incoherent"],
               "decoding_helps": d["decoding_helps"], "cause": d["cause"], "explanation": d["explanation"],
               "greedy_repetition": d["greedy"]["repetition"], "served_repetition": d["served"]["repetition"],
               "served_garbage": d["served"]["garbage"], "served_unended": d["served"]["unended"],
               "samples": [{"prompt": x["prompt"], "reply": x["reply"]} for x in d["served"]["samples"][:3]]}
    ctx.db.set_config(key, summary)
    return summary
