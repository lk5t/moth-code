"""Adaptive Parameter Growth: grow an existing MOTH model instead of training a new one from scratch.

Function-preserving expansions (the grown model computes *exactly* the same outputs before it is trained
further, so nothing learned is lost):

* **depth** — new transformer blocks are inserted between existing ones. A new block copies its
  neighbour's weights except its two output projections (``attn.wo``, ``mlp.w2``), which start at zero;
  because every block is residual, a zero-output block passes its input through unchanged.
* **FFN width** — every block's SwiGLU hidden layer gets extra units; their input weights are small and
  random, their output weights (``w2`` columns) zero, so they contribute nothing until trained.

Width of the residual stream (``d_model``), heads and vocabulary are not grown here: changing them is not
function-preserving and needs distillation — an architecture *migration*, which always needs the Owner.

The optimizer state is migrated with the weights: AdamW moments of existing parameters are kept
(mapped to their new positions), new parameters start with zero moments, and the step count is kept.

``plan_growth`` decides from evidence whether growing is worthwhile and by how much (flexible increments:
5–40% depending on the strength of the plateau and the compute headroom), never while the model is still
improving, never when it overfits (that needs data, not parameters), and never beyond the resource budget.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import torch

from moth.model.config import MothConfig

ZERO_INIT = ("attn.wo.weight", "mlp.w2.weight")


def grown_config(cfg: MothConfig, add_layers: int = 0, ffn_hidden: int | None = None) -> MothConfig:
    new = replace(cfg, n_layers=cfg.n_layers + int(add_layers), ffn_hidden=int(ffn_hidden or cfg.ffn_hidden))
    if new.ffn_hidden < cfg.ffn_hidden or new.n_layers < cfg.n_layers:
        raise ValueError("growth never removes parameters")
    if new.ffn_hidden % 64:
        raise ValueError("ffn_hidden must stay a multiple of 64")
    return new


def layer_map(old_layers: int, new_layers: int) -> list[int | None]:
    """For each new layer index: the old layer it continues, or ``None`` for an inserted layer.

    Inserted layers are spread evenly through the stack (not all appended at the end)."""
    add = new_layers - old_layers
    if add < 0:
        raise ValueError("cannot remove layers")
    out: list[int | None] = []
    inserted = 0
    for i in range(old_layers):
        out.append(i)
        # insert after old layer i when the even spacing says so
        while inserted < add and (inserted + 1) * old_layers <= (i + 1) * add:
            out.append(None)
            inserted += 1
    while inserted < add:
        out.append(None)
        inserted += 1
    return out


def expand_state(state: dict[str, torch.Tensor], old: MothConfig, new: MothConfig, seed: int = 0
                 ) -> tuple[dict[str, torch.Tensor], dict[str, Any]]:
    """Grown weights and a record of where every old tensor went (for the optimizer migration)."""
    g = torch.Generator().manual_seed(seed)
    mapping = layer_map(old.n_layers, new.n_layers)
    out: dict[str, torch.Tensor] = {}
    origin: dict[str, tuple[str, tuple[slice, ...]] | None] = {}
    for k, v in state.items():
        if not k.startswith("layers."):
            out[k] = v.clone()
            origin[k] = (k, tuple(slice(0, n) for n in v.shape))
    prev_old = 0
    for ni, oi in enumerate(mapping):
        src = oi if oi is not None else prev_old  # an inserted layer copies its predecessor
        if oi is not None:
            prev_old = oi
        for k, v in state.items():
            if not k.startswith(f"layers.{src}."):
                continue
            suffix = k[len(f"layers.{src}."):]
            nk = f"layers.{ni}.{suffix}"
            t = v.clone()
            if oi is None and suffix in ZERO_INIT:
                t.zero_()
            out[nk] = t
            origin[nk] = (k, tuple(slice(0, n) for n in v.shape)) if oi is not None else None
    if new.ffn_hidden > old.ffn_hidden:
        extra = new.ffn_hidden - old.ffn_hidden
        for ni in range(new.n_layers):
            for name in ("w1", "w3"):
                k = f"layers.{ni}.mlp.{name}.weight"
                w = out[k]
                add = torch.randn(extra, w.shape[1], generator=g, dtype=torch.float32).to(w.dtype) * 0.02
                out[k] = torch.cat([w, add], dim=0)
            k = f"layers.{ni}.mlp.w2.weight"
            w = out[k]
            out[k] = torch.cat([w, torch.zeros(w.shape[0], extra, dtype=w.dtype)], dim=1)  # new units: zero output
    return out, {"layer_map": mapping, "origin": origin}


def _opt_names(model) -> list[str]:
    """Parameter names in the order MothModel.configure_optimizer puts them into AdamW's state."""
    decay, no_decay = [], []
    for n, p in model.named_parameters():
        if p.requires_grad:
            (decay if p.dim() >= 2 else no_decay).append(n)
    return decay + no_decay


