"""1.1 held-out exams for a coding and security-testing AI.

* ``js_suite`` — write a JavaScript function; it counts only if Node.js runs it and every test passes
  (isolated temporary directory, time-limited). Not measurable (for every model alike) without Node.js.
* ``security_suite`` — fixed multiple-choice questions on vulnerability classes, ATT&CK, protocols, shell
  and defensive practice, scored like the reasoning benchmark (which answer the model finds most likely), so
  even a small model gets a steady, comparable score.

None of these items appear in the training data.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

JS_TASKS: list[tuple[str, str, list[tuple[list, Any]]]] = [
    ("return the sum of an array of numbers", "sumAll", [([[1, 2, 3]], 6), ([[]], 0), ([[-2, 5]], 3)]),
    ("return the largest number in an array", "largest", [([[3, 9, 2]], 9), ([[-5, -1]], -1)]),
    ("reverse a string", "reverseText", [(["abc"], "cba"), ([""], "")]),
    ("count how many times a character appears in a string", "countChar", [(["banana", "a"], 3), (["xyz", "a"], 0)]),
    ("return true if a number is even", "isEven", [([4], True), ([7], False), ([0], True)]),
    ("return the array with duplicates removed, keeping the first occurrence", "unique",
     [([[1, 2, 1, 3, 2]], [1, 2, 3]), ([[]], [])]),
    ("capitalize the first letter of a string", "capitalize", [(["hello"], "Hello"), (["a"], "A")]),
    ("return the factorial of a non-negative integer", "factorial", [([0], 1), ([5], 120)]),
    ("return the number of words in a sentence separated by spaces", "wordCount", [(["one two three"], 3), (["solo"], 1)]),
    ("return a new array with every number doubled", "doubleAll", [([[1, 2]], [2, 4]), ([[]], [])]),
    ("return true if a string reads the same backwards", "isPalindrome", [(["level"], True), (["moth"], False)]),
    ("return the keys of an object sorted alphabetically", "sortedKeys", [([{"b": 1, "a": 2}], ["a", "b"])]),
]

# (question, choices, index of the correct choice)
SECURITY_EXAM: list[tuple[str, list[str], int]] = [
    ("Which weakness class lets an attacker change a database query through unsanitised input?",
     ["SQL injection (CWE-89)", "Buffer over-read", "Race condition", "Weak password policy"], 0),
    ("What is the most reliable defence against SQL injection?",
     ["Parameterised queries", "Hiding error messages", "Longer table names", "Using HTTPS"], 0),
    ("Cross-site scripting (XSS) is mainly prevented by…",
     ["Encoding output for the context it is placed in", "Disabling cookies", "Using a faster server", "Compressing pages"], 0),
    ("Which CWE describes storing passwords in plain text?",
     ["CWE-256 Plaintext Storage of a Password", "CWE-79 Cross-site Scripting", "CWE-20 Improper Input Validation",
      "CWE-400 Uncontrolled Resource Consumption"], 0),
    ("In MITRE ATT&CK, what does a tactic describe?",
     ["The adversary's goal, the 'why' of an action", "A specific malware family", "A patch level", "A CVE score"], 0),
    ("Which ATT&CK tactic covers gaining a first foothold in a network?",
     ["Initial Access", "Exfiltration", "Impact", "Collection"], 0),
    ("Which ATT&CK tactic covers keeping access across restarts?",
     ["Persistence", "Discovery", "Reconnaissance", "Impact"], 0),
    ("What does the CVSS score of a vulnerability express?", ["Its severity", "Its age", "Its author", "Its file size"], 0),
    ("Which port does HTTPS use by default?", ["443", "21", "25", "3389"], 0),
    ("Which port does SSH use by default?", ["22", "80", "53", "110"], 0),
    ("Which port does DNS use by default?", ["53", "8080", "143", "445"], 0),
    ("Which protocol does SMB file sharing usually run on?", ["TCP port 445", "UDP port 123", "TCP port 25", "TCP port 993"], 0),
    ("What must exist before an authorized penetration test starts?",
     ["Written permission and an agreed scope", "A public announcement", "A faster internet connection", "An antivirus scan"], 0),
    ("A finding outside the agreed scope of an engagement should be…",
     ["Stopped and reported to the client, not exploited", "Exploited fully", "Ignored and deleted", "Published online"], 0),
    ("Which shell command lists open listening TCP ports on Linux?", ["ss -tlnp", "ls -la", "chmod 600", "cat /etc/hosts"], 0),
    ("Which command shows the permissions of files in a directory?", ["ls -l", "pwd", "whoami", "uptime"], 0),
    ("Which file permission setting is safest for a private SSH key?", ["600", "777", "755", "666"], 0),
    ("What does the principle of least privilege mean?",
     ["Give each user and process only the access it needs", "Give admins all access", "Remove all passwords",
      "Share one account per team"], 0),
    ("Why should passwords be stored with a slow salted hash such as bcrypt or Argon2?",
     ["It makes stolen hashes much harder to crack", "It makes logins faster", "It compresses the database",
      "It hides usernames"], 0),
    ("What is the purpose of a CSRF token?",
     ["To check that a request really came from the site's own form", "To speed up page loads", "To store passwords",
      "To encrypt images"], 0),
    ("What does TLS provide for a web connection?",
     ["Encryption and server authentication", "Faster DNS", "Unlimited bandwidth", "Automatic backups"], 0),
    ("What is a common sign of a directory traversal attempt in a URL?", ["../ sequences", "?page=2", "#top", "www."], 0),
    ("Which tool category maps hosts and open ports on a network you are authorized to test?",
     ["A network scanner such as nmap", "A word processor", "A spreadsheet", "An image editor"], 0),
    ("What should a security report include for each finding?",
     ["Description, impact, evidence and how to fix it", "Only the attacker's name", "Only a score", "Nothing written"], 0),
    ("Which HTTP response header helps prevent clickjacking?",
     ["Content-Security-Policy frame-ancestors (or X-Frame-Options)", "Content-Length", "Accept-Encoding", "Date"], 0),
    ("What does multi-factor authentication protect against?",
     ["Logins with a stolen password alone", "Slow networks", "Disk failure", "Spam folders"], 0),
    ("What is the safest way to handle secrets such as API keys in code?",
     ["Keep them out of source code, in a secret store or environment", "Commit them to the repository",
      "Put them in comments", "Email them to the team"], 0),
    ("What does input validation on a server do?",
     ["Rejects data that is not in the expected format", "Makes pages colourful", "Encrypts the disk", "Counts visitors"], 0),
    ("Which log would show failed SSH logins on many Linux systems?",
     ["/var/log/auth.log", "/etc/passwd", "/tmp/cache", "/usr/bin/ls"], 0),
    ("What is the purpose of patch management?",
     ["Fixing known vulnerabilities by applying updates", "Designing logos", "Writing contracts", "Cleaning keyboards"], 0),
]


def _node() -> str | None:
    return shutil.which("node")


def run_js(code: str, name: str, tests: list[tuple[list, Any]], timeout: float = 6.0) -> bool:
    node = _node()
    if not node or not code.strip():
        return False
    checks = "\n".join(f"if (JSON.stringify({name}(...{json.dumps(args)})) !== JSON.stringify({json.dumps(want)})) "
                       "process.exit(1);" for args, want in tests)
    with tempfile.TemporaryDirectory(prefix="moth-js-eval-") as d:
        p = Path(d) / "solution.js"
        p.write_text(f"{code}\n{checks}\n", encoding="utf-8")
        try:
            r = subprocess.run([node, str(p)], cwd=d, capture_output=True, timeout=timeout,
                               env={"PATH": os.environ.get("PATH", "")})
            return r.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False


def js_items() -> list[dict[str, Any]]:
    return [{"prompt": f"Write a JavaScript function named `{name}` that can {task}.", "name": name, "tests": tests}
            for task, name, tests in JS_TASKS]


def js_suite(model, tok, max_new: int = 200) -> dict[str, Any]:
    from moth.model.capabilities import _chat, _extract_code

    if not _node():
        return {"ok": False, "error": "Node.js is not installed on this computer"}
    items = js_items()
    passed = 0
    for it in items:
        out, _ = _chat(model, tok, it["prompt"], max_new)
        code = _extract_code(out)
        if f"function {it['name']}" in code or f"{it['name']} =" in code:
            passed += run_js(code, it["name"], it["tests"])
    return {"metric": "tests_passed", "value": passed / len(items), "n": len(items), "higher_is_better": True}


def security_suite(model, tok) -> dict[str, Any]:
    from moth.model.capabilities import _logprob
    from moth.model.chat_format import Message, encode_chat

    correct = 0
    for q, choices, answer in SECURITY_EXAM:
        base, _ = encode_chat(tok, [Message("user", q)], add_generation_prompt=True)
        scores = []
        for text in choices:
            cont = tok.encode(text)
            scores.append(_logprob(model, base + cont, len(base)) / max(1, len(cont)))
        correct += max(range(len(scores)), key=scores.__getitem__) == answer
    n = len(SECURITY_EXAM)
    return {"metric": "accuracy", "value": correct / n, "n": n, "higher_is_better": True,
            "chance": round(sum(1 / len(c) for _, c, _ in SECURITY_EXAM) / n, 3)}
