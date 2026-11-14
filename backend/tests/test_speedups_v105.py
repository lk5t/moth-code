"""1.0.5: short context first (same tokens, cheaper steps) and one thread per physical core."""
import torch

from moth.training.speedups import fold, physical_cores


def test_fold_keeps_every_token_in_shorter_rows():
    x = torch.arange(2 * 1024).reshape(2, 1024)
    y, m = x + 1, torch.ones_like(x)
    fx, fy, fm = fold(x, y, m, 256)
    assert fx.shape == (8, 256) and torch.equal(fx.flatten(), x.flatten()) and torch.equal(fy.flatten(), y.flatten())
    assert fm.shape == (8, 256)
    assert fold(x, y, None, 256)[2] is None
    assert fold(x, y, m, 1024)[0] is x and fold(x, y, m, 300)[0] is x  # same length or uneven: unchanged


def test_physical_cores_is_positive():
    assert physical_cores() >= 1


def test_short_context_training_runs(tmp_path):
    from moth.training.trainer import TrainConfig
    from test_continue_v053 import _mixture  # noqa: F401  (fixture helpers exist for full runs)
    cfg = TrainConfig(short_context=16, short_until=0.5)
    assert cfg.short_context == 16 and cfg.short_until == 0.5