def expand_optimizer(opt_state: dict[str, Any], old_model, new_model, record: dict[str, Any]) -> dict[str, Any]:
    """AdamW state for the grown model: existing moments kept (in their new place), new ones zero."""
    old_names = _opt_names(old_model)
    new_names = _opt_names(new_model)
    old_idx = {n: i for i, n in enumerate(old_names)}
    new_params = dict(new_model.named_parameters())
    state: dict[int, dict[str, Any]] = {}
    step_value = None
    for i, n in enumerate(new_names):
        src = record["origin"].get(n)
        shape = new_params[n].shape
        entry = {"exp_avg": torch.zeros(shape), "exp_avg_sq": torch.zeros(shape)}
        if src is not None and old_idx.get(src[0]) in opt_state["state"]:
            st = opt_state["state"][old_idx[src[0]]]
            for key in ("exp_avg", "exp_avg_sq"):
                t = entry[key]
                region = tuple(slice(0, s) for s in st[key].shape)
                t[region] = st[key].float()
            step_value = st.get("step", step_value)
        state[i] = entry
    if step_value is None:
        step_value = torch.tensor(0.0)
    for e in state.values():
        e["step"] = step_value.clone() if isinstance(step_value, torch.Tensor) else torch.tensor(float(step_value))
    groups = []
    start = 0
    n_decay = sum(1 for n, p in new_model.named_parameters() if p.requires_grad and p.dim() >= 2)
    for gi, grp in enumerate(opt_state["param_groups"]):
        count = n_decay if gi == 0 else len(new_names) - n_decay
        groups.append({**{k: v for k, v in grp.items() if k != "params"}, "params": list(range(start, start + count))})
        start += count
    return {"state": state, "param_groups": groups}


def growth_options(cfg: MothConfig, max_ratio: float = 1.5) -> list[dict[str, Any]]:
    """Every architecturally valid growth up to ``max_ratio``× parameters (depth and/or FFN width)."""
    base = cfg.num_params()
    opts = []
    for add in range(0, max(1, cfg.n_layers) + 1):
        for ffn in range(cfg.ffn_hidden, int(cfg.ffn_hidden * 2) + 1, 64):
            if add == 0 and ffn == cfg.ffn_hidden:
                continue
            new = grown_config(cfg, add, ffn)
            ratio = new.num_params() / base
            if ratio <= max_ratio:
                opts.append({"add_layers": add, "ffn_hidden": ffn, "params": new.num_params(), "ratio": round(ratio, 4)})
    return sorted(opts, key=lambda o: o["ratio"])


