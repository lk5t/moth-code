"""Coding curriculum and held-out coding tasks (0.8.0), every example verified by execution.

Training kinds (from ``synthetic.PY_TASKS``):

* ``debugging`` — a working function gets one realistic bug (wrong operator, off-by-one, wrong
  comparison, wrong return). The example is kept only if the buggy version still parses **and fails**
  its tests while the original **passes** them; the answer names the faulty line and gives the fix.
* ``code_explain`` — "explain this function": what it does, its inputs and a worked example whose
  result was computed by running the function.
* ``test_writing`` — "write tests": assertions derived from executed results, then run against the
  function before the example is kept.

``EVAL_TASKS`` are different functions (never in training) used by the code-generation and debugging
benchmarks; their tests run in a separate, resource-limited Python process
(``moth.model.capabilities._run_tests``).
"""

from __future__ import annotations

import difflib
import random
import re
from typing import Any, Iterator

from moth.datafactory.synthetic import PY_TASKS, SAFE_BUILTINS, passes

MUTATIONS = [(r" \+ ", " - "), (r" - ", " + "), (r" < ", " > "), (r" > ", " < "), (r"== 0", "== 1"),
             (r"range\(2, n \+ 1\)", "range(2, n)"), (r"\[::-1\]", "[::1]"), (r"return best", "return numbers[0]"),
             (r"a, b = b, a \+ b", "a, b = b, a"), (r"s \+= n", "s = n"), (r"result \*= i", "result += i"),
             (r"seen\.add\(x\)", "pass"), (r"in \"aeiou\"", "in \"aeio\""), (r"not in seen", "in seen"),
             (r" \* ", " + "), (r"% 2 == 0", "% 2 == 1"), (r"if n < 2", "if n < 1"), (r"a % b", "b % a"),
             (r"capitalize\(\)", "lower()"), (r"range\(1, len", "range(2, len"), (r"/ len\(numbers\)", "/ 2"),
             (r"text\.split\(\)\)", "text)"), (r"total \+= n \* n", "total += n")]

EVAL_TASKS: list[tuple[str, str, str, list[tuple[tuple, Any]]]] = [
    ("return the product of two numbers", "multiply", "def multiply(a, b):\n    return a * b", [((3, 4), 12), ((0, 9), 0)]),
    ("return the smallest number in a list", "smallest",
     "def smallest(numbers):\n    best = numbers[0]\n    for n in numbers[1:]:\n        if n < best:\n            best = n\n    return best",
     [(([4, 1, 7],), 1), (([-3, -8],), -8)]),
    ("count the words in a sentence", "count_words", "def count_words(text):\n    return len(text.split())",
     [(("a b c",), 3), (("",), 0)]),
    ("return the sum of the squares of a list of numbers", "sum_of_squares",
     "def sum_of_squares(numbers):\n    total = 0\n    for n in numbers:\n        total += n * n\n    return total",
     [(([1, 2, 3],), 14), (([],), 0)]),
    ("check whether a number is prime", "is_prime",
     "def is_prime(n):\n    if n < 2:\n        return False\n    for i in range(2, n):\n        if n % i == 0:\n            return False\n    return True",
     [((7,), True), ((8,), False), ((1,), False)]),
    ("return the greatest common divisor of two numbers", "gcd",
     "def gcd(a, b):\n    while b:\n        a, b = b, a % b\n    return a", [((12, 18), 6), ((7, 5), 1)]),
    ("return the index of the largest number in a list", "max_index",
     "def max_index(numbers):\n    best = 0\n    for i in range(1, len(numbers)):\n        if numbers[i] > numbers[best]:\n            best = i\n    return best",
     [(([3, 9, 2],), 1), (([5],), 0)]),
    ("return a string with every word capitalized", "title_words",
     "def title_words(text):\n    return \" \".join(w.capitalize() for w in text.split())",
     [(("hello world",), "Hello World"), (("moth",), "Moth")]),
    ("count how many numbers in a list are even", "count_even",
     "def count_even(numbers):\n    return sum(1 for n in numbers if n % 2 == 0)", [(([1, 2, 4],), 2), (([],), 0)]),
    ("return the average of a non-empty list of numbers", "average",
     "def average(numbers):\n    return sum(numbers) / len(numbers)", [(([2, 4],), 3.0), (([5],), 5.0)]),
]


def _call(name: str, args: tuple) -> str:
    return f"{name}({', '.join(map(repr, args))})"


