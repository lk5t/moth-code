"""Checkpoint integrity: corrupted checkpoints are detected and skipped; one trainer per run directory."""

import json
from pathlib import Path

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
    """A second trainer (another process) is refused while the first holds the run; when the holder dies
    — even killed — the run can be taken over immediately."""
    import subprocess
    import sys
    import time

    holder = subprocess.Popen([sys.executable, "-c", (
        "import sys, time; sys.path.insert(0, %r)\n"
        "from moth.training.checkpoint import RunLock\n"
        "with RunLock(%r, 'worker-b'):\n    print('locked', flush=True); time.sleep(60)\n")
        % (str(Path(__file__).resolve().parents[1]), str(tmp_path))], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(CheckpointError, match="worker-b"):
            RunLock(tmp_path, "worker-c").__enter__()
    finally:
        holder.kill()
        holder.wait()
    time.sleep(0.2)
    with RunLock(tmp_path, "new"):  # the killed holder's lock is gone
        pass


def test_retention_keeps_newest_and_milestones(tmp_path):
    for step in range(1, 11):
        save_checkpoint(tmp_path, step, {"step": step}, keep=2, keep_every=4)
    names = sorted(p.name for p in (tmp_path / "checkpoints").glob("step_*.pt"))
    assert names == ["step_00000004.pt", "step_00000008.pt", "step_00000009.pt", "step_00000010.pt"]
