"""Synthetic examples are verified before use: every answer is exactly right, every function passes."""
import re

from moth.datafactory import catalog, synthetic


def test_every_arithmetic_example_is_correct_and_deterministic():
    recs = list(synthetic.generate("arithmetic", 2000, seed=1))
    assert len(recs) == 2000 and recs == list(synthetic.generate("arithmetic", 2000, seed=1))
    ops = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "×": lambda a, b: a * b, "÷": lambda a, b: a / b}
    for r in recs:
        q, a = r["messages"][0]["content"], r["messages"][1]["content"]
        x, s, y = re.search(r"(-?\d+) ([+\-×÷]) (-?\d+)", q).groups()
        assert a.endswith(f"The answer is {int(ops[s](int(x), int(y)))}.")
        assert r["domain"] == "math" and r["messages"][1]["role"] == "assistant"


def test_instructions_are_answered_by_the_operation_itself():
    for r in synthetic.generate("instructions", 500):
        q, a = r["messages"][0]["content"], r["messages"][1]["content"]
        if q.startswith("Write \""):
            assert a == re.search(r'"(\w+)"', q).group(1).upper()
        if q.startswith("Sort these numbers"):
            nums = [int(n) for n in re.findall(r"\d+", q)]
            assert a == ", ".join(map(str, sorted(nums)))
        if q.startswith("Spell"):
            assert a == re.search(r'"(\w+)"', q).group(1)[::-1]


def test_python_examples_run_and_broken_code_is_rejected():
    for task, name, code, tests in synthetic.PY_TASKS:
        assert synthetic.passes(code, name, tests), name
    assert not synthetic.passes("def add(a, b):\n    return a - b", "add", [((2, 3), 5)])
    assert not synthetic.passes("import os\ndef add(a, b):\n    return a + b", "add", [((2, 3), 5)])  # no imports
    recs = list(synthetic.generate("python", 50))
    assert all("```python" in r["messages"][1]["content"] for r in recs)


def test_catalog_lists_the_synthetic_sources_as_cc0():
    ids = {s["id"]: s for s in catalog.SOURCES}
    for k in synthetic.KINDS:
        s = ids[f"synthetic-{k}"]
        assert s["format"] == "synthetic" and s["license"] == "CC0-1.0" and s["files"] == []