def inject_bug(code: str, name: str, tests: list, rng: random.Random) -> str | None:
    """A buggy variant that still parses and fails its tests (None if no mutation applies)."""
    import ast

    options = [(p, r) for p, r in MUTATIONS if re.search(p, code)]
    rng.shuffle(options)
    for pat, rep in options:
        buggy = re.sub(pat, rep, code, count=1)
        try:
            ast.parse(buggy)
        except SyntaxError:
            continue
        if buggy != code and not passes(buggy, name, tests):
            return buggy
    return None


def _changed_line(a: str, b: str) -> tuple[str, str]:
    for x, y in zip(a.splitlines(), b.splitlines()):
        if x != y:
            return x.strip(), y.strip()
    return "", ""


def debugging(rng: random.Random, tasks=PY_TASKS) -> tuple[str, str] | None:
    task, name, code, tests = rng.choice(tasks)
    if not passes(code, name, tests):
        return None
    buggy = inject_bug(code, name, tests, rng)
    if buggy is None:
        return None
    wrong, right = _changed_line(buggy, code)
    args, want = tests[0]
    q = (f"This function should {task}, but it does not work:\n```python\n{buggy}\n```\n"
         + rng.choice(["Find and fix the bug.", "What is wrong, and how do I fix it?", "Please fix it."]))
    a = (f"The bug is in this line:\n```python\n{wrong}\n```\nIt should be:\n```python\n{right}\n```\n"
         f"Here is the corrected function:\n```python\n{code}\n```\nNow `{_call(name, args)}` returns `{want!r}`.")
    return q, a


def code_explain(rng: random.Random) -> tuple[str, str] | None:
    task, name, code, tests = rng.choice(PY_TASKS)
    ns: dict[str, Any] = {"__builtins__": SAFE_BUILTINS}
    try:
        exec(compile(code, "<explain>", "exec"), ns)  # noqa: S102 — MOTH's own templates
        args, _ = tests[0]
        got = ns[name](*args)
    except Exception:  # noqa: BLE001
        return None
    params = re.search(r"def \w+\(([^)]*)\)", code).group(1)
    q = rng.choice(["Explain what this function does:", "What does this code do?", "Can you explain this function?"]) \
        + f"\n```python\n{code}\n```"
    a = (f"`{name}` is a function that can {task}. It takes {('`' + params + '`') if params else 'no arguments'} "
         f"and returns the result. For example, `{_call(name, args)}` returns `{got!r}`.")
    return q, a


def test_writing(rng: random.Random) -> tuple[str, str] | None:
    task, name, code, tests = rng.choice(PY_TASKS)
    lines = [f"    assert {_call(name, args)} == {want!r}" for args, want in tests]
    test_code = f"def test_{name}():\n" + "\n".join(lines)
    ns: dict[str, Any] = {"__builtins__": {**SAFE_BUILTINS, "AssertionError": AssertionError}}
    try:
        exec(compile(code + "\n\n" + test_code + f"\n\ntest_{name}()\n", "<tests>", "exec"), ns)  # noqa: S102
    except Exception:  # noqa: BLE001 — the tests must pass against the function
        return None
    q = f"Write tests for this function:\n```python\n{code}\n```"
    a = f"```python\n{test_code}\n```\nEach assertion checks a result of `{name}` that was computed by running it."
    return q, a


GENERATORS = {"debugging": debugging, "code_explain": code_explain, "test_writing": test_writing}


def eval_items(kind: str) -> list[dict[str, Any]]:
    """Held-out benchmark items: ``codegen`` (write the function) or ``debugging`` (fix a planted bug)."""
    out = []
    rng = random.Random("coding-eval")
    for task, name, code, tests in EVAL_TASKS:
        test_lines = [f"assert {_call(name, args)} == {want!r}" for args, want in tests]
        if kind == "codegen":
            out.append({"prompt": f"Write a Python function named `{name}` that can {task}.", "tests": test_lines,
                        "name": name})
        else:
            buggy = inject_bug(code, name, tests, rng)
            if buggy:
                out.append({"prompt": f"This function should {task}, but it does not work:\n```python\n{buggy}\n```\n"
                                      "Fix the bug and show the corrected function.", "tests": test_lines, "name": name})
    return out


def generate(kind: str, n: int, seed: int = 0, source_id: str | None = None) -> Iterator[dict[str, Any]]:
    rng = random.Random(f"coding:{kind}:{seed}")
    sid = source_id or f"synthetic-{kind.replace('_', '-')}"
    made = tries = 0
    while made < n and tries < n * 6:
        tries += 1
        ex = GENERATORS[kind](rng)
        if ex is None:
            continue
        q, a = ex
        yield {"uid": f"{sid}:{made}", "source": sid, "domain": "code",
               "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]}
        made += 1
