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
