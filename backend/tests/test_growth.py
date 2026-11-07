"""Adaptive Parameter Growth: exact function preservation, optimizer migration, continued training,
evidence-based growth decisions."""

import torch
import pytest

from moth.model.config import preset
from moth.model.growth import (assert_function_preserved, expand_optimizer, expand_state, grow_checkpoint, grown_config,
                               layer_map, plan_growth)
from moth.model.transformer import MothModel


def _trained(cfg, steps=12, seed=0):
    torch.manual_seed(seed)
    m = MothModel(cfg)
    opt = m.configure_optimizer(3e-3, 0.0)
    data = torch.randint(0, cfg.vocab_size, (4, 33), generator=torch.Generator().manual_seed(1))
    for _ in range(steps):
        _, loss = m(data[:, :-1], data[:, 1:])
        loss.backward()
        opt.step()
        opt.zero_grad()
    return m, opt, data


def test_layer_map_spreads_new_layers():
    assert layer_map(4, 6) == [0, 1, None, 2, 3, None]
    assert layer_map(2, 2) == [0, 1]
    assert layer_map(3, 6).count(None) == 3


def test_depth_and_width_growth_preserve_the_function_exactly():
    cfg = preset("moth-tiny", vocab_size=256)
    m, _, data = _trained(cfg)
    for add, ffn in ((2, None), (0, cfg.ffn_hidden + 64), (1, cfg.ffn_hidden + 128)):
        new = grown_config(cfg, add, ffn)
        state, _ = expand_state(m.state_dict(), cfg, new, seed=3)
        diff = assert_function_preserved(m.state_dict(), cfg, state, new, data[:, :-1])
        assert diff < 1e-5 and new.num_params() > cfg.num_params()


def test_optimizer_moments_migrate_and_training_continues():
    cfg = preset("moth-tiny", vocab_size=256)
    m, opt, data = _trained(cfg)
    new = grown_config(cfg, 2, cfg.ffn_hidden + 64)
    state, rec = expand_state(m.state_dict(), cfg, new)
    m2 = MothModel(new)
    m2.load_state_dict(state)
    opt2 = m2.configure_optimizer(3e-3, 0.0)
    opt2.load_state_dict(expand_optimizer(opt.state_dict(), m, m2, rec))
    # an old parameter keeps its moments; an inserted layer's output projection starts with zero moments
    old_i = [n for n, p in m.named_parameters() if p.dim() >= 2].index("layers.0.attn.wq.weight")
    new_i = [n for n, p in m2.named_parameters() if p.dim() >= 2].index("layers.0.attn.wq.weight")
    assert torch.equal(opt2.state_dict()["state"][new_i]["exp_avg"], opt.state_dict()["state"][old_i]["exp_avg"])
    inserted = rec["layer_map"].index(None)
    ins = [n for n, p in m2.named_parameters() if p.dim() >= 2].index(f"layers.{inserted}.attn.wo.weight")
    assert float(opt2.state_dict()["state"][ins]["exp_avg"].abs().sum()) == 0.0
    with torch.no_grad():
        _, before = m2(data[:, :-1], data[:, 1:])
    for _ in range(10):  # the grown model keeps learning from where the small one stopped
        _, loss = m2(data[:, :-1], data[:, 1:])
        loss.backward()
        opt2.step()
        opt2.zero_grad()
    assert float(loss) < float(before)


def test_grow_checkpoint_leaves_the_original_untouched():
    cfg = preset("moth-tiny", vocab_size=256)
    m, opt, data = _trained(cfg)
    ck = {"model": m.state_dict(), "optimizer": opt.state_dict(), "model_config": cfg.to_dict(), "step": 12}
    before = {k: v.clone() for k, v in ck["model"].items()}
    g = grow_checkpoint(ck, 1, cfg.ffn_hidden + 64)
    assert all(torch.equal(before[k], ck["model"][k]) for k in before)  # stable model never modified
    assert g["growth"]["to_params"] > g["growth"]["from_params"] and g["step"] == 12


def test_plan_growth_needs_evidence():
    cfg = preset("moth-50m", vocab_size=16384)
    still = plan_growth(cfg, {"recent_improvements": [0.04, 0.02, 0.015], "train_loss": 2.0, "val_loss": 2.1})
    assert not still["grow"] and "still improving" in still["reason"]
    over = plan_growth(cfg, {"recent_improvements": [0.001, 0.0, 0.002], "train_loss": 1.5, "val_loss": 2.2})
    assert not over["grow"] and "overfitting" in over["reason"]
    mild = plan_growth(cfg, {"recent_improvements": [0.02, 0.004, 0.003, 0.002], "train_loss": 2.0, "val_loss": 2.1})
    strong = plan_growth(cfg, {"recent_improvements": [0.002] * 7, "train_loss": 2.0, "val_loss": 2.1})
    assert mild["grow"] and strong["grow"] and strong["ratio"] > mild["ratio"]  # increments follow the evidence
    assert mild["ratio"] < 1.25 and not mild["requires_approval"]
    assert strong["requires_approval"] or strong["ratio"] <= 1.25
    tight = plan_growth(cfg, {"recent_improvements": [0.0] * 6, "train_loss": 2.0, "val_loss": 2.0},
                        {"max_params": int(cfg.num_params() * 1.08)})
    assert tight["grow"] and tight["params_after"] <= cfg.num_params() * 1.08  # respects the compute budget
    none = plan_growth(cfg, {"recent_improvements": [0.0] * 6, "train_loss": 2, "val_loss": 2},
                       {"max_params": cfg.num_params()})
    assert not none["grow"]


def test_growth_increment_counts_only_the_current_plateau():
    cfg = preset("moth-50m", vocab_size=16384)
    evidence = {"train_loss": 2.0, "val_loss": 2.1}
    recent = [0.002] * 3
    short = plan_growth(cfg, {**evidence, "recent_improvements": recent})
    interrupted = plan_growth(cfg, {**evidence, "recent_improvements": [0.001] * 10 + [0.1] + recent})
    assert interrupted["grow"] and interrupted["ratio"] == short["ratio"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_growth_requires_finite_measurements(invalid):
    decision = plan_growth(preset("moth-tiny"), {"recent_improvements": [0.0, invalid, 0.0]})
    assert not decision["grow"] and "finite" in decision["reason"]
