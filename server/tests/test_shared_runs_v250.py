"""2.5: shared runs report their real speed, stop when held-out loss stops improving, and the next successor
is planned with the speed shared runs really reach."""
from moth_server.evolution import distributed as D


def _h(r, before, after, at, tokens=1000, accepted=True):
    return {"round": r, "probe_before": before, "probe_after": after, "accepted": accepted, "at": at, "tokens": tokens}


def test_real_speed_counts_waiting_and_merging():
    hist = [_h(0, 2.0, 1.9, 100.0), _h(1, 1.9, 1.8, 200.0), _h(2, 1.8, 1.7, 300.0)]
    assert D.real_speed(hist) == 2000 / 200
    assert D.real_speed(hist[:1]) is None


def test_a_run_whose_held_out_loss_stopped_improving_stops():
    improving = [_h(i, 2 - i * 0.05, 2 - (i + 1) * 0.05, i) for i in range(12)]
    assert not D._stalled(improving, 29)
    flat = improving[:6] + [_h(6 + i, 1.70, 1.70 + (0.01 if i % 2 else -0.002), 6 + i) for i in range(8)]
    assert D._stalled(flat, 29)
    assert not D._stalled(flat[:7], 29)          # too early to judge
    assert not D._stalled(flat, 60)              # less than a third of a long run


def test_the_next_successor_is_planned_with_the_real_shared_speed(client):
    ctx = client.app.state.ctx
    assert D.shared_speed_factor(ctx) == 1.0
    exp = {"config": {"rebirth": {"planned_tokens": 36_000_000, "planned_hours": 1.0}}}   # 10,000 tokens/s planned
    st = {"history": [_h(0, 2, 1.9, 0.0, 1000), _h(1, 1.9, 1.8, 1000.0, 1_000_000)]}      # 1,000 tokens/s real
    D._learn_shared_speed(ctx, exp, st)
    assert abs(D.shared_speed_factor(ctx) - 0.1) < 1e-9
    D._learn_shared_speed(ctx, exp, {"history": [_h(0, 2, 1.9, 0.0), _h(1, 1.9, 1.8, 100.0, 1_000_000)]})
    assert abs(D.shared_speed_factor(ctx) - (0.1 + 1.0) / 2) < 1e-9  # averaged with the earlier run
    assert D.report({"resources": {"distributed": {"rounds": 3, "round": 2, "local_steps": 5, "history": st["history"]}}}
                    )["tokens_per_sec"] == 1000.0
