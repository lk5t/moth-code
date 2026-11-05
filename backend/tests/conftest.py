import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moth.config import get_paths  # noqa: E402


@pytest.fixture
def paths(tmp_path):
    return get_paths(tmp_path / "moth-home")


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "README.md").write_text("# Demo\n")
    (root / "pyproject.toml").write_text("[project]\nname='demo'\n")
    pkg = root / "demo"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "math_utils.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("x")
    (root / ".env").write_text("SECRET=1\n")
    return root


CORPUS_SNIPPETS = [
    "def add(a, b):\n    return a + b\n",
    "def subtract(a, b):\n    return a - b\n",
    "def multiply(a, b):\n    return a * b\n",
    "class Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n",
    "for i in range(10):\n    print(i)\n",
    "import os\nimport sys\n\nprint(os.getcwd())\n",
    "The quick brown fox jumps over the lazy dog.\n",
    "MOTH is a coding assistant trained from scratch.\n",
]


@pytest.fixture
def corpus_dir(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    for i in range(40):
        (d / f"file_{i}.py").write_text("\n".join(CORPUS_SNIPPETS[(i + k) % len(CORPUS_SNIPPETS)] for k in range(4)))
    return d


@pytest.fixture
def tiny_pipeline(tmp_path, corpus_dir):
    """Tokenizer + prepared dataset built from the synthetic corpus."""
    from moth.model.tokenizer import train_bpe
    from moth.training.data import prepare_dataset
    from moth.training.sources import SourceSpec, iter_source

    src = SourceSpec(f"dir:{corpus_dir}", license="MIT")
    tok = train_bpe((d.text for d in iter_source(src)), vocab_size=400)
    tok_path = tmp_path / "tok.json"
    tok.save(tok_path)
    ds = tmp_path / "ds"
    meta = prepare_dataset([src], tok, tok_path, ds, val_fraction=0.1)
    return {"tokenizer": tok, "tokenizer_path": tok_path, "dataset": ds, "meta": meta, "source": src}


@pytest.fixture
def tiny_model(tiny_pipeline, tmp_path):
    """A briefly trained and exported moth-tiny model (real training, CPU)."""
    from moth.model.registry import export_model
    from moth.training.trainer import TrainConfig, Trainer

    cfg = TrainConfig(run_name="fx", dataset=str(tiny_pipeline["dataset"]), out_dir=str(tmp_path / "fx-run"),
                      preset="moth-tiny", seq_len=64, batch_size=8, grad_accum=1, max_steps=30, lr=3e-3,
                      warmup_steps=3, eval_interval=10, eval_iters=2, log_interval=10, device="cpu")
    Trainer(cfg).run()
    info = export_model(tmp_path / "fx-run/checkpoints/best.pt", tmp_path / "models", "fx-model", dtype="float32")
    return {"dir": tmp_path / "models" / "fx-model", "models_dir": tmp_path / "models", "info": info}
