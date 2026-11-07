"""Checkpoint integrity: corrupted checkpoints are detected and skipped; one trainer per run directory."""

import json

import pytest

from moth.training.checkpoint import CheckpointError, RunLock, load_latest_verified, save_checkpoint


def test_corrupted_latest_falls_back_to_previous_verified(tmp_path):
    for step in (1, 2, 3):
        save_checkpoint(tmp_path, step, {"step": step, "w": [step] * 100})
    latest = tmp_path / "checkpoints" / "step_00000003.pt"
    data = bytearray(latest.read_bytes())
    data[len(data) // 2] ^= 0xFF  # flip one byte: the SHA-256 no longer matches
    latest.write_bytes(bytes(data))
    warnings = []
    path, ck = load_latest_verified(tmp_path, on_event=lambda k, **d: warnings.append(d["message"]))
    assert ck["step"] == 2 and path.name == "step_00000002.pt"
    assert (tmp_path / "checkpoints" / "step_00000003.pt.corrupt").exists() and warnings
    assert json.loads((tmp_path / "checkpoints" / "latest.json").read_text())["sha256"]


def test_run_lock_prevents_concurrent_trainers(tmp_path):
    with RunLock(tmp_path, "worker-a"):
        lock = json.loads((tmp_path / "run.lock").read_text())
        assert lock["owner"] == "worker-a"
        # a second trainer in another process would be refused; simulate with a live foreign pid
        (tmp_path / "run.lock").write_text(json.dumps({"pid": 1, "owner": "worker-b"}))
        with pytest.raises(CheckpointError, match="worker-b"):
            RunLock(tmp_path, "worker-c").__enter__()
        (tmp_path / "run.lock").write_text(json.dumps(lock))
    assert not (tmp_path / "run.lock").exists()
    # a stale lock of a dead process is taken over
    (tmp_path / "run.lock").write_text(json.dumps({"pid": 999_999_999, "owner": "dead"}))
    with RunLock(tmp_path, "new"):
        pass
