"""Deterministic benchmark helpers (moth.model.benchmark)."""

from moth.model.benchmark import _parses


def test_code_syntax_scores_only_real_python():
    assert _parses("def add(a, b):\n", "    return a + b\n")
    assert _parses("def add(a, b):\n", "    return a + b\nprint(add(1, 2))\n")  # stops at the block's end
    assert _parses("def f(x):\n", "    y = x * 2\n    return y\n    retu")  # last line cut by the token limit
    assert not _parses("def add(a, b):\n", "return a + b\n")  # no indented body
    assert not _parses("def add(a, b):\n", "    return a +\n    ) (\n")
    assert not _parses("def add(a, b):\n", "\n\n")
    assert _parses("class Stack:\n    def __init__(self):\n", "        self.items = []\n")
