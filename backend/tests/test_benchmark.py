"""Deterministic benchmark helpers (moth.model.benchmark)."""

from moth.model.benchmark import _parses
from moth.model.release_criteria import check
import pytest


def test_code_syntax_scores_only_real_python():
    assert _parses("def add(a, b):\n", "    return a + b\n")
    assert _parses("def add(a, b):\n", "    return a + b\nprint(add(1, 2))\n")  # stops at the block's end
    assert _parses("def f(x):\n", "    y = x * 2\n    return y\n    retu")  # last line cut by the token limit
    assert not _parses("def add(a, b):\n", "return a + b\n")  # no indented body
    assert not _parses("def add(a, b):\n", "    return a +\n    ) (\n")
    assert not _parses("def add(a, b):\n", "\n\n")
    assert _parses("class Stack:\n    def __init__(self):\n", "        self.items = []\n")


@pytest.mark.parametrize("suite,op,value", [("holdout:language", "<=", float("-inf")),
                                          ("performance", ">=", float("inf")),
                                          ("instruction", ">=", float("nan"))])
def test_release_criteria_reject_nonfinite_measurements(suite, op, value):
    report = {"suites": {suite: {"value": value, "ok": True}},
              "performance": {"tokens_per_second": value}}
    result = check(report, [{"id": "invalid", "suite": suite, "op": op, "value": 1.0}])
    assert not result["passed"]
    assert result["criteria"][0]["measured"] is None
