"""2.1: self-checked security training examples (CC0, MOTH's own templates).

Three kinds of example, all checked before use:

* **Fix the vulnerable code** — a short snippet with a known weakness (SQL built from strings, shell=True,
  eval, unsafe YAML/pickle, innerHTML, disabled TLS checks …) and its fixed version. MOTH's own code audit
  rules must flag the vulnerable line and must *not* flag the fixed one, so a wrong pair never reaches training.
* **Explain a finding** — what a scan, audit or configuration finding means, how serious it is and how to fix
  it, taken from the same tables the scanner and audits use (so MOTH explains its own findings correctly).
* **Is this setting safe?** — configuration lines (SSH, nginx, Docker) judged by the configuration audit.

Every example keeps to defence: understanding and fixing problems in your own systems.
"""

from __future__ import annotations

import random
from typing import Any, Iterator

# (language, vulnerable template, fixed template); {v}/{t}/{c} are random names
PAIRS: list[tuple[str, str, str]] = [
    ("python", 'cur.execute(f"SELECT * FROM {t} WHERE name = \'{{{v}}}\'")',
     'cur.execute("SELECT * FROM {t} WHERE name = ?", ({v},))'),
    ("python", 'cursor.execute("DELETE FROM {t} WHERE id = " + str({v}))',
     'cursor.execute("DELETE FROM {t} WHERE id = ?", ({v},))'),
    ("python", 'subprocess.run(f"ping -c 1 {{{v}}}", shell=True)',
     'subprocess.run(["ping", "-c", "1", {v}], check=True)'),
    ("python", 'os.system("convert " + {v} + " out.png")',
     'subprocess.run(["convert", {v}, "out.png"], check=True)'),
    ("python", "result = eval({v})", "result = ast.literal_eval({v})"),
    ("python", "config = yaml.load({v})", "config = yaml.safe_load({v})"),
    ("python", "obj = pickle.loads({v})", "obj = json.loads({v})"),
    ("python", "r = requests.get({v}, verify=False)", "r = requests.get({v}, timeout=10)"),
    ("python", "app.run(debug=True)", 'app.run(debug=os.environ.get("FLASK_DEBUG") == "1")'),
    ("javascript", "el.innerHTML = {v};", "el.textContent = {v};"),
    ("javascript", "const out = eval({v});", "const out = JSON.parse({v});"),
    ("javascript", "db.query(`SELECT * FROM {t} WHERE id = ${{{v}}}`);", "db.query(\"SELECT * FROM {t} WHERE id = ?\", [{v}]);"),
    ("javascript", "https.get(url, {{ rejectUnauthorized: false }}, cb);", "https.get(url, cb);"),
    ("php", "echo $_GET['{v}'];", "echo htmlspecialchars($_GET['{v}'], ENT_QUOTES, 'UTF-8');"),
    ("go", "tls.Config{{InsecureSkipVerify: true}}", "tls.Config{{MinVersion: tls.VersionTLS12}}"),
    ("c", "strcpy(buf, {v});", "snprintf(buf, sizeof(buf), \"%s\", {v});"),
]
EXT = {"python": "py", "javascript": "js", "php": "php", "go": "go", "c": "c"}
NAMES = ["user_input", "name", "query", "host", "payload", "data", "filename", "term", "value", "item"]
TABLES = ["users", "orders", "accounts", "products", "sessions"]
FIX_PROMPTS = ["Is this {lang} code safe?\n```{lang}\n{code}\n```",
               "Review this line for security problems:\n```{lang}\n{code}\n```",
               "How do I fix the vulnerability in this code?\n```{lang}\n{code}\n```"]


def _flags(lang: str, line: str) -> list[tuple[str, str, str]]:
    from moth.security.audit import RULES
    ext = EXT[lang]
    return [(title, fix, ref) for langs, rx, _sev, title, fix, ref in RULES if ext in langs and rx.search(line)]


def fix_example(rng: random.Random) -> tuple[str, str] | None:
    lang, bad_t, good_t = rng.choice(PAIRS)
    v, t = rng.choice(NAMES), rng.choice(TABLES)
    if lang == "php":
        v = v.replace("_", "")
    bad, good = bad_t.format(v=v, t=t), good_t.format(v=v, t=t)
    found = _flags(lang, bad)
    if not found or _flags(lang, good):  # the check: the vulnerable line is flagged, the fix is clean
        return None
    title, fix, ref = found[0]
    q = rng.choice(FIX_PROMPTS).format(lang=lang, code=bad)
    a = (f"No — this has a security problem: **{title}** ({ref}).\n\n{fix}\n\nFixed:\n```{lang}\n{good}\n```")
    return q, a


