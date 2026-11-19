"""0.9.2: a model far too small for the measured compute is replaced by a right-sized successor."""
import json

from moth_server import models as M
from moth_server.evolution import capacity as CAP, compute as C, memory as MEM, settings as S
from test_evolution import drive
from test_evolution_v053 import _world


def test_right_size_from_measured_compute(client, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    base = M.release(ctx, base_v)
    assert CAP.right_size(ctx, base, S.get(ctx)) is None  # nothing measured yet: no guess
    C.record_throughput(ctx, "local:cpu", 50_000, 1)  # 50k tokens/s, like a 6-core server on a 100k model
    rs = CAP.right_size(ctx, base, S.get(ctx))
    assert rs and rs["params_after"] >= 4 * rs["params_before"] and rs["params_after"] <= rs["optimal_params"]
    assert rs["architecture"]["d_model"] > json.loads(open(f"{base['path']}/config.json").read())["d_model"]
    S.update(ctx, {"growth": {"max_params": rs["params_before"] * 2}})  # the Owner's ceiling is respected
    assert CAP.right_size(ctx, base, S.get(ctx)) is None


def test_successor_trains_from_scratch_and_must_pass_the_gates(client, owner, tmp_path, monkeypatch):
    ctx, base_v = _world(client, owner, tmp_path, monkeypatch)
    from moth_server.evolution import v2 as V2

    # a short successor run whatever the machine's speed: a fixed small number of steps, a normal budget
    monkeypatch.setattr(V2, "REBIRTH_MAX_HOURS", 1e-6)
    monkeypatch.setattr(V2, "REBIRTH_MIN_STEPS", 40)
    S.update(ctx, {"training": {"steps": 30}, "budget": {"max_cycle_hours": 2.0}})
    C.record_throughput(ctx, "local:cpu", 50_000, 1)
    cyc = drive(ctx, lambda c: any((e["config"] or {}).get("rebirth") for e in MEM.experiments(ctx, c["id"]))
                or c["status"] in MEM.TERMINAL_CYCLE, timeout=300)
    succ = next(e for e in MEM.experiments(ctx, cyc["id"]) if (e["config"] or {}).get("rebirth"))
    r = succ["config"]["rebirth"]
    assert succ["config"]["method"] == "from_scratch" and succ["config"]["no_single_worker"]
    assert r["architecture"]["max_seq_len"] == 2048 and succ["config"]["seq_len"] <= 2048  # 2.1: 2,048-token context
    assert r["speed_basis"] == "measured"  # 0.10.0: the successor's own shape was timed
    assert r["params_after"] >= 4 * r["params_before"]
    assert any(e["kind"] == "growth.not_proposed" or e["kind"] == "experiment.planned" for e in MEM.events(ctx, 50))
    cyc = drive(ctx, lambda c: c["status"] in MEM.TERMINAL_CYCLE, timeout=900)
    succ = MEM.experiment(ctx, succ["id"])
    assert succ["status"] in ("passed", "rejected", "deployed"), succ["error"]
    cand = M.release(ctx, succ["candidate_version"])
    assert cand["info"]["params"] == r["params_after"]  # the successor really has the new size
    cfg = cand["info"].get("config") or {}  # files of a rejected candidate are removed by retention
    assert cfg["d_model"] == r["architecture"]["d_model"] and cfg["n_layers"] == r["architecture"]["n_layers"]
    assert succ["backend"] == "local"
    if succ["status"] == "rejected":  # the gates protect the current model; a retry trains twice as long
        failed = [g["gate"] for g in (succ["metrics"] or {}).get("gates", []) if not g.get("passed")]
        assert failed
        assert CAP.rebirth_blocked(ctx, r["params_after"]) is None  # one more attempt is allowed
