"""2.0: syntax checks for files the agent changed, in many languages, without running the project's code.

Each check only parses or type-checks syntax (``node --check``, ``bash -n``, ``gofmt -e``, ``gcc -fsyntax-only``,
``php -l``, ``ruby -c``…), and only runs when that tool is installed. Python, JSON and TOML are checked in-process.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path

TIMEOUT = 20

# suffix -> (tool, args before the file); {f} is replaced by the file path
EXTERNAL: dict[str, tuple[str, list[str]]] = {
    ".js": ("node", ["--check", "{f}"]), ".mjs": ("node", ["--check", "{f}"]), ".cjs": ("node", ["--check", "{f}"]),
    ".sh": ("bash", ["-n", "{f}"]), ".bash": ("bash", ["-n", "{f}"]),
    ".go": ("gofmt", ["-e", "-l", "{f}"]),
    ".c": ("gcc", ["-fsyntax-only", "-w", "{f}"]), ".cpp": ("g++", ["-fsyntax-only", "-w", "{f}"]),
    ".cc": ("g++", ["-fsyntax-only", "-w", "{f}"]),
    ".php": ("php", ["-l", "{f}"]), ".rb": ("ruby", ["-c", "{f}"]), ".pl": ("perl", ["-c", "{f}"]),
    ".lua": ("luac", ["-p", "{f}"]),
}


def _env() -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "GOPATH", "GOCACHE")
    return {k: v for k, v in os.environ.items() if k in keep}


def check_file(root: Path, rel: str) -> str | None:
    """A problem description, or None when the file looks fine (or cannot be checked here)."""
    p = Path(root) / rel
    if not p.is_file():
        return None
    suffix = p.suffix.lower()
    try:
        if suffix == ".py":
            ast.parse(p.read_text(encoding="utf-8"), filename=rel)
        elif suffix == ".json":
            json.loads(p.read_text(encoding="utf-8"))
        elif suffix == ".toml":
            import tomllib
            tomllib.loads(p.read_text(encoding="utf-8"))
        elif suffix in (".yml", ".yaml"):
            try:
                import yaml
            except ImportError:
                return None
            yaml.safe_load(p.read_text(encoding="utf-8"))
        elif suffix in EXTERNAL:
            tool, args = EXTERNAL[suffix]
            exe = shutil.which(tool)
            if not exe:
                return None
            r = subprocess.run([exe, *[a.replace("{f}", str(p)) for a in args]], cwd=root, capture_output=True,
                               text=True, timeout=TIMEOUT, env=_env())
            out = (r.stderr or r.stdout or "").strip()
            if r.returncode != 0:
                return f"{rel}: {out[-800:] or f'{tool} failed'}"
    except SyntaxError as e:
        return f"{rel}:{e.lineno}: {e.msg}"
    except (ValueError, UnicodeDecodeError) as e:  # JSON, TOML and decoding errors
        return f"{rel}: {e}"
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None
    except Exception as e:  # noqa: BLE001 - e.g. yaml.YAMLError
        return f"{rel}: {str(e)[:400]}"
    return None


def available() -> dict[str, bool]:
    """Which external checkers this computer has (shown in the agent's report)."""
    return {t: shutil.which(t) is not None for t in sorted({v[0] for v in EXTERNAL.values()})}


FENCE = __import__("re").compile(r"```([\w+#.-]*)[^\n]*\n(.*?)```", __import__("re").S)
LANG_SUFFIX = {"python": ".py", "py": ".py", "javascript": ".js", "js": ".js", "node": ".js", "bash": ".sh", "sh": ".sh",
               "shell": ".sh", "go": ".go", "golang": ".go", "c": ".c", "cpp": ".cpp", "c++": ".cpp", "php": ".php",
               "ruby": ".rb", "rb": ".rb", "json": ".json", "toml": ".toml", "yaml": ".yaml", "yml": ".yaml", "lua": ".lua"}


def check_answer(text: str, limit: int = 6) -> list[dict]:
    """2.0: MOTH checks the code in its own answer: each fenced block in a known language is syntax-checked
    (never run). Returns one entry per checked block: language, ok, and the problem when there is one."""
    import tempfile

    out: list[dict] = []
    for lang, code in FENCE.findall(text or "")[:limit]:
        suffix = LANG_SUFFIX.get(lang.lower())
        if not suffix or not code.strip():
            continue
        if suffix == ".sh" and code.lstrip().startswith("$ "):
            continue  # a terminal transcript, not a script
        with tempfile.TemporaryDirectory(prefix="moth-answer-") as d:
            name = "answer" + suffix
            Path(d, name).write_text(code, encoding="utf-8")
            problem = check_file(Path(d), name)
            if problem:
                problem = problem.replace(str(Path(d, name)), "code")
                if problem.startswith(f"{name}:"):
                    problem = problem[len(name) + 1:]
                problem = problem.replace(name, "code").strip()
                problem = problem[5:].strip() if problem.startswith("code:") else problem
                keep = [ln.strip() for ln in problem.splitlines()
                        if ln.strip() and not ln.lstrip().startswith("at ") and not ln.startswith("Node.js v")]
                problem = " · ".join(keep[:3])[:300]
                problem = __import__("re").sub(r"^(\d+)\s*(?::|·)\s*", r"line \1: ", problem)
        out.append({"language": lang.lower(), "ok": problem is None, "problem": problem})
    return out
