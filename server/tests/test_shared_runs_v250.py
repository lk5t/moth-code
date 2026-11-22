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


def test_one_pass_counts_a_small_heavily_weighted_domain_first(tmp_path):
    import json

    import numpy as np

    from moth_server.evolution import v2 as V2

    for d, n in (("code", 100_000), ("chat", 1_000)):
        (tmp_path / d).mkdir()
        np.zeros(n, dtype=np.uint32).tofile(tmp_path / d / "train.bin")
        (tmp_path / d / "meta.json").write_text(json.dumps({"dtype": "uint32"}))
    (tmp_path / "mixture.json").write_text(json.dumps({"domains": {"code": {"dir": "code"}, "chat": {"dir": "chat"}}}))
    big = V2.one_pass_tokens(str(tmp_path), {"code": 1.0})
    assert big == 100_000
    mixed = V2.one_pass_tokens(str(tmp_path), {"code": 0.5, "chat": 0.5})
    assert mixed < 4_000  # the 1,000-token chat domain at half the mixture is repeated almost at once
    assert V2.one_pass_tokens(str(tmp_path / "missing"), {"code": 1.0}) is None


def test_the_live_view_lists_the_computers_training_an_experiment(client, owner):
    import json

    from moth_server.db import now, training_jobs
    from moth_server.evolution.native_reset import next_job_values
    from moth_server.routes.intelligence import _compute_live
    from test_network_v063 import _enroll

    ctx = client.app.state.ctx
    w = _enroll(client, owner)
    with ctx.db.tx() as c:
        values = next_job_values(ctx, c)
        c.execute(training_jobs.insert().values(**values, kind="dist_shard", status="leased", worker_id=w["worker_id"],
                                                progress=0.4, spec=json.dumps({"evolution_experiment": 78, "round": 3}),
                                                attempts=0, max_attempts=3, created_at=now(), updated_at=now()))
        c.execute(training_jobs.insert().values(**next_job_values(ctx, c), kind="dist_shard", status="leased",
                                                worker_id=w["worker_id"], progress=0.9,
                                                spec=json.dumps({"evolution_experiment": 780, "round": 1}),
                                                attempts=0, max_attempts=3, created_at=now(), updated_at=now()))
    live = _compute_live(ctx, {"id": 78})
    assert len(live) == 1 and live[0]["kind"] == "cpu" and live[0]["cpu"] == 0.25 and live[0]["part_progress"] == 0.4
    assert live[0]["seen_seconds_ago"] < 60


def test_deeper_shapes_win_when_sizes_are_close():
    from moth_server.evolution import capacity as CAP

    shapes = CAP._shapes()
    assert max(layers for d, layers, _, _ in shapes if d == 384) >= 20   # 2.5.2: deep shapes exist
    assert all(d // heads == 32 or d < 64 for d, _, heads, _ in shapes if d % 32 == 0)


def test_shape_timing_is_bounded(client, monkeypatch):
    """2.5.3: at most MAX_NEW_PROBES new shapes are timed per pass, on a quarter of the cores; failures are cached."""
    import torch

    from moth_server.evolution import capacity as CAP

    ctx = client.app.state.ctx
    calls, threads = [], []
    monkeypatch.setattr("moth.training.speed_probe.measure", lambda cfg, seq: (calls.append(cfg), threads.append(torch.get_num_threads()), 1000.0)[2])
    budget = [CAP.MAX_NEW_PROBES]
    shapes = [{"d_model": 64 + 32 * i, "n_layers": 2} for i in range(6)]
    got = [CAP._probe(ctx, s, 256, budget) for s in shapes]
    assert len(calls) == CAP.MAX_NEW_PROBES and got.count(None) == len(shapes) - CAP.MAX_NEW_PROBES
    assert all(t <= max(1, (__import__("os").cpu_count() or 4) // 4) for t in threads)
    assert CAP._probe(ctx, shapes[0], 256, [0]) == 1000.0  # cached: no budget needed
    def boom(cfg, seq):
        calls.append(cfg); raise RuntimeError("no")
    monkeypatch.setattr("moth.training.speed_probe.measure", boom)
    n = len(calls)
    assert CAP._probe(ctx, {"d_model": 999}, 256) is None and CAP._probe(ctx, {"d_model": 999}, 256) is None
    assert len(calls) == n + 1  # a failure is remembered, not retried every pass
