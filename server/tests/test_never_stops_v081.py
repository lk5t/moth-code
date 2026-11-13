"""0.8.1: Evolution never runs out of experiments, and elapsed time is measured by MOTH Cloud."""
import time

from moth_server.evolution import memory as MEM, settings as S, v2


def _out():
    return {"experiments": [], "skipped": [], "notes": [], "weaknesses": [], "growth": None}


def _plan_inputs(ctx):
    base = {"version": 7, "sha256": "a" * 64}
    src = {"dataset_id": 1, "build_id": 3, "path": "/x", "build_sha256": "b" * 64}
    tilted = {"weights": {"conversation": 0.6, "code": 0.4}, "stage": "balanced"}
    balanced = {"weights": {"conversation": 0.5, "code": 0.5}, "stage": "balanced"}
    return base, src, tilted, balanced


def test_exploration_supplies_new_experiments_every_cycle(client, monkeypatch):
    ctx = client.app.state.ctx
    settings = S.get(ctx)
    base, src, tilted, balanced = _plan_inputs(ctx)
    tried = set()
    monkeypatch.setattr(MEM, "tried", lambda c, h: {"id": 1, "status": "rejected"} if h in tried else None)
    seen = []
    for cycle in range(6):  # six cycles in a row, each after the previous ones were all rejected
        out = _out()
        v2._explore(ctx, out, base, "arch", src, tilted, balanced, [3e-4], settings, cycle)
        assert out["experiments"], f"cycle {cycle} had nothing to run"
        for e in out["experiments"]:
            assert e["config_hash"] not in tried  # never a repeat
            tried.add(e["config_hash"])
            seen.append(e["config"]["exploration"])
        assert any("exploring" in n for n in out["notes"])
    assert len(seen) == len(set(seen)) and len(seen) >= 6
    lrs = {round(e, 8) for e in [3e-4 * f for f in v2.EXPLORE_LR]}
    assert len(lrs) == len(v2.EXPLORE_LR)  # a spread of learning rates around the best known one


def test_elapsed_time_counts_from_when_the_worker_took_the_job():
    from moth_server.routes.intelligence import _elapsed

    t = time.time()
    # queued for hours, then a worker took it ten minutes ago
    e = {"status": "running", "backend": "worker", "started_at": t - 4 * 3600, "resources": {"leased_at": t - 600}}
    assert 595 <= _elapsed(e) <= 605
    assert _elapsed({"status": "running", "backend": "worker", "resources": {}}) is None  # not taken yet
    local = {"status": "running", "backend": "local", "compute_seconds": 120.0, "resources": {"started": t - 60}}
    assert 175 <= _elapsed(local) <= 185  # earlier sessions plus the current one
    assert _elapsed({"status": "rejected", "compute_seconds": 270.0}) == 270.0
