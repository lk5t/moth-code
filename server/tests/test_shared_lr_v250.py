"""2.5: a shared run's parts follow one learning-rate curve over all rounds (they used a fixed rate)."""
from moth_worker.runner import shared_lr


def _t(r, rounds=10, steps=100, warmup=0.02):
    return {"lr": 1e-3, "steps": steps, "schedule": {"round": r, "rounds": rounds, "min_lr": 1e-4, "warmup": warmup}}


def test_one_curve_over_every_round():
    lrs = [shared_lr(_t(r), s) for r in range(10) for s in range(0, 100, 10)]
    assert lrs[0] < 1e-3 * 0.6                          # warms up first
    peak = lrs.index(max(lrs))
    assert all(a >= b - 1e-12 for a, b in zip(lrs[peak:], lrs[peak + 1:]))  # then only goes down, across rounds
    assert abs(shared_lr(_t(9), 99) - 1e-4) < 2e-5      # ends near the minimum
    assert shared_lr(_t(5), 0) < shared_lr(_t(4), 0)    # a later round starts lower, not back at the top


def test_resumed_runs_skip_the_warm_up():
    assert shared_lr(_t(0, warmup=0.0), 0) == 1e-3
