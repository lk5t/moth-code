"""1.0.2: everyone trains together. A run that started on MOTH Cloud alone moves to shared rounds with
the workers once they come online, continuing from its checkpoint; CPUs join GPU rounds when fast enough."""
import json
import time

import pytest

from moth_server.evolution import backends as B, compute as C, distributed as D, engine as EN, memory as MEM
from test_evolution import drive
from test_network_v063 import _enroll, _world


@pytest.mark.timeout(900)
def test_a_solo_successor_moves_to_shared_rounds_from_its_checkpoint(client, owner, tmp_path, monkeypatch):
    from moth_server.evolution import v2 as V2
    from test_evolution import FAST

    monkeypatch.setattr(V2, "REBIRTH_MAX_HOURS", 1e-6)
    monkeypatch.setattr(V2, "REBIRTH_MIN_STEPS", 4000)  # long enough to still be running when workers arrive
    monkeypatch.setattr(D, "SUCCESSOR_ROUND_STEPS", 10)
    monkeypatch.setattr(EN, "HANDOFF_CHECK_SECONDS", 0.0)
    ctx = _world(client, owner, tmp_path, monkeypatch,
                 training={**FAST["training"], "steps": 4000, "checkpoint_interval": 10, "eval_interval": 1000},
                 backends={"local_cpu": True, "local_gpu": False, "workers": True},
                 distributed={"min_participants": 2, "rounds": 1, "cloud_participates": False},
                 budget={"max_cycle_hours": 2.0}, growth={"enabled": True})
    C.record_throughput(ctx, "local:cpu", 50_000, 1)

    def successor(c):
        return next((e for e in MEM.experiments(ctx, c["id"]) if (e["config"] or {}).get("rebirth")), None)

    # nobody else is online: MOTH Cloud starts the successor alone and saves a checkpoint
    cyc = drive(ctx, lambda c: (s := successor(c)) is not None and s["backend"] == "local"
                and (((s["metrics"] or {}).get("progress") or {}).get("checkpoint") or {}).get("step")
                or c["status"] in MEM.TERMINAL_CYCLE, timeout=400)
    exp = successor(cyc)
    assert exp and exp["backend"] == "local", exp and exp["error"]
    planned = int(exp["config"]["steps"])

    _enroll(client, owner), _enroll(client, owner)  # two workers come online
    deadline = time.time() + 300
    while time.time() < deadline:
        EN.tick(ctx)
        exp = MEM.experiment(ctx, exp["id"])
        if exp["backend"] == "distributed":
            break
        time.sleep(0.3)
    assert exp["backend"] == "distributed", ([(e["kind"], e["message"][:160]) for e in MEM.events(ctx, limit=40) if "checkpoint at step" not in e["message"]], exp["config"].get("resume"), exp["resources"].get("handoff_checked_at"))
    st = exp["resources"]["distributed"]
    assert st["started_from"] == "checkpoint"
    resume = exp["config"]["resume"]
    assert resume["step"] > 0 and resume["planned_steps"] == planned
    assert exp["config"]["steps"] == planned - resume["step"]  # only the remaining steps are shared
    assert not (B.run_dir(ctx, exp) / "checkpoints").exists()
    assert any(e["kind"] == "experiment.shared" for e in MEM.events(ctx, limit=50))


def test_cpus_join_gpu_rounds_when_fast_enough(client, owner, tmp_path, monkeypatch):
    ctx = client.app.state.ctx
    fast_cpu = _enroll(client, owner, gflops=40)
    slow_cpu = _enroll(client, owner, gflops=5)
    e = client.post("/v1/training/enrollments", json={"name": "gpu-box"}, headers={"Authorization": f"Bearer {owner['token']}"}).json()
    hw = {"gpus": [{"name": "RTX", "memory_gb": 8}], "cpu_count": 8, "ram_gb": 32, "ram_available_gb": 24,
          "compute": "gpu", "benchmark": {"gflops": 100}, "utilization": {"cpu": 0.1, "memory": 0.1}}
    g = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": hw, "version": "1.0.2"}).json()
    client.post("/v1/worker/heartbeat", json={"hardware": hw, "version": "1.0.2"},
                headers={"Authorization": f"Bearer {g['worker_token']}"})
    ids = {w["id"] for w in D.participants(ctx, 1)}
    assert g["worker_id"] in ids and fast_cpu["worker_id"] in ids
    assert slow_cpu["worker_id"] not in ids
