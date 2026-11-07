import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from moth.model.chat_format import Message, encode_chat
from moth.model.registry import export_model, list_models, load_model
from moth.training.data import TokenDataset, prepare_dataset
from moth.training.evaluate import evaluate_model
from moth.training.sources import LicenseError, SourceSpec
from moth.training.trainer import TrainConfig, Trainer, lr_at


@pytest.mark.parametrize('platform,amx,bf16,expected', [
    ('win32', True, True, False),
    ('linux', True, False, True),
    ('linux', False, True, True),
    ('linux', False, False, False),
])
def test_automatic_cpu_precision_respects_runtime_support(monkeypatch, platform, amx, bf16, expected):
    from moth.training import trainer as training

    with monkeypatch.context() as patch:
        patch.setattr(training.sys, 'platform', platform)
        patch.setattr(torch.cpu, '_is_amx_tile_supported', lambda: amx, raising=False)
        patch.setattr(torch.cpu, '_is_avx512_bf16_supported', lambda: bf16, raising=False)
        assert training.cpu_has_fast_bf16() is expected
        trainer = Trainer.__new__(Trainer)
        trainer.cfg, trainer.device = TrainConfig(), 'cpu'
        assert trainer._precision() == (torch.bfloat16 if expected else None, False)


def test_windows_cpu_fallback_preserves_cuda_precision(monkeypatch):
    from moth.training import trainer as training

    with monkeypatch.context() as patch:
        patch.setattr(training.sys, 'platform', 'win32')
        patch.setattr(torch.cuda, 'is_bf16_supported', lambda: True)
        trainer = Trainer.__new__(Trainer)
        trainer.cfg, trainer.device = TrainConfig(), 'cuda'
        assert trainer._precision() == (torch.bfloat16, False)


def cfg(pipeline, out, **kw):
    base = dict(run_name="t", dataset=str(pipeline["dataset"]), out_dir=str(out), preset="moth-tiny",
                seq_len=64, batch_size=8, grad_accum=1, max_steps=60, lr=3e-3, min_lr=3e-4, warmup_steps=5,
                eval_interval=20, eval_iters=4, log_interval=5, checkpoint_interval=1000, device="cpu", seed=7)
    base.update(kw)
    return TrainConfig.from_dict(base)


def test_dataset_preparation(tiny_pipeline):
    meta = tiny_pipeline["meta"]
    assert meta["tokens"]["train"] > 1000 and meta["tokens"]["val"] > 0
    assert meta["sources"][0]["license"] == "MIT"
    ds = TokenDataset(tiny_pipeline["dataset"], "train", 32)
    x, y, m = ds.batch(4, torch.Generator().manual_seed(0))
    assert x.shape == (4, 32) and torch.equal(x[:, 1:], y[:, :-1]) and m.sum() > 0


def test_undeclared_license_is_rejected(tmp_path, corpus_dir, tiny_pipeline):
    with pytest.raises(LicenseError):
        prepare_dataset([SourceSpec(f"dir:{corpus_dir}")], tiny_pipeline["tokenizer"],
                        tiny_pipeline["tokenizer_path"], tmp_path / "x")


def test_chat_loss_mask(tiny_pipeline):
    tok = tiny_pipeline["tokenizer"]
    ids, mask = encode_chat(tok, [Message("user", "hi"), Message("assistant", "hello")], add_generation_prompt=False)
    learned = tok.decode([i for i, m in zip(ids, mask) if m])
    assert learned == "hello"


def test_lr_schedule():
    c = TrainConfig(lr=1.0, min_lr=0.1, warmup_steps=10, max_steps=110)
    assert lr_at(0, c) == pytest.approx(0.1)
    assert lr_at(9, c) == pytest.approx(1.0)
    assert lr_at(60, c) == pytest.approx(0.55)
    assert lr_at(500, c) == pytest.approx(0.1)


def test_training_reduces_loss_and_checkpoints(tiny_pipeline, tmp_path):
    events = []
    result = Trainer(cfg(tiny_pipeline, tmp_path / "run"), on_event=events.append).run()
    train_losses = [e["loss"] for e in events if e["kind"] == "metrics" and e["split"] == "train"]
    val_losses = [e["loss"] for e in events if e["kind"] == "metrics" and e["split"] == "val"]
    assert result["step"] == 60 and result["reason"] == "completed"
    assert train_losses[-1] < train_losses[0] * 0.6, (train_losses[0], train_losses[-1])
    assert val_losses[-1] < val_losses[0]
    ckpts = tmp_path / "run" / "checkpoints"
    assert (ckpts / "best.pt").exists() and (ckpts / "latest.json").exists()
    # metrics also persisted to disk
    assert len((tmp_path / "run" / "events.jsonl").read_text().splitlines()) == len(events)


