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


def test_consistency_requires_both_reference_answers(tmp_path,monkeypatch):
    """Evaluator contract test with deterministic supplied completions; not a quality claim."""
    import json
    from moth.model import benchmark as bench
    path=tmp_path/'pairs.jsonl'
    path.write_text(json.dumps({'prompt':'2+2?','paraphrase':'Sum two and two','answer':'4'})+'\n')
    replies=iter(['4','5']);monkeypatch.setattr(bench,'_complete',lambda *args:(next(replies),None))
    assert bench.tasks_suite(None,None,path)['value']==0
    replies=iter(['4','4'])
    assert bench.tasks_suite(None,None,path)['value']==1


def test_a_suite_that_cannot_run_is_not_measurable_instead_of_failing_everything(monkeypatch, tmp_path):
    """2.2.2: the JavaScript exam without Node.js returned no value and failed every evaluation."""
    from moth.model import benchmark as BM
    from moth.model import capabilities, registry

    monkeypatch.setattr(registry, "load_model", lambda *a, **k: (None, None, {"sha256": "x", "params": 1}))
    calls = {"codegen_js": {"ok": False, "error": "Node.js is not installed on this computer"},
             "security": {"metric": "accuracy", "value": 0.25, "n": 20, "higher_is_better": True}}

    def run_suite(model, tok, spec):
        if spec["capability"] == "boom":
            raise KeyError("value")
        return dict(calls[spec["capability"]])

    monkeypatch.setattr(capabilities, "run_suite", run_suite)
    monkeypatch.setattr(BM, "_complete", lambda *a, **k: (None, type("S", (), {"generated_tokens": 0})()))
    out = BM.run(tmp_path, [{"id": c, "kind": "capability", "capability": c} for c in ("codegen_js", "security", "boom")])
    s = out["suites"]
    assert s["codegen_js"]["ok"] is False and "Node.js" in s["codegen_js"]["error"]
    assert s["security"]["ok"] is True and s["security"]["value"] == 0.25
    assert s["boom"]["ok"] is False and "KeyError" in s["boom"]["error"]
