"""Real backward probes, unchanged weights/RNG, and persisted training decisions."""
import json

import torch
import pytest

from moth.model.config import preset
from moth.model.transformer import MothModel
from moth.training.autotune import tune_batch
from moth.training.continue_run import run
from test_continue_v053 import _mixture, _spec


def test_real_probes_preserve_weights_rng_and_effective_batch():
    torch.set_num_threads(2)
    model = MothModel(preset("moth-tiny", vocab_size=320))
    before = {k: v.clone() for k, v in model.state_dict().items()}
    rng = torch.get_rng_state().clone()
    def sample(b):
        ids = torch.randint(0, 320, (b, 17))
        return ids[:, :-1], ids[:, 1:], None
    result = tune_batch(model, 4, 2, sample, "cpu")
    assert result["batch_size"] * result["grad_accum"] == 8
    assert all(t["tokens_per_second"] > 0 for t in result["trials"] if t["ok"])
    assert torch.equal(rng, torch.get_rng_state())
    assert all(torch.equal(before[k], v) for k, v in model.state_dict().items())
    assert all(p.grad is None for p in model.parameters())


def test_autotuned_training_resumes_without_reprobing(tmp_path, monkeypatch):
    mix, base = _mixture(tmp_path)
    spec = _spec(tmp_path, "tuned", mix, base, steps=3)
    first = run(spec)
    ck = torch.load(first["dev_checkpoint"], weights_only=False)
    tuning = ck["batch_tuning"]
    assert tuning["effective_batch_size"] == 4 and ck["tokens_seen"] == 3 * 4 * 32
    import moth.training.autotune as at
    monkeypatch.setattr(at, "tune_batch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("retuned on resume")))
    second = run({**spec, "steps": 5})
    ck2 = torch.load(second["dev_checkpoint"], weights_only=False)
    assert second["resumed"] and ck2["batch_tuning"] == tuning
    assert ck2["tokens_seen"] == 5 * 4 * 32
    assert ck2["optimizer"]["state"]
    assert json.loads((tmp_path / "tuned" / "events.jsonl").read_text().splitlines()[0])["batch_tuning"] == tuning


def test_continued_training_can_disable_batch_probes(tmp_path):
    mix, base = _mixture(tmp_path)
    result = run(_spec(tmp_path, "manual", mix, base, steps=2, batch_autotune=False))
    checkpoint = torch.load(result["dev_checkpoint"], weights_only=False)
    assert result["reason"] == "completed" and result["batch_tuning"] is None
    assert checkpoint["tokens_seen"] == 2 * 4 * 32 and checkpoint["batch_tuning"] is None


def test_no_random_restart_when_every_resumable_checkpoint_is_damaged(tmp_path):
    mix, base = _mixture(tmp_path)
    spec = _spec(tmp_path, "protected", mix, base, steps=2)
    result = run(spec)
    checkpoint = tmp_path / "protected" / "checkpoints" / "step_00000002.pt"
    checkpoint.write_bytes(b"damaged")
    best = (checkpoint.parent / "best.pt").read_bytes()
    for _ in range(2):
        with pytest.raises(ValueError, match="refusing to restart"):
            run({**spec, "steps": 3})
    assert checkpoint.with_name(checkpoint.name + ".corrupt").exists()
    assert (checkpoint.parent / "best.pt").read_bytes() == best