def _finding_tables() -> list[tuple[str, str, str, str]]:
    """(severity, title, fix, reference) from the scanner, audits and configuration checks."""
    from moth.security import audit, scanner
    out = [(sev, title, fix, "") for _p, (sev, title, fix) in scanner.EXPOSED.items()]
    out += [(sev, title, fix, ref) for _l, _rx, sev, title, fix, ref in audit.RULES]
    out += [(sev, title, fix, "") for _f, _rx, sev, title, fix in audit.CONFIG_RULES]
    out += [(sev, f"{name} older than {fixed} ({what})", f"Update {name} to {fixed} or later.", ref)
            for _e, name, fixed, sev, what, ref in audit.KNOWN_VULNS]
    return out


SEVERITY_WORDS = {"critical": "Critical: fix it right away; it can give an attacker control or your data.",
                  "high": "High: fix it soon; it is a real way in or a serious leak.",
                  "medium": "Medium: worth fixing; it makes an attack easier or exposes something it shouldn't.",
                  "low": "Low: a hardening step; small on its own but part of good hygiene.",
                  "info": "Informational: no direct risk, but useful to know."}
EXPLAIN_PROMPTS = ["My security check reported \"{title}\". What does that mean?",
                   "What should I do about this finding: {title}?",
                   "Explain this vulnerability and how to fix it: {title}",
                   "How serious is \"{title}\"?"]


def explain_example(rng: random.Random) -> tuple[str, str] | None:
    sev, title, fix, ref = rng.choice(_finding_tables())
    if sev not in SEVERITY_WORDS:
        return None
    a = f"**{title}**{f' ({ref})' if ref else ''}\n\n{SEVERITY_WORDS[sev]}\n\nHow to fix it: {fix}"
    return rng.choice(EXPLAIN_PROMPTS).format(title=title), a


CONFIG_LINES: list[tuple[str, str, str]] = [
    ("sshd_config", "PermitRootLogin yes", "PermitRootLogin no"),
    ("sshd_config", "PasswordAuthentication yes", "PasswordAuthentication no"),
    ("sshd_config", "PermitEmptyPasswords yes", "PermitEmptyPasswords no"),
    ("nginx.conf", "server_tokens on;", "server_tokens off;"),
    ("nginx.conf", "autoindex on;", "autoindex off;"),
    ("nginx.conf", "ssl_protocols TLSv1 TLSv1.1 TLSv1.2;", "ssl_protocols TLSv1.2 TLSv1.3;"),
    ("docker-compose.yml", "    privileged: true", "    cap_add: [NET_ADMIN]"),
    ("Dockerfile", "ENV API_KEY=changeme", "# pass API_KEY at run time: docker run -e API_KEY=..."),
]


def config_example(rng: random.Random) -> tuple[str, str] | None:
    from moth.security.audit import config_audit
    name, bad, good = rng.choice(CONFIG_LINES)
    found = config_audit([(name, bad)])["findings"]
    if not found or config_audit([(name, good)])["findings"]:
        return None
    f = found[0]
    q = rng.choice([f"Is this line in my {name} safe?\n```\n{bad}\n```", f"Should I change this in {name}?\n```\n{bad}\n```"])
    return q, f"No: **{f['title']}** ({f['severity']}).\n\n{f['fix']}\n\nUse:\n```\n{good}\n```"


def generate(n: int, seed: int = 0, source_id: str | None = None) -> Iterator[dict[str, Any]]:
    rng = random.Random(f"security_explain:{seed}")
    sid = source_id or "synthetic-security_explain"
    made = attempts = 0
    makers = [fix_example, fix_example, explain_example, config_example]
    while made < n and attempts < n * 6:
        attempts += 1
        ex = rng.choice(makers)(rng)
        if ex is None:
            continue
        q, a = ex
        yield {"uid": f"{sid}:{made}", "source": sid, "domain": "code",
               "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}]}
        made += 1
