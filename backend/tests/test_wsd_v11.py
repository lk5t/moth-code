"""1.1: warm-up / stable / decay learning rate."""
from moth.training.trainer import TrainConfig, lr_at


def test_wsd_holds_then_cools_down():
    cfg = TrainConfig(lr=1e-3, min_lr=1e-4, warmup_steps=10, max_steps=100, lr_schedule="wsd", decay_fraction=0.2)
    assert lr_at(0, cfg) < 1e-3                      # warm-up
    assert lr_at(10, cfg) == lr_at(79, cfg) == 1e-3  # stable for most of the run
    assert 1e-4 < lr_at(90, cfg) < 1e-3              # linear cool-down over the last 20 %
    assert abs(lr_at(99, cfg) - 1e-4) < 5e-5 and lr_at(100, cfg) == 1e-4


def test_cosine_is_unchanged_by_default():
    cfg = TrainConfig(lr=1e-3, min_lr=1e-4, warmup_steps=10, max_steps=100)
    assert lr_at(50, cfg) < 1e-3
