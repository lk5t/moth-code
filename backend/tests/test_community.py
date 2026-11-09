import datetime as dt
import json

import pytest
import torch
from fastapi.testclient import TestClient

from moth.community.aggregation import apply_delta, federated_average
from moth.community.client import CommunityClient, ContributionError
from moth.community.coordinator import create_coordinator_app, init_coordinator
from moth.community.protocol import TrainSpec
from moth.community.resources import ParticipationSettings, in_schedule, may_contribute
from moth.community.validation import serialize_state, tensor_bytes_sha256, validate_delta


def test_participation_is_opt_in_and_respects_controls():
    now = dt.datetime(2026, 11, 5, 23, 0)  # Thursday 23:00
    s = ParticipationSettings()
    assert may_contribute(s, now, 0) == (False, "community training is off (opt-in)")
    s.enabled = True
    assert "no coordinator" in may_contribute(s, now, 0)[1]
    s.coordinator_url = "http://coord"
    assert may_contribute(s, now, 0)[0]
    s.paused = True
    assert may_contribute(s, now, 0) == (False, "paused by you")
    s.paused = False
    assert not may_contribute(s, now, s.max_rounds_per_day)[0]
    s.schedule_enabled, s.schedule_start_hour, s.schedule_end_hour = True, 22, 7
    assert in_schedule(s, now) and in_schedule(s, dt.datetime(2026, 11, 6, 3, 0))
    assert not in_schedule(s, dt.datetime(2026, 11, 6, 12, 0))
    s.schedule_days = [0]  # Mondays only (night starting Monday)
    assert not in_schedule(s, now)
    assert in_schedule(s, dt.datetime(2026, 11, 10, 2, 0))  # Tuesday 02:00 belongs to Monday night
    clamped = ParticipationSettings.from_dict({"gpu_memory_fraction": 5, "duty_cycle": 0})
    assert clamped.gpu_memory_fraction == 0.95 and clamped.duty_cycle == 0.05


def test_validation_rejects_bad_updates():
    base = {"w": torch.ones(4, 4), "b": torch.ones(4)}
    good = {"w": torch.full((4, 4), 0.01), "b": torch.full((4,), 0.01)}
    assert validate_delta(base, good).ok
    assert not validate_delta(base, {"w": good["w"]}).ok
    assert not validate_delta(base, {"w": torch.ones(3, 3), "b": good["b"]}).ok
    assert not validate_delta(base, {"w": torch.full((4, 4), float("nan")), "b": good["b"]}).ok
    assert not validate_delta(base, {"w": torch.full((4, 4), 5.0), "b": good["b"]}).ok
    assert not validate_delta(base, {"w": torch.zeros(4, 4), "b": torch.zeros(4)}).ok


def test_federated_average_weighted():
    d1, d2 = {"w": torch.ones(2)}, {"w": torch.full((2,), 3.0)}
    avg = federated_average([(d1, 1.0), (d2, 3.0)])
    assert torch.allclose(avg["w"], torch.full((2,), 2.5))
    assert torch.allclose(apply_delta({"w": torch.ones(2)}, avg)["w"], torch.full((2,), 3.5))


@pytest.fixture
def coordinator(tmp_path, tiny_model, tiny_pipeline):
    root = tmp_path / "coord"
    init_coordinator(root, tiny_model["dir"], tiny_pipeline["dataset"], shards=3,
                     train=TrainSpec(steps=6, lr=1e-4, batch_size=4, seq_len=64), min_contributions=2)
    return TestClient(create_coordinator_app(root, admin_token="adm")), root


def settings():
    return ParticipationSettings(enabled=True, coordinator_url="http://coord", device="cpu", duty_cycle=1.0)


def test_full_round_two_clients_aggregates_new_version(coordinator):
    http, root = coordinator
    a = CommunityClient(settings(), "client-a", http=http)
    r1 = a.run_round()
    assert r1["accepted"], r1
    assert r1["steps"] == 6 and r1["tokens"] == 6 * 4 * 64
    assert http.get("/v1/info").json()["pending_contributions"] == 1
    b = CommunityClient(settings(), "client-b", http=http)
    r2 = b.run_round()
    assert r2["accepted"] and r2["aggregated"]["version"] == 1, json.dumps(r2)
    info = http.get("/v1/info").json()
    assert info["version"] == 1 and info["round"] == 1
    v1 = info["versions"][1]
    assert v1["parent_sha256"] == info["versions"][0]["sha256"] and v1["contributors"] == ["client-a", "client-b"]
    # the new checkpoint really differs from the base
    w0 = torch.load(root / "versions/v00000/model.pt", weights_only=True)
    w1 = torch.load(root / "versions/v00001/model.pt", weights_only=True)
    assert any(not torch.equal(w0[k], w1[k]) for k in w0)


