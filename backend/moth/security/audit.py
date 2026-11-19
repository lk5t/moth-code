"""2.1 security checks MOTH runs from chat on your own files. Nothing here contacts any system.

* ``code_audit`` — hard-coded secrets and dangerous code patterns (eval/exec, shell injection, unsafe
  deserialisation, SQL built from strings, disabled TLS checks, weak password hashing, HTML injection sinks,
  debug mode) in Python, JavaScript/TypeScript, PHP, Go, Java, C/C++, Ruby and shell scripts.
* ``deps_audit`` — dependency versions (requirements.txt, pyproject.toml, package.json, package-lock.json)
  checked against a built-in list of well-known vulnerable versions. The list is not exhaustive and says so.
* ``config_audit`` — risky settings in SSH, nginx, Dockerfile, docker-compose and .env files.

Each finding has the same shape as a scan finding (severity, title, where, evidence, fix), so chat shows them alike.
Secrets found are never shown in full.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from moth.security.redaction import SECRET_PATTERNS

SEVERITIES = ["critical", "high", "medium", "low", "info"]
MAX_FILES = 4000
MAX_FILE_BYTES = 400_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "env", "dist", "build", "target", ".next",
             ".cache", ".mypy_cache", ".pytest_cache", ".tox", "vendor", "coverage", ".idea", ".vscode"}


@dataclass
class Finding:
    severity: str
    title: str
    where: str
    evidence: str
    fix: str
    ref: str = ""


# ---- code -------------------------------------------------------------------------------------------------
# (languages, regex, severity, title, fix, reference)
RULES: list[tuple[set[str], re.Pattern, str, str, str, str]] = [
    ({"py"}, re.compile(r"\b(eval|exec)\s*\((?!\s*['\"])"), "high", "eval/exec on dynamic input",
     "Never run code built from input; parse the data instead (json.loads, ast.literal_eval).", "CWE-95"),
    ({"py"}, re.compile(r"subprocess\.\w+\([^)]*shell\s*=\s*True"), "high", "Shell command with shell=True",
     "Pass the command as a list without shell=True, so input cannot add extra commands.", "CWE-78"),
    ({"py"}, re.compile(r"\bos\.(system|popen)\s*\((?!\s*['\"][^'\"]*['\"]\s*\))"), "high", "os.system/os.popen with a built command",
     "Use subprocess.run([...]) with a list of arguments.", "CWE-78"),
    ({"py"}, re.compile(r"\bpickle\.loads?\s*\(|\bmarshal\.loads?\s*\("), "high", "Unpickling data (can run code)",
     "Never unpickle data from users or the network; use JSON.", "CWE-502"),
    ({"py"}, re.compile(r"\byaml\.load\s*\((?![^)]*Loader\s*=\s*yaml\.SafeLoader)(?![^)]*SafeLoader)"), "high", "yaml.load without SafeLoader",
     "Use yaml.safe_load().", "CWE-502"),
    ({"py"}, re.compile(r"\.execute\s*\(\s*(f['\"]|['\"][^'\"]*['\"]\s*(%|\+|\.format))", re.I), "high", "SQL query built from strings",
     "Use parameters: cursor.execute('... WHERE id = ?', (value,)).", "CWE-89"),
    ({"py"}, re.compile(r"verify\s*=\s*False"), "medium", "TLS certificate checks turned off",
     "Remove verify=False so connections check the server's certificate.", "CWE-295"),
    ({"py"}, re.compile(r"hashlib\.(md5|sha1)\s*\("), "low", "MD5/SHA-1 in use",
     "Fine for checksums, never for passwords: use bcrypt or argon2 for passwords and SHA-256+ for integrity.", "CWE-328"),
    ({"py"}, re.compile(r"\bdebug\s*=\s*True|DEBUG\s*=\s*True"), "medium", "Debug mode on",
     "Turn debug off in production; it can show code and secrets to visitors.", "CWE-489"),
    ({"js", "ts"}, re.compile(r"\beval\s*\(|new\s+Function\s*\("), "high", "eval/new Function",
     "Avoid running strings as code; parse data with JSON.parse.", "CWE-95"),
    ({"js", "ts"}, re.compile(r"\.innerHTML\s*=|dangerouslySetInnerHTML|document\.write\s*\("), "medium", "HTML injection sink",
     "Use textContent (or escape/sanitise HTML) so input cannot add scripts.", "CWE-79"),
    ({"js", "ts"}, re.compile(r"child_process['\"]?\)?\.?\s*.*\bexec\s*\(|\bexecSync\s*\("), "high", "Shell command execution",
     "Use execFile/spawn with an argument list instead of exec with a built string.", "CWE-78"),
    ({"js", "ts"}, re.compile(r"(query|execute)\s*\(\s*`[^`]*\$\{", re.I), "high", "SQL query built with a template string",
     "Use parameterised queries (placeholders) instead of ${...} inside SQL.", "CWE-89"),
    ({"js", "ts"}, re.compile(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED"), "medium", "TLS certificate checks turned off",
     "Keep certificate checks on.", "CWE-295"),
    ({"php"}, re.compile(r"\b(eval|assert)\s*\(\s*\$|\b(system|exec|shell_exec|passthru)\s*\(\s*\$"), "high", "Code or shell execution from a variable",
     "Never pass user data to eval/system; use escapeshellarg or avoid the shell.", "CWE-78"),
    ({"php"}, re.compile(r"(mysql_query|mysqli_query|->query)\s*\([^)]*\$_(GET|POST|REQUEST)"), "critical", "SQL query with request data",
     "Use prepared statements (PDO with placeholders).", "CWE-89"),
    ({"php"}, re.compile(r"echo\s+\$_(GET|POST|REQUEST)"), "high", "Request data printed without escaping",
     "Escape output with htmlspecialchars().", "CWE-79"),
    ({"go"}, re.compile(r"InsecureSkipVerify\s*:\s*true"), "medium", "TLS certificate checks turned off",
     "Remove InsecureSkipVerify.", "CWE-295"),
    ({"go"}, re.compile(r"(Query|Exec)\w*\(\s*(fmt\.Sprintf|\"[^\"]*\"\s*\+)"), "high", "SQL query built from strings",
     "Use placeholders: db.Query(\"... WHERE id = ?\", id).", "CWE-89"),
    ({"java"}, re.compile(r"(executeQuery|executeUpdate|execute)\s*\(\s*\"[^\"]*\"\s*\+"), "high", "SQL query built from strings",
     "Use PreparedStatement with ? placeholders.", "CWE-89"),
    ({"java"}, re.compile(r"Runtime\.getRuntime\(\)\.exec\s*\("), "medium", "Runtime.exec",
     "Use ProcessBuilder with an argument list and never pass raw input.", "CWE-78"),
    ({"c", "cpp"}, re.compile(r"\b(gets|strcpy|strcat|sprintf)\s*\("), "medium", "Unsafe C string function",
     "Use bounded versions (fgets, snprintf, strncpy/strlcpy) to avoid buffer overflows.", "CWE-120"),
    ({"c", "cpp"}, re.compile(r"\bsystem\s*\("), "medium", "system() call",
     "Avoid the shell; use execv-style calls with fixed arguments.", "CWE-78"),
    ({"rb"}, re.compile(r"\beval\s*\(|`[^`]*#\{"), "high", "eval or shell command with interpolation",
     "Avoid eval; use system with an argument list.", "CWE-78"),
    ({"sh"}, re.compile(r"\beval\s+\"?\$"), "medium", "eval of a variable",
     "Avoid eval; quote variables and use arrays.", "CWE-78"),
    ({"sh"}, re.compile(r"curl[^|\n]*\|\s*(sudo\s+)?(ba)?sh\b"), "medium", "Piping a download straight into a shell",
     "Download, check (checksum or signature), then run.", "CWE-494"),
]
EXT = {".py": "py", ".js": "js", ".mjs": "js", ".cjs": "js", ".jsx": "js", ".ts": "ts", ".tsx": "ts", ".php": "php",
       ".go": "go", ".java": "java", ".kt": "java", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
       ".rb": "rb", ".sh": "sh", ".bash": "sh"}
TEXT_EXT = set(EXT) | {".env", ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".xml", ".txt"}


def _files(root: Path) -> Iterable[Path]:
    count = 0
    for p in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts[:-1]):
            continue
        if not p.is_file():
            continue
        if p.suffix.lower() in TEXT_EXT or p.name.startswith(".env") or p.name in ("Dockerfile", "sshd_config"):
            count += 1
            if count > MAX_FILES:
                return
            yield p


def _read(p: Path) -> str | None:
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _mask(s: str) -> str:
    s = s.strip()
    return (s[:4] + "…" + s[-2:]) if len(s) > 10 else "…"


def _is_test(rel: str) -> bool:
    return bool(re.search(r"(^|/)(tests?|spec|__tests__|fixtures?)(/|$)|(_test|\.test|\.spec)\.", rel))


def code_audit(root: Path | str) -> dict[str, Any]:
    root = Path(root)
    out: list[Finding] = []
    scanned = 0
    for p in _files(root):
        rel = p.relative_to(root).as_posix()
        text = _read(p)
        if text is None:
            continue
        scanned += 1
        lang = EXT.get(p.suffix.lower())
        lines = text.splitlines()
        # secrets in any text file (an example/template file is fine)
        if not re.search(r"\.(example|sample|template)$", p.name):
            for name, rx in SECRET_PATTERNS:
                for m in rx.finditer(text):
                    line = text.count("\n", 0, m.start()) + 1
                    sev = "info" if _is_test(rel) else ("critical" if name in ("private_key", "aws_access_key", "stripe_key", "github_token") else "high")
                    out.append(Finding(sev, f"Secret in the code ({name.replace('_', ' ')})", f"{rel}:{line}",
                                       f"value {_mask(m.group(0))}",
                                       "Move it to an environment variable or secret store, remove it from the code and "
                                       "Git history, and rotate it (assume it is leaked).", "CWE-798"))
                    break
        if not lang:
            continue
        for i, line in enumerate(lines, 1):
            if len(line) > 2000 or line.lstrip().startswith(("#", "//", "*", "/*")):
                continue
            for langs, rx, sev, title, fix, ref in RULES:
                if lang in langs and rx.search(line):
                    out.append(Finding("low" if _is_test(rel) and sev != "low" else sev, title, f"{rel}:{i}",
                                       line.strip()[:160], fix, ref))
    return _report("Code audit", out, f"Checked {scanned} files for secrets and risky code patterns.")


# ---- dependencies -----------------------------------------------------------------------------------------
# (ecosystem, package, fixed-in version, severity, what, reference) — well-known issues only
KNOWN_VULNS: list[tuple[str, str, str, str, str, str]] = [
    ("pypi", "requests", "2.31.0", "medium", "leaks Proxy-Authorization headers on redirects", "CVE-2023-32681"),
    ("pypi", "urllib3", "1.26.18", "medium", "Cookie header kept on cross-origin redirects", "CVE-2023-43804"),
    ("pypi", "pyyaml", "5.4", "critical", "yaml.load can run code (full_load)", "CVE-2020-14343"),
    ("pypi", "jinja2", "3.1.3", "medium", "XSS through the xmlattr filter", "CVE-2024-22195"),
    ("pypi", "flask", "2.2.5", "high", "session cookie can be cached by proxies", "CVE-2023-30861"),
    ("pypi", "django", "3.2.25", "high", "several fixed vulnerabilities in older releases", "Django security releases"),
    ("pypi", "pillow", "10.0.1", "high", "libwebp heap overflow", "CVE-2023-4863"),
    ("pypi", "werkzeug", "2.3.8", "high", "debugger and multipart issues in older releases", "CVE-2023-46136"),
    ("npm", "lodash", "4.17.21", "high", "prototype pollution / command injection in template", "CVE-2021-23337"),
    ("npm", "minimist", "1.2.6", "high", "prototype pollution", "CVE-2021-44906"),
    ("npm", "axios", "1.6.0", "medium", "CSRF token sent to other hosts", "CVE-2023-45857"),
    ("npm", "jsonwebtoken", "9.0.0", "high", "weak key / algorithm handling", "CVE-2022-23529"),
    ("npm", "node-fetch", "2.6.7", "high", "sends cookies to other hosts on redirect", "CVE-2022-0235"),
    ("npm", "express", "4.19.2", "medium", "open redirect", "CVE-2024-29041"),
    ("npm", "ws", "8.17.1", "high", "denial of service with many headers", "CVE-2024-37890"),
    ("npm", "semver", "7.5.2", "medium", "regular-expression denial of service", "CVE-2022-25883"),
]


def _ver(v: str) -> tuple[int, ...] | None:
    m = re.match(r"\s*[v=^~>]*\s*(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _deps(root: Path) -> list[tuple[str, str, str, str]]:
    """(ecosystem, name, version, file) for pinned/minimum versions we can read."""
    out = []
    for f in [root / "requirements.txt", *sorted(root.glob("requirements*.txt"))]:
        if f.exists():
            for line in f.read_text(errors="replace").splitlines():
                m = re.match(r"\s*([A-Za-z0-9_.\-]+)\s*(==|>=|~=)\s*([0-9][^\s;,#]*)", line)
                if m:
                    out.append(("pypi", m.group(1).lower(), m.group(3), f.name))
    py = root / "pyproject.toml"
    if py.exists():
        for m in re.finditer(r"['\"]([A-Za-z0-9_.\-]+)\s*(==|>=|~=)\s*([0-9][^'\";, ]*)", py.read_text(errors="replace")):
            out.append(("pypi", m.group(1).lower(), m.group(3), "pyproject.toml"))
    lock = root / "package-lock.json"
    pkg = root / "package.json"
    if lock.exists():
        try:
            data = json.loads(lock.read_text(errors="replace"))
            for path, info in (data.get("packages") or {}).items():
                if path.startswith("node_modules/") and info.get("version"):
                    out.append(("npm", path.rsplit("node_modules/", 1)[-1], info["version"], "package-lock.json"))
        except ValueError:
            pass
    elif pkg.exists():
        try:
            data = json.loads(pkg.read_text(errors="replace"))
            for sec in ("dependencies", "devDependencies"):
                for name, v in (data.get(sec) or {}).items():
                    out.append(("npm", name, str(v), "package.json"))
        except ValueError:
            pass
    seen, uniq = set(), []
    for d in out:
        if d[:3] not in seen:
            seen.add(d[:3])
            uniq.append(d)
    return uniq


def deps_audit(root: Path | str) -> dict[str, Any]:
    root = Path(root)
    deps = _deps(root)
    out: list[Finding] = []
    for eco, name, version, file in deps:
        have = _ver(version)
        if not have:
            continue
        for k_eco, k_name, fixed, sev, what, ref in KNOWN_VULNS:
            if k_eco == eco and k_name == name and have < _ver(fixed):
                out.append(Finding(sev, f"{name} {version} is vulnerable ({what})", file, f"{name} {version} < {fixed}",
                                   f"Update {name} to {fixed} or later.", ref))
    note = (f"Checked {len(deps)} dependencies against MOTH's built-in list of well-known vulnerable versions. "
            "This list is not exhaustive: keep dependencies updated and use your package manager's audit too "
            "(pip-audit, npm audit).") if deps else "No requirements.txt, pyproject.toml or package.json found."
    return _report("Dependency audit", out, note)


# ---- configuration ----------------------------------------------------------------------------------------
CONFIG_RULES: list[tuple[re.Pattern, re.Pattern, str, str, str]] = [
    # (file name pattern, line pattern, severity, title, fix)
    (re.compile(r"sshd_config"), re.compile(r"^\s*PermitRootLogin\s+yes", re.I | re.M), "high", "SSH allows root login",
     "Set PermitRootLogin no (or prohibit-password) and log in as a normal user."),
    (re.compile(r"sshd_config"), re.compile(r"^\s*PasswordAuthentication\s+yes", re.I | re.M), "medium", "SSH accepts passwords",
     "Use SSH keys and set PasswordAuthentication no."),
    (re.compile(r"sshd_config"), re.compile(r"^\s*PermitEmptyPasswords\s+yes", re.I | re.M), "critical", "SSH allows empty passwords",
     "Set PermitEmptyPasswords no."),
    (re.compile(r"nginx|\.conf$"), re.compile(r"^\s*server_tokens\s+on", re.I | re.M), "low", "nginx shows its version",
     "Set server_tokens off."),
    (re.compile(r"nginx|\.conf$"), re.compile(r"^\s*autoindex\s+on", re.I | re.M), "medium", "Directory listing on",
     "Set autoindex off."),
    (re.compile(r"nginx|\.conf$"), re.compile(r"ssl_protocols[^;]*TLSv1(\.1)?[\s;]", re.I), "medium", "Old TLS versions allowed",
     "Use ssl_protocols TLSv1.2 TLSv1.3;"),
    (re.compile(r"Dockerfile"), re.compile(r"^\s*FROM\s+\S+:latest\b|^\s*FROM\s+[^:\s]+\s*$", re.I | re.M), "low", "Base image without a fixed version",
     "Pin the base image to a version (or digest) so builds are repeatable."),
    (re.compile(r"Dockerfile"), re.compile(r"^\s*(ENV|ARG)\s+\w*(PASSWORD|SECRET|TOKEN|API_KEY)\w*[ =]", re.I | re.M), "high", "Secret baked into the image",
     "Pass secrets at run time (docker secrets or environment), never in ENV/ARG."),
    (re.compile(r"Dockerfile"), re.compile(r"^\s*ADD\s+https?://", re.I | re.M), "low", "ADD downloads from a URL",
     "Download with curl and verify a checksum instead."),
    (re.compile(r"compose\.ya?ml$|docker-compose"), re.compile(r"privileged\s*:\s*true", re.I), "high", "Container runs privileged",
     "Remove privileged: true; grant only the capabilities it needs."),
    (re.compile(r"compose\.ya?ml$|docker-compose"), re.compile(r"[\"']?(0\.0\.0\.0:)?(3306|5432|6379|27017|9200):\d+", re.I), "medium", "Database port published to every network",
     "Publish it on 127.0.0.1 only (\"127.0.0.1:5432:5432\") or not at all."),
    (re.compile(r"compose\.ya?ml$|docker-compose"), re.compile(r"/var/run/docker\.sock", re.I), "high", "Docker socket mounted into a container",
     "Mounting the Docker socket gives the container control of the host; avoid it."),
]


def config_audit(files: list[tuple[str, str]]) -> dict[str, Any]:
    """``files``: (name, content) pairs, from the open project or attached to the message."""
    out: list[Finding] = []
    for name, text in files:
        base = Path(name).name
        if base.startswith(".env") and not re.search(r"\.(example|sample|template)$", base):
            out.append(Finding("medium", ".env file with secrets", name, "contains environment settings",
                               "Keep .env out of Git (.gitignore) and out of web roots; commit a .env.example instead.", "CWE-538"))
        for fpat, rx, sev, title, fix in CONFIG_RULES:
            if fpat.search(base) or fpat.search(name):
                m = rx.search(text)
                if m:
                    line = text.count("\n", 0, m.start()) + 1
                    out.append(Finding(sev, title, f"{name}:{line}", m.group(0).strip()[:120], fix))
    return _report("Configuration audit", out, f"Checked {len(files)} configuration file(s).")


def project_configs(root: Path | str) -> list[tuple[str, str]]:
    root = Path(root)
    out = []
    for p in _files(root):
        rel = p.relative_to(root).as_posix()
        if re.search(r"(sshd_config|nginx|\.conf$|Dockerfile|compose\.ya?ml$|docker-compose|(^|/)\.env)", rel):
            t = _read(p)
            if t is not None:
                out.append((rel, t))
    return out


def _report(kind: str, findings: list[Finding], note: str) -> dict[str, Any]:
    findings.sort(key=lambda f: (SEVERITIES.index(f.severity), f.where))
    counts = {s: sum(1 for f in findings if f.severity == s) for s in SEVERITIES}
    return {"kind": kind, "findings": [asdict(f) for f in findings[:200]], "total": len(findings), "counts": counts, "note": note}


def report_markdown(r: dict[str, Any]) -> str:
    lines = [f"**{r['kind']}** — {r['note']}"]
    if not r["findings"]:
        lines.append("\nNothing stood out.")
    for f in r["findings"][:30]:
        ref = f" ({f['ref']})" if f.get("ref") else ""
        lines.append(f"\n- **[{f['severity'].upper()}] {f['title']}**{ref} — `{f['where']}`\n  {f['evidence']}\n  Fix: {f['fix']}")
    if r["total"] > 30:
        lines.append(f"\n…and {r['total'] - 30} more.")
    lines.append("\nAsk me about any finding and I'll explain it or help you fix it.")
    return "\n".join(lines)


# ---- what the user asked for ------------------------------------------------------------------------------
_CODE = re.compile(r"\b(audit|review|check|scan|analy[sz]e|look at)\b.*\b(my |this |the )?(code|project|repo|codebase|source)\b.*\b(secur|vuln|safe|secret|risk)"
                   r"|\b(secur\w*|vulnerabilit\w*)\s+(review|audit|check)\b.*\b(code|project|repo|codebase)\b"
                   r"|\b(find|look for)\b.*\b(secrets|hard.?coded (keys|passwords))\b", re.I)
_DEPS = re.compile(r"\b(dependenc\w+|packages?|libraries|requirements|npm|pip)\b.*\b(vuln\w*|secur\w*|outdated|audit|cve)"
                   r"|\b(audit|check|scan)\b.*\b(dependenc\w+|packages|libraries|requirements)\b", re.I)
_CONF = re.compile(r"\b(audit|review|check|scan|harden)\b.*\b(config\w*|sshd?|nginx|dockerfile|docker.?compose|\.env)\b"
                   r"|\b(config\w*|sshd?|nginx|dockerfile)\b.*\b(secur\w*|safe|harden\w*|risk\w*|vuln\w*)", re.I)


def parse_request(text: str) -> str | None:
    """'code_audit', 'deps_audit', 'config_audit' or None."""
    t = text or ""
    if _DEPS.search(t):
        return "deps_audit"
    if _CONF.search(t):
        return "config_audit"
    if _CODE.search(t):
        return "code_audit"
    return None
