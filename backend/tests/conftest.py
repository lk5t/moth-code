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