def test_coordinator_rejects_tampered_and_stale_contributions(coordinator):
    http, root = coordinator
    job = http.get("/v1/jobs/next?client_id=x").json()
    base = torch.load(root / "versions/v00000/model.pt", weights_only=True)

    def submit(delta, **meta_over):
        payload = serialize_state(delta)
        meta = {"job_id": job["job_id"], "round": job["round"], "client_id": "x", "base_sha256": job["base_sha256"],
                "delta_sha256": tensor_bytes_sha256(payload), "tokens": 100, "steps": 1, "loss_before": 1.0,
                "loss_after": 1.0, "protocol": "moth-community/1", **meta_over}
        return http.post("/v1/contributions", content=payload, headers={"x-moth-contribution": json.dumps(meta)}).json()

    small = {k: torch.randn_like(v.float()) * 1e-4 for k, v in base.items()}
    assert "checksum mismatch" in submit(small, delta_sha256="0" * 64)["reasons"]
    assert "contribution is based on an outdated checkpoint" in submit(small, base_sha256="f" * 64)["reasons"]
    assert any("update too large" in r for r in submit({k: v * 1e4 for k, v in small.items()})["reasons"])
    harmful = {k: -v.float() * 0.4 for k, v in base.items()}  # shrinks every weight: loss must not improve
    res = submit(harmful)
    assert not res["accepted"]
    assert http.post("/v1/aggregate").status_code == 401
    assert http.post("/v1/aggregate", headers={"Authorization": "Bearer adm"}).status_code == 409  # nothing pending


def test_client_verifies_downloads(coordinator):
    http, root = coordinator
    (root / "shards" / "shard-0000.bin").write_bytes(b"\x00" * 1024)  # corrupt the data shard
    with pytest.raises(ContributionError, match="checksum"):
        CommunityClient(settings(), "c", http=http).run_round()


def test_community_api_defaults_opt_out(paths):
    from moth.server.app import create_app

    H = {"Authorization": "Bearer t"}
    with TestClient(create_app(paths, token="t")) as c:
        d = c.get("/api/community", headers=H).json()
        assert d["settings"]["enabled"] is False and d["can_contribute"] is False
        assert c.post("/api/community/contribute", headers=H).status_code == 409
        d = c.put("/api/community", json={"enabled": True}, headers=H).json()
        assert "no coordinator" in d["reason"]
        assert c.post("/api/learning/personal/export", json={}, headers=H).status_code == 409


def test_personal_learning_export_uses_only_verified_tasks(paths, tiny_pipeline, tmp_path):
    import numpy as np

    from moth.server.app import create_app
    from moth.training.data import prepare_dataset

    H = {"Authorization": "Bearer t"}
    with TestClient(create_app(paths, token="t")) as c:
        db = c.app.state.services.db
        steps = {"steps": [{"tool": "read_file", "args": {"path": "a.py"}, "thought": "look", "result": "OK\nx"}]}
        for tid, passed in (("good", True), ("bad", False)):
            db.execute("INSERT INTO tasks(id, project_id, goal, status, plan, steps, result, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?,?,?)", (tid, 1, f"goal {tid}", "completed", "[]", json.dumps(steps),
                       json.dumps({"verification": {"ran": True, "passed": passed}, "model_summary": "ok"}), 0, 0))
        out = c.post("/api/learning/personal/export", json={}, headers=H).json()
        assert out["examples"] == 1
    tok = tiny_pipeline["tokenizer"]
    untrusted = tmp_path / "untrusted.jsonl"
    untrusted.write_text(json.dumps({"messages": [{"role": "assistant", "content": "<|tool_call|>{}"}]}) + "\n")
    tc = tok.token_id("<|tool_call|>")
    for spec, expect in ((out["source_spec"], True), (f"jsonl:{untrusted}", False)):
        d = tmp_path / ("ds-" + str(expect))
        prepare_dataset([{"spec": spec, "license": "own-data"}], tok, tiny_pipeline["tokenizer_path"], d, val_fraction=0)
        ids = np.concatenate([np.fromfile(d / f"{s}.bin", dtype=np.uint16) for s in ("train", "val")])
        assert (tc in ids) is expect
