"""2.0: self-checked training examples in more languages: SQL, JavaScript and Bash.

Every example is run before it is kept, so a wrong one never reaches training:

* ``sql`` — a small table with random rows and a question about it; the query runs in an in-memory SQLite
  database and its result must equal the answer computed separately in Python.
* ``javascript`` — a function for a task with random parameters; Node.js runs it against tests (all examples
  of a batch in one isolated, time-limited process) and only passing ones are kept. Without Node.js on this
  computer no JavaScript examples are made.
* ``shell`` — a Bash one-liner for a file task; it runs in a temporary directory with prepared files and its
  output must equal the expected output. Not generated on Windows or without Bash.

All examples are MOTH's own templates (CC0); deterministic for a seed.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterator

KINDS = ("sql", "javascript", "shell")
NAMES = ["Ada", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivo", "June", "Kai", "Lena", "Milo", "Nora"]
CITIES = ["Oslo", "Lima", "Cairo", "Perth", "Quito", "Rome", "Seoul", "Turin"]
PRODUCTS = ["lamp", "desk", "chair", "pen", "mug", "book", "fan", "clock"]


def _msgs(q: str, a: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": q}, {"role": "assistant", "content": a}]


def _env() -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG")
    return {k: v for k, v in os.environ.items() if k in keep}


# ---- SQL ---------------------------------------------------------------------------------------------------

def _table(rng: random.Random):
    kind = rng.choice(["employees", "orders"])
    if kind == "employees":
        cols = [("name", "TEXT"), ("city", "TEXT"), ("age", "INTEGER"), ("salary", "INTEGER")]
        rows = [(n, rng.choice(CITIES), rng.randint(20, 65), rng.randrange(30, 120) * 1000)
                for n in rng.sample(NAMES, rng.randint(4, 8))]
    else:
        cols = [("id", "INTEGER"), ("product", "TEXT"), ("quantity", "INTEGER"), ("price", "INTEGER")]
        rows = [(i + 1, rng.choice(PRODUCTS), rng.randint(1, 9), rng.randint(2, 60)) for i in range(rng.randint(4, 9))]
    return kind, cols, rows


def _sql_task(rng: random.Random, kind: str, cols, rows):
    """(question, query, expected rows computed in Python)."""
    if kind == "employees":
        city = rng.choice([r[1] for r in rows])
        age = rng.randint(25, 55)
        n = rng.randint(1, 3)
        return rng.choice([
            (f"List the names of the employees who live in {city}, in alphabetical order.",
             f"SELECT name FROM employees WHERE city = '{city}' ORDER BY name;",
             sorted([(r[0],) for r in rows if r[1] == city])),
            (f"How many employees are older than {age}?",
             f"SELECT COUNT(*) FROM employees WHERE age > {age};", [(sum(1 for r in rows if r[2] > age),)]),
            (f"Show the {n} highest-paid employees with their salaries.",
             f"SELECT name, salary FROM employees ORDER BY salary DESC, name LIMIT {n};",
             [(r[0], r[3]) for r in sorted(rows, key=lambda r: (-r[3], r[0]))[:n]]),
            ("What is the average age of the employees in each city? Sort by city.",
             "SELECT city, AVG(age) FROM employees GROUP BY city ORDER BY city;",
             [(c, sum(r[2] for r in rows if r[1] == c) / sum(1 for r in rows if r[1] == c)) for c in sorted({r[1] for r in rows})]),
        ])
    prod = rng.choice([r[1] for r in rows])
    q = rng.randint(2, 6)
    return rng.choice([
        (f"What is the total quantity ordered of {prod}?",
         f"SELECT SUM(quantity) FROM orders WHERE product = '{prod}';", [(sum(r[2] for r in rows if r[1] == prod),)]),
        ("Show each product with its total revenue (quantity × price), highest first.",
         "SELECT product, SUM(quantity * price) AS revenue FROM orders GROUP BY product ORDER BY revenue DESC, product;",
         sorted([(p, sum(r[2] * r[3] for r in rows if r[1] == p)) for p in {r[1] for r in rows}], key=lambda x: (-x[1], x[0]))),
        (f"List the ids of orders with a quantity of at least {q}.",
         f"SELECT id FROM orders WHERE quantity >= {q} ORDER BY id;", [(r[0],) for r in rows if r[2] >= q]),
        ("How many different products were ordered?", "SELECT COUNT(DISTINCT product) FROM orders;", [(len({r[1] for r in rows}),)]),
    ])


def sql_example(rng: random.Random) -> tuple[str, str] | None:
    kind, cols, rows = _table(rng)
    question, query, want = _sql_task(rng, kind, cols, rows)
    db = sqlite3.connect(":memory:")
    try:
        db.execute(f"CREATE TABLE {kind} ({', '.join(f'{c} {t}' for c, t in cols)})")
        db.executemany(f"INSERT INTO {kind} VALUES ({', '.join('?' * len(cols))})", rows)
        got = db.execute(query).fetchall()
    except sqlite3.Error:
        return None
    finally:
        db.close()
    norm = lambda rs: [tuple(round(v, 6) if isinstance(v, float) else v for v in r) for r in rs]  # noqa: E731
    if norm(got) != norm(want):
        return None
    schema = f"{kind}({', '.join(c for c, _ in cols)})"
    fmt = lambda v: f"{v:g}" if isinstance(v, float) else str(v)  # noqa: E731
    data = "\n".join(", ".join(map(str, r)) for r in rows)
    shown = "; ".join(", ".join(fmt(v) for v in r) for r in got[:8])
    if rng.random() < 0.5:  # with the rows: the answer can state the result, which was computed and checked
        return (f"I have a table {schema} with these rows:\n{data}\n\n{question}",
                f"```sql\n{query}\n```\n\nOn these rows it returns: {shown or 'no rows'}.")
    return f"I have a table {schema}. {question} Write the SQL query.", f"```sql\n{query}\n```"


# ---- JavaScript --------------------------------------------------------------------------------------------

def _js_candidates(rng: random.Random):
    """(prompt, name, code, tests) with random parameters."""
    k = rng.randint(2, 9)
    w = rng.choice(["moth", "code", "secure", "byte", "lamp"])
    return rng.choice([
        (f"return a new array with every number multiplied by {k}", f"times{k}",
         f"function times{k}(numbers) {{\n  return numbers.map((n) => n * {k});\n}}",
         [([[1, 2, 3]], [k, 2 * k, 3 * k]), ([[]], [])]),
        (f"keep only the numbers greater than {k}", f"above{k}",
         f"function above{k}(numbers) {{\n  return numbers.filter((n) => n > {k});\n}}",
         [([[k - 1, k, k + 1, k + 5]], [k + 1, k + 5])]),
        ("return the sum of the even numbers in an array", "sumEven",
         "function sumEven(numbers) {\n  let total = 0;\n  for (const n of numbers) {\n    if (n % 2 === 0) total += n;\n  }\n  return total;\n}",
         [([[1, 2, 3, 4]], 6), ([[]], 0)]),
        (f"count how many times the word \"{w}\" appears in a sentence", "countWord",
         f"function countWord(sentence) {{\n  return sentence.split(/\\s+/).filter((x) => x === \"{w}\").length;\n}}",
         [([f"{w} and {w} again"], 2), (["nothing here"], 0)]),
        ("return the number of keys of an object", "keyCount",
         "function keyCount(obj) {\n  return Object.keys(obj).length;\n}", [([{"a": 1, "b": 2}], 2), ([{}], 0)]),
        (f"repeat a string {k} times with a dash between", "repeatDash",
         f"function repeatDash(text) {{\n  return Array({k}).fill(text).join(\"-\");\n}}",
         [(["ab"], "-".join(["ab"] * k))]),
        ("turn a sentence into Title Case", "titleCase",
         "function titleCase(sentence) {\n  return sentence\n    .split(\" \")\n    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())\n    .join(\" \");\n}",
         [(["hello moth world"], "Hello Moth World")]),
        ("return the largest and smallest number of an array as [min, max]", "minMax",
         "function minMax(numbers) {\n  return [Math.min(...numbers), Math.max(...numbers)];\n}", [([[3, 9, 1]], [1, 9])]),
        ("check whether a string is a valid IPv4 address", "isIPv4",
         "function isIPv4(text) {\n  const parts = text.split(\".\");\n  return parts.length === 4 && parts.every((p) => /^\\d{1,3}$/.test(p) && Number(p) <= 255);\n}",
         [(["192.168.1.10"], True), (["300.1.1.1"], False), (["1.2.3"], False)]),
        ("escape <, > and & in a string so it is safe to put in HTML", "escapeHtml",
         "function escapeHtml(text) {\n  return text.replace(/&/g, \"&amp;\").replace(/</g, \"&lt;\").replace(/>/g, \"&gt;\");\n}",
         [(["<b>&</b>"], "&lt;b&gt;&amp;&lt;/b&gt;")]),
    ])


def _node_verify(items: list[tuple]) -> list[bool]:
    node = shutil.which("node")
    if not node or not items:
        return [False] * len(items)
    parts = ["const results = [];"]
    for i, (_, name, code, tests) in enumerate(items):
        checks = " && ".join(f"JSON.stringify({name}(...{json.dumps(a)})) === JSON.stringify({json.dumps(want)})" for a, want in tests)
        body = json.dumps(f"{code}\nreturn {checks};")  # compiled on its own: a syntax error spoils only this one
        parts.append(f"try {{ results[{i}] = new Function({body})() === true; }} catch (e) {{ results[{i}] = false; }}")
    parts.append("process.stdout.write(JSON.stringify(results));")
    with tempfile.TemporaryDirectory(prefix="moth-js-data-") as d:
        p = Path(d) / "check.js"
        p.write_text("\n".join(parts), encoding="utf-8")
        try:
            r = subprocess.run([node, str(p)], cwd=d, capture_output=True, text=True, timeout=60, env=_env())
            out = json.loads(r.stdout or "[]")
        except (subprocess.TimeoutExpired, OSError, ValueError):
            return [False] * len(items)
    return [out[i] is True if i < len(out) else False for i in range(len(items))]


JS_PROMPTS = ["Write a JavaScript function that can {task}.", "In JavaScript, how do I {task}?",
              "Write a JS function named `{name}` to {task}."]


def javascript_examples(rng: random.Random, n: int) -> list[tuple[str, str]]:
    cands = [_js_candidates(rng) for _ in range(n)]
    ok = _node_verify(cands)
    out = []
    for (task, name, code, tests), good in zip(cands, ok):
        if not good:
            continue
        args, want = tests[0]
        call = f"{name}({', '.join(json.dumps(a) for a in args)})"
        out.append((rng.choice(JS_PROMPTS).format(task=task, name=name),
                    f"```javascript\n{code}\n```\n\nFor example, `{call}` returns `{json.dumps(want)}`."))
    return out


# ---- Bash --------------------------------------------------------------------------------------------------

def _shell_task(rng: random.Random):
    """(question, command, files to prepare, expected stdout)."""
    lines = [f"{rng.choice(NAMES)},{rng.choice(CITIES)},{rng.randint(1, 99)}" for _ in range(rng.randint(3, 7))]
    logs = {f"app{i}.log": "" for i in range(rng.randint(1, 3))}
    errors = rng.randint(1, 4)
    log_text = "\n".join(["INFO start"] + ["ERROR failed"] * errors + ["INFO done"]) + "\n"
    word = rng.choice(CITIES)
    return rng.choice([
        ("How many lines does data.csv have?", "wc -l < data.csv", {"data.csv": "\n".join(lines) + "\n"}, f"{len(lines)}\n"),
        ("Print the second column of the comma-separated file data.csv.", "cut -d, -f2 data.csv",
         {"data.csv": "\n".join(lines) + "\n"}, "".join(l.split(",")[1] + "\n" for l in lines)),
        ("Count the lines containing ERROR in server.log.", "grep -c ERROR server.log", {"server.log": log_text}, f"{errors}\n"),
        ("List the .log files in this folder, sorted by name.", "ls *.log | sort",
         {**logs, "notes.txt": "x\n"}, "".join(f"{k}\n" for k in sorted(logs))),
        (f"Print the lines of data.csv that mention {word}.", f"grep '{word}' data.csv",
         {"data.csv": "\n".join(lines) + "\n"}, "".join(l + "\n" for l in lines if word in l)),
        ("Sort data.csv by its third column as numbers, largest first.", "sort -t, -k3,3nr data.csv",
         {"data.csv": "\n".join(lines) + "\n"}, None),  # expected computed by sort semantics below
    ])


def shell_example(rng: random.Random) -> tuple[str, str] | None:
    bash = shutil.which("bash")
    if not bash or os.name == "nt":
        return None
    question, cmd, files, want = _shell_task(rng)
    if want is None:
        rows = files["data.csv"].strip().split("\n")
        if len({int(r.split(",")[2]) for r in rows}) != len(rows):
            return None  # ties would make the order depend on sort's tie-breaking
        want = "".join(r + "\n" for r in sorted(rows, key=lambda r: -int(r.split(",")[2])))
    if want.strip() == "" and "grep" in cmd:
        return None
    with tempfile.TemporaryDirectory(prefix="moth-sh-data-") as d:
        for name, text in files.items():
            (Path(d) / name).write_text(text, encoding="utf-8")
        try:
            r = subprocess.run([bash, "--noprofile", "--norc", "-c", cmd], cwd=d, capture_output=True, text=True,
                               timeout=10, env={**_env(), "LC_ALL": "C"})
        except (subprocess.TimeoutExpired, OSError):
            return None
    if r.returncode != 0 or r.stdout.replace(" ", "") != want.replace(" ", ""):
        return None
    shown = r.stdout.strip().splitlines()
    return question, (f"```bash\n{cmd}\n```\n\nOutput:\n```\n" + "\n".join(shown[:6]).strip() + "\n```")


def generate(kind: str, n: int, seed: int = 0, source_id: str | None = None) -> Iterator[dict[str, Any]]:
    if kind not in KINDS:
        raise ValueError(f"unknown multi-language kind {kind!r}")
    rng = random.Random(f"{kind}:{seed}")
    sid = source_id or f"synthetic-{kind}"
    made = attempts = 0
    while made < n and attempts < n * 5:
        if kind == "javascript":
            batch = javascript_examples(rng, min(200, max(1, n - made)))
            attempts += 200
            if not batch and not shutil.which("node"):
                return
            examples = batch
        else:
            attempts += 1
            ex = sql_example(rng) if kind == "sql" else shell_example(rng)
            if ex is None:
                if kind == "shell" and (os.name == "nt" or not shutil.which("bash")):
                    return
                continue
            examples = [ex]
        for q, a in examples:
            if made >= n:
                break
            yield {"uid": f"{sid}:{made}", "source": sid, "domain": "code", "messages": _msgs(q, a)}
            made += 1
