"""2.2: measurement noise no longer rejects better models (same-shape speed/memory, small accuracy exams),
and honest whole-experiment worker results on small models are no longer refused as "update too large"."""
import torch

from moth_server import models as M
from moth_server.evolution import backends as B
from moth_server.evolution import distributed as D
from moth_server.evolution import evaluation as EV
from moth_server.evolution import settings as S

SUITES = [
    {"id": "retention:target0000000000", "kind": "heldout", "name": "training data"},
    {"id": "capability:security:builtin", "kind": "capability", "capability": "security", "name": "Security exam"},
]
CFG = {"d_model": 64, "n_layers": 2}


def loss(v):
    return {"ok": True, "value": v, "higher_is_better": False}


def acc(v, n=20):
    return {"ok": True, "value": v, "higher_is_better": True, "n": n}


def run(monkeypatch, base_s, cand_s, base_perf, cand_perf, cand_cfg=CFG):
    monkeypatch.setattr(EV, "build_suites", lambda ctx, rel: SUITES)
    monkeypatch.setattr(EV, "_prescreen", lambda *a, **k: None)
    monkeypatch.setattr(EV, "benchmark", lambda ctx, version, path, suites:
                        {"suites": base_s if version == 1 else cand_s, "performance": base_perf if version == 1 else cand_perf})
    monkeypatch.setattr(M, "evaluate", lambda ctx, v: {"status": "published", "evaluation": {}})
    return EV.gate(None, {"version": 2, "path": "/c", "info": {"config": cand_cfg}},
                   {"version": 1, "path": "/b", "info": {"config": CFG}}, {"sha256": "target0000000000xx"}, S.DEFAULTS)


def test_same_shape_speed_noise_does_not_reject(monkeypatch):
    s = {"retention:target0000000000": loss(5.6), "capability:security:builtin": acc(0.2)}
    c = {**s, "retention:target0000000000": loss(1.6)}
    v = run(monkeypatch, s, c, {"tokens_per_second": 100.0, "peak_memory_bytes": 100},
            {"tokens_per_second": 40.0, "peak_memory_bytes": 140})  # benchmarked while training was running
    g = {x["gate"]: x for x in v["gates"]}
    assert v["passed"], v["decision"]
    assert g["speed"]["informational"] and g["memory"]["informational"]


def test_a_different_shape_is_still_held_to_speed(monkeypatch):
    s = {"retention:target0000000000": loss(5.6), "capability:security:builtin": acc(0.2)}
    c = {**s, "retention:target0000000000": loss(1.6)}
    v = run(monkeypatch, s, c, {"tokens_per_second": 100.0}, {"tokens_per_second": 40.0}, cand_cfg={"d_model": 96})
    assert not v["passed"] and "speed" in v["decision"]


def test_a_guessing_exam_drop_within_noise_does_not_block(monkeypatch):
    # a seed model guessed 25 % on a 20-question exam; the trained candidate 10 %: within 3 standard errors
    s = {"retention:target0000000000": loss(5.6), "capability:security:builtin": acc(0.25)}
    c = {"retention:target0000000000": loss(1.6), "capability:security:builtin": acc(0.10)}
    v = run(monkeypatch, s, c, {}, {})
    assert v["passed"], v["decision"]


def test_result_size_limit_allows_a_small_models_honest_training():
    assert B.RESULT_MAX_RELATIVE_NORM >= 100 and D.ROUND_MAX_RELATIVE_NORM >= 100
    from moth.community.validation import validate_delta

    base = {"embed.weight": torch.full((256, 16), 0.02)}
    delta = {"embed.weight": torch.full((256, 16), 0.02 * 11.5)}  # the rejection seen on Worker #13
    assert not validate_delta(base, delta, max_relative_norm=10.0).ok
    assert validate_delta(base, delta, max_relative_norm=B.RESULT_MAX_RELATIVE_NORM).ok
    bad = {"embed.weight": torch.full((256, 16), float("nan"))}
    assert not validate_delta(base, bad, max_relative_norm=B.RESULT_MAX_RELATIVE_NORM).ok


def test_a_rejection_streak_is_reported_with_its_blocking_checks():
    from types import SimpleNamespace

    from moth_server.evolution import autopilot as AP

    def ctx(rows):
        return SimpleNamespace(db=SimpleNamespace(all=lambda stmt: rows))

    assert AP.rejection_streak(ctx([{"status": "passed", "error": None}])) is None
    rows = [{"status": "rejected", "error": "failed: speed" + (", memory" if i % 2 else "")} for i in range(6)]
    msg = AP.rejection_streak(ctx(rows + [{"status": "passed", "error": None}]))
    assert msg.startswith("The last 6 candidates were not promoted") and "speed (6×)" in msg and "memory (3×)" in msg


def test_a_failed_growth_size_is_retried_on_a_new_base_or_after_two_days(monkeypatch):
    import time

    from moth_server.evolution import capacity as CAP

    now = time.time()

    def exp(status, base, at):
        return {"status": status, "base_version": base, "finished_at": at, "config": {"rebirth": {"params_after": 270_000}}}

    rows = [exp("rejected", 150, now - 3600), exp("rejected", 150, now - 7200)]
    monkeypatch.setattr(CAP.MEM, "experiments", lambda ctx, limit=200: rows)
    assert "did not beat" in CAP.rebirth_blocked(None, 270_000, 150)
    assert CAP.rebirth_blocked(None, 270_000, 151) is None        # a new base model may try again
    assert CAP.rebirth_blocked(None, 300_000, 150) is None        # another size may be tried now
    rows[:] = [exp("rejected", 150, now - 3 * 86400), exp("rejected", 150, now - 3 * 86400)]
    assert CAP.rebirth_blocked(None, 270_000, 150) is None        # two days later it is tried again
    rows.append({"status": "running", "base_version": 150, "config": {"rebirth": {"params_after": 270_000}}})
    assert "already being trained" in CAP.rebirth_blocked(None, 270_000, 150)