def test_resume_reproduces_uninterrupted_run(tiny_pipeline, tmp_path):
    torch.use_deterministic_algorithms(True)
    try:
        Trainer(cfg(tiny_pipeline, tmp_path / "a", max_steps=30)).run()
        # Same run, interrupted at step 12 then resumed.
        stop_at = {"n": 0}

        def stopper():
            return stop_at["n"] >= 12

        t = Trainer(cfg(tiny_pipeline, tmp_path / "b", max_steps=30),
                    on_event=lambda e: stop_at.__setitem__("n", e["step"]), should_stop=stopper)
        r1 = t.run()
        assert r1["reason"] == "stopped" and 12 <= r1["step"] < 30
        r2 = Trainer(cfg(tiny_pipeline, tmp_path / "b", max_steps=30)).run()
        assert r2["step"] == 30
        a = torch.load(tmp_path / "a/checkpoints/step_00000030.pt", weights_only=False)["model"]
        b = torch.load(tmp_path / "b/checkpoints/step_00000030.pt", weights_only=False)["model"]
        for k in a:
            assert torch.equal(a[k], b[k]), k
    finally:
        torch.use_deterministic_algorithms(False)


def test_stop_file_stops_training(tiny_pipeline, tmp_path):
    out = tmp_path / "run"
    out.mkdir()
    (out / "STOP").touch()
    r = Trainer(cfg(tiny_pipeline, out)).run()
    assert r["reason"] == "stopped" and r["step"] == 0
    assert not (out / "STOP").exists()


def test_export_load_generate_and_evaluate(tiny_pipeline, tmp_path):
    Trainer(cfg(tiny_pipeline, tmp_path / "run", max_steps=40)).run()
    info = export_model(tmp_path / "run/checkpoints/best.pt", tmp_path / "models", "moth-test", dtype="float32")
    assert info["params"] > 0 and info["training"]["sources"][0]["license"] == "MIT"
    assert [m["id"] for m in list_models(tmp_path / "models")] == ["moth-test"]
    model, tok, manifest = load_model(tmp_path / "models/moth-test")
    report = evaluate_model(model, tok, str(tiny_pipeline["dataset"]), batches=3)
    assert 0 < report.val_loss < 10 and 0 <= report.next_token_accuracy <= 1
    assert report.code_total > 0 and len(report.samples) > 0
    # Corruption is detected.
    with open(tmp_path / "models/moth-test/model.pt", "r+b") as f:
        f.seek(200)
        f.write(b"\x00\x01\x02\x03")
    with pytest.raises(ValueError, match="checksum"):
        load_model(tmp_path / "models/moth-test")


def test_cli_end_to_end(tmp_path, corpus_dir):
    env_py = [sys.executable, "-m", "moth.cli"]
    cwd = Path(__file__).resolve().parents[1]
    src = json.dumps({"spec": f"dir:{corpus_dir}", "license": "MIT"})

    def run(*args):
        p = subprocess.run([*env_py, "--json-events", *args], cwd=cwd, capture_output=True, text=True, timeout=600)
        events = [json.loads(l[6:]) for l in p.stdout.splitlines() if l.startswith("@moth ")]
        assert p.returncode == 0, p.stdout + p.stderr
        return events

    ev = run("tokenizer", "--source", src, "--vocab-size", "400", "--out", str(tmp_path / "tok.json"))
    assert ev[-1]["kind"] == "done"
    run("prepare", "--source", src, "--tokenizer", str(tmp_path / "tok.json"), "--out", str(tmp_path / "ds"))
    conf = {"run_name": "cli", "dataset": str(tmp_path / "ds"), "out_dir": str(tmp_path / "run"),
            "preset": "moth-tiny", "seq_len": 64, "batch_size": 4, "grad_accum": 1, "max_steps": 15,
            "warmup_steps": 2, "eval_interval": 5, "eval_iters": 2, "log_interval": 5, "device": "cpu"}
    (tmp_path / "train.json").write_text(json.dumps(conf))
    ev = run("train", "--config", str(tmp_path / "train.json"))
    assert ev[-1] == {**ev[-1], "kind": "done", "step": 15}
    run("export", "--checkpoint", str(tmp_path / "run/checkpoints/best.pt"), "--models-dir", str(tmp_path / "m"),
        "--name", "cli-model")
    p = subprocess.run([*env_py, "generate", "--model", str(tmp_path / "m/cli-model"), "--prompt", "def ",
                        "--max-new-tokens", "10"], cwd=cwd, capture_output=True, text=True, timeout=120)
    assert p.returncode == 0, p.stderr
