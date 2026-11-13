"""0.7.2: a strategy that keeps failing is suspended while another one works."""
from moth_server.evolution import autopilot as AP


def test_failing_strategy_is_suspended_only_while_another_works(client, monkeypatch):
    ctx = client.app.state.ctx
    stats = {"weakness": {"runs": 5, "passed": 0, "mean_improvement": -0.01, "total": 0},
             "balanced": {"runs": 4, "passed": 2, "mean_improvement": 0.02, "total": 0}}
    monkeypatch.setattr(AP, "strategy_stats", lambda c, limit=60: stats)
    sus, note = AP.suspended_strategies(ctx, ["weakness", "weakness", "balanced"])
    assert sus == {"weakness"} and "5 runs without an accepted improvement" in note and "2 of 4" in note
    stats["balanced"]["passed"] = 0  # nothing works: keep exploring everything
    assert AP.suspended_strategies(ctx, ["weakness", "balanced"]) == (set(), None)
    stats["balanced"]["passed"] = 2
    stats["weakness"]["runs"] = 3  # not enough evidence yet
    assert AP.suspended_strategies(ctx, ["weakness", "balanced"]) == (set(), None)
    assert AP.suspended_strategies(ctx, ["weakness"]) == (set(), None)  # the only option is never suspended