def plan_growth(cfg: MothConfig, evidence: dict[str, Any], budget: dict[str, Any] | None = None,
                approval_ratio: float = 1.25) -> dict[str, Any]:
    """Decide whether to grow and by how much, from measurements.

    ``evidence``: ``recent_improvements`` (relative held-out improvements of the last promoted cycles,
    newest last), ``train_loss`` and ``val_loss`` of the stable model, optional ``plateau_threshold``.
    ``budget``: ``max_params`` (from the compute budget / worker memory) and ``max_ratio``.
    """
    budget = budget or {}
    imps = list(evidence.get("recent_improvements") or [])
    thr = float(evidence.get("plateau_threshold", 0.01))
    out: dict[str, Any] = {"grow": False, "params_before": cfg.num_params()}
    if len(imps) < 3:
        return {**out, "reason": "not enough completed cycles to judge a plateau (need 3)"}
    recent = imps[-3:]
    if not all(math.isfinite(float(x)) for x in imps):
        return {**out, "reason": "growth needs finite held-out improvement measurements"}
    if max(recent) >= thr:
        return {**out, "reason": f"the model is still improving ({max(recent):+.2%} in a recent cycle): no growth"}
    tl, vl = evidence.get("train_loss"), evidence.get("val_loss")
    if tl is not None and vl is not None and vl - tl > 0.3:
        return {**out, "reason": f"held-out loss is {vl - tl:.2f} above training loss (overfitting): more data, "
                                 f"not more parameters, is needed"}
    # strength of the plateau → size of the step (flexible increments 5%..40%)
    stuck = 0
    for x in reversed(imps):
        if x >= thr:
            break
        stuck += 1
    target = min(1.4, 1.05 + 0.05 * stuck)
    max_params = int(budget.get("max_params") or 0)
    max_ratio = float(budget.get("max_ratio", 1.5))
    if max_params:
        max_ratio = min(max_ratio, max_params / cfg.num_params())
    if max_ratio < 1.03:
        return {**out, "reason": "the compute budget leaves no room for a larger model"}
    opts = [o for o in growth_options(cfg, max_ratio) if o["ratio"] <= max_ratio]
    if not opts:
        return {**out, "reason": "no valid growth fits the budget"}
    # closest to the target; prefer depth (cheaper per parameter of capacity), then fewer changes
    best = min(opts, key=lambda o: (abs(o["ratio"] - target), o["ffn_hidden"] != cfg.ffn_hidden, -o["add_layers"]))
    return {**out, "grow": True, "add_layers": best["add_layers"], "ffn_hidden": best["ffn_hidden"],
            "params_after": best["params"], "ratio": best["ratio"], "target_ratio": round(target, 3),
            "requires_approval": best["ratio"] > approval_ratio,
            "reason": f"held-out improvement below {thr:.0%} for {stuck} cycles without overfitting: grow "
                      f"{(best['ratio'] - 1):.0%} ({cfg.num_params() / 1e6:.1f}M → {best['params'] / 1e6:.1f}M)"}


def grow_checkpoint(ck: dict[str, Any], add_layers: int, ffn_hidden: int | None = None, seed: int = 0
                    ) -> dict[str, Any]:
    """A grown copy of a full training checkpoint (weights, optimizer, config); the input is untouched."""
    from moth.model.transformer import MothModel

    old_cfg = MothConfig.from_dict(ck["model_config"])
    new_cfg = grown_config(old_cfg, add_layers, ffn_hidden)
    state, record = expand_state(ck["model"], old_cfg, new_cfg, seed)
    out = {k: v for k, v in ck.items() if k not in ("model", "optimizer", "model_config")}
    out["model"] = state
    out["model_config"] = new_cfg.to_dict()
    if ck.get("optimizer"):
        old_m, new_m = MothModel(old_cfg), MothModel(new_cfg)
        out["optimizer"] = expand_optimizer(ck["optimizer"], old_m, new_m, record)
    out["growth"] = {"from_params": old_cfg.num_params(), "to_params": new_cfg.num_params(),
                     "add_layers": add_layers, "ffn_hidden": new_cfg.ffn_hidden, "layer_map": record["layer_map"],
                     "parent_config": old_cfg.to_dict()}
    return out


def assert_function_preserved(old_state, old_cfg: MothConfig, new_state, new_cfg: MothConfig, tokens: torch.Tensor,
                              atol: float = 1e-4) -> float:
    """Maximum absolute logit difference between the two models on ``tokens`` (raises if above ``atol``)."""
    from moth.model.transformer import MothModel

    a, b = MothModel(old_cfg).eval(), MothModel(new_cfg).eval()
    a.load_state_dict(old_state)
    b.load_state_dict(new_state)
    with torch.no_grad():
        la, _ = a(tokens)
        lb, _ = b(tokens)
    diff = float((la.float() - lb.float()).abs().max())
    if not math.isfinite(diff) or diff > atol:
        raise AssertionError(f"growth changed the model's outputs (max logit difference {diff:.2e})")
    return diff
