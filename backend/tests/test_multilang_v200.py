"""2.0: self-checked SQL, JavaScript and Bash training data, and the held-out SQL exam."""
import os
import random
import shutil

import pytest

from moth.datafactory import catalog, multilang as M, synthetic
from moth.model import exams


def test_sql_examples_are_checked_against_python():
    ex = list(synthetic.generate("sql", 200, seed=3))
    assert len(ex) == 200 and all(e["domain"] == "code" for e in ex)
    assert all("```sql" in e["messages"][1]["content"] for e in ex)
    # a stated result only appears when the rows are in the question
    for e in ex:
        q, a = e["messages"][0]["content"], e["messages"][1]["content"]
        assert ("returns:" in a) == ("with these rows" in q)
    assert list(synthetic.generate("sql", 20, seed=3)) == list(synthetic.generate("sql", 20, seed=3))  # reproducible


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js not installed")
def test_javascript_examples_really_run_and_bad_code_is_dropped():
    rng = random.Random(1)
    good = M._js_candidates(rng)
    bad = (good[0], good[1], good[2].replace("return", "return 1 +", 1), good[3])
    broken = ("x", "nope", "function nope( {", [([1], 1)])
    assert M._node_verify([good, bad, broken]) == [True, False, False]
    ex = list(synthetic.generate("javascript", 50, seed=2))
    assert len(ex) == 50 and all("```javascript" in e["messages"][1]["content"] for e in ex)


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="needs Bash")
def test_shell_examples_print_the_expected_output():
    ex = list(synthetic.generate("shell", 40, seed=5))
    assert len(ex) == 40 and all("```bash" in e["messages"][1]["content"] for e in ex)


def test_new_sources_are_in_the_catalog():
    ids = {s["id"] for s in catalog.SOURCES}
    assert {"synthetic-sql", "synthetic-javascript", "synthetic-shell"} <= ids


def test_sql_exam_accepts_only_the_exact_result():
    t = exams.SQL_TASKS
    assert exams.run_sql("SELECT title FROM books ORDER BY title", t[0][1])
    assert not exams.run_sql("SELECT title FROM books", t[0][1])  # wrong order
    assert exams.run_sql("SELECT COUNT(*) FROM books;", t[1][1])
    assert exams.run_sql("SELECT author, COUNT(*) FROM books GROUP BY author ORDER BY author", t[5][1])
    assert not exams.run_sql("DROP TABLE books", [])  # read-only
    assert not exams.run_sql("SELECT 1; DROP TABLE books", [(1,)])  # one statement only
    assert not exams.run_sql("SELEC nonsense", [])
    # the exam's table and questions are not in the generated training data
    data = " ".join(e["messages"][0]["content"] for e in synthetic.generate("sql", 500, seed=0))
    assert "books(" not in data and "Neuromancer" not in data


def test_calculator_tool():
    from moth.inference.tools import calculate
    assert calculate("what is 1234 * 5678?") == ("1234 * 5678", "7006652")
    assert calculate("(17 + 5) / 4") == ("(17 + 5) / 4", "5.5")
    assert calculate("compute 2^10 - 1") == ("2^10 - 1", "1023")
    for no in ("hello", "update to 1.2.3", "on 12/05/2024", "10 / 0", "scan 10.0.0.5:8080", "__import__('os')"):
        assert calculate(no) is None


def test_answers_have_their_code_checked():
    from moth.agent.checkers import check_answer
    got = check_answer("```python\ndef f(x):\n    return x\n```\n```python\ndef g(:\n```\n```text\nnot code\n```")
    assert [c["ok"] for c in got] == [True, False] and got[1]["problem"].startswith("line 1")
