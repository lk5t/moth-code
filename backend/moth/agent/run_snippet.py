"""2.4: "Run" on a code block in chat — the user's own choice, on their own computer.

The code runs in a new, empty temporary folder with a short time limit, a trimmed environment (no tokens or keys
from this app's environment), no input, and its output capped. Shell code that looks destructive, publishes data
or reads secrets is refused unless the user confirmed that warning (``confirmed``). Only languages whose
interpreter is installed can run; the answer says which one is missing otherwise.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from moth.agent.checkers import _env

TIMEOUT_S = 15
MAX_OUTPUT = 20_000
MAX_CODE = 100_000

# language → (file name, candidate interpreters, arguments before the file)
RUNNERS: dict[str, tuple[str, list[str], list[str]]] = {
    "python": ("main.py", ["python3", "python", "py"], []),
    "javascript": ("main.js", ["node"], []),
    "typescript": ("main.ts", ["deno"], ["run", "--no-prompt"]),
    "bash": ("main.sh", ["bash"], []),
    "sh": ("main.sh", ["sh", "bash"], []),
    "powershell": ("main.ps1", ["pwsh", "powershell"], ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]),
    "ruby": ("main.rb", ["ruby"], []),
    "php": ("main.php", ["php"], []),
    "lua": ("main.lua", ["lua"], []),
    "perl": ("main.pl", ["perl"], []),
}
ALIASES = {"py": "python", "python3": "python", "js": "javascript", "node": "javascript", "ts": "typescript",
           "shell": "bash", "zsh": "bash", "console": "bash", "ps1": "powershell", "pwsh": "powershell", "rb": "ruby"}
SHELLS = {"bash", "sh", "powershell"}


def language(label: str) -> str | None:
    lang = (label or "").strip().lower().split()[0] if (label or "").strip() else ""
    lang = ALIASES.get(lang, lang)
    return lang if lang in RUNNERS else None


def _interpreter(lang: str) -> str | None:
    names = RUNNERS[lang][1]
    if lang == "python":  # on Windows "python3" is often the Microsoft Store shortcut, not Python
        names = ["py", "python"] if sys.platform == "win32" else ["python3", "python"]
    for name in names:
        exe = shutil.which(name)
        if exe and "WindowsApps" not in exe:
            return exe
    return None


def available() -> dict[str, bool]:
    return {lang: _interpreter(lang) is not None for lang in RUNNERS}


def risk(lang: str, code: str) -> str | None:
    """Why shell code needs a confirmation (destructive, publishing, network, secrets), else None."""
    if lang not in SHELLS:
        return None
    from moth.security.permissions import Decision, classify_command

    for line in code.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        r = classify_command(line)
        if r.decision != Decision.ALLOW:
            return f"{line.strip()[:120]}: {r.reason}"
    return None


def run(label: str, code: str, confirmed: bool = False) -> dict[str, Any]:
    lang = language(label)
    if not lang:
        return {"ok": False, "error": f"Running “{label or 'this'}” code is not supported. Supported: {', '.join(sorted(RUNNERS))}."}
    if len(code) > MAX_CODE:
        return {"ok": False, "error": "That code is too long to run here."}
    exe = _interpreter(lang)
    if not exe:
        return {"ok": False, "language": lang, "error": f"{lang.capitalize()} is not installed on this computer ({' or '.join(RUNNERS[lang][1])} was not found)."}
    why = risk(lang, code)
    if why and not confirmed:
        return {"ok": False, "language": lang, "needs_confirmation": why}
    name, _, pre = RUNNERS[lang]
    kw: dict[str, Any] = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    with tempfile.TemporaryDirectory(prefix="moth-run-") as d:
        f = Path(d) / name
        f.write_text(code, encoding="utf-8")
        t = time.monotonic()
        try:
            p = subprocess.run([exe, *pre, str(f)], cwd=d, env={**_env(), "PYTHONIOENCODING": "utf-8"}, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TIMEOUT_S, **kw)
            out, err, code_ = p.stdout, p.stderr, p.returncode
            timed_out = False
        except subprocess.TimeoutExpired as e:
            out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            err = (e.stderr or b"").decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
            code_, timed_out = None, True
        took = round(time.monotonic() - t, 2)
    clip = lambda s: s if len(s) <= MAX_OUTPUT else s[:MAX_OUTPUT] + "\n… (output cut off)"  # noqa: E731
    return {"ok": code_ == 0, "language": lang, "exit_code": code_, "timed_out": timed_out, "seconds": took,
            "stdout": clip(out or ""), "stderr": clip((err or "").replace(d, "."))}
