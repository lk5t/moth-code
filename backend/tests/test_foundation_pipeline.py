"""The real scratch pipeline prepares approved data, trains, and safely resumes in place."""
import json
import subprocess
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]


def test_foundation_prepare_train_and_resume_preserve_data_and_lineage(tmp_path):
    args = [sys.executable, str(ROOT / "scripts/train-moth-foundation.py"), "--data", str(tmp_path),
            "--sources", "python-stdlib", "--max-source-chars", "20000", "--vocab-size", "320",
            "--preset", "moth-tiny", "--batch-size", "2", "--grad-accum", "1", "--seq-len", "16",
            "--checkpoint-interval", "1", "--threads", "2", "--device", "cpu"]
    prepared = subprocess.run([*args, "--steps", "2", "--prepare-only"], capture_output=True, text=True, timeout=120)
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    assert '"training_complete": false' in prepared.stdout
    home = tmp_path / "moth-0.1"
    keep = [home / "lineage.json", home / "tokenizer.json", tmp_path / "build-1/tokens/code/train.bin"]
    before = {p: p.read_bytes() for p in keep}
    for steps in (2, 3):
        result = subprocess.run([*args, "--steps", str(steps)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stdout + result.stderr
        ck = torch.load(home / f"run/checkpoints/step_{steps:08d}.pt", weights_only=False)
        assert ck["step"] == steps and ck["tokens_seen"] == steps * 2 * 16
        assert ck["optimizer"]["state"]
        assert all(p.read_bytes() == content for p, content in before.items())
    again = subprocess.run([*args, "--steps", "3", "--prepare-only"], capture_output=True, text=True, timeout=120)
    assert again.returncode == 0, again.stderr
    # An incompatible preparation request must leave completed preparation and training intact.
    changed = [*args]
    changed[changed.index("python-stdlib")] = "dolly-15k"
    bad = subprocess.run([*changed, "--prepare-only"], capture_output=True, text=True, timeout=120)
    assert bad.returncode != 0 and "different sources" in bad.stderr
    assert all(p.read_bytes() == content for p, content in before.items())
