"""Engagements (1.0.18): the authorized scope of a security test, enforced on every agent command.

An engagement names what may be tested: hosts, IP addresses or ranges (CIDR) and domains, and optionally
a time window. While one is active, every command MOTH runs, locally or over SSH, is checked before it
starts: if it names a network target outside the scope, or the window is not open, it is refused. Every
command run during the engagement is appended to its log, which becomes the record for the report.

With no active engagement nothing here applies; ordinary coding and server work run as before.
"""

from __future__ import annotations

import ipaddress
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_home: Path | None = None

# file extensions that look like domains in commands ("main.py") and are not network targets
_FILE_EXT = {"py", "js", "ts", "tsx", "jsx", "txt", "json", "md", "sh", "ps1", "yml", "yaml", "toml", "lock", "log",
             "html", "htm", "css", "c", "h", "cc", "cpp", "hpp", "rs", "go", "java", "kt", "xml", "csv", "conf", "cfg",
             "ini", "pem", "key", "crt", "zip", "gz", "tgz", "tar", "exe", "dll", "so", "png", "jpg", "jpeg", "gif",
             "svg", "pdf", "rb", "php", "pl", "sql", "db", "bak", "env", "pyc", "whl", "deb", "rpm", "iso", "img",
             "bin", "out", "o", "a", "lib", "map", "vue", "svelte", "scss", "less", "jsonl", "pcap", "pcapng", "nse",
             "service", "socket", "d", "local", "lan", "internal"}
_IPV4 = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?(?![\w.])")
_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:'\"]+)", re.I)
_USERHOST = re.compile(r"(?<![\w.])[\w.-]+@([A-Za-z0-9.-]+)")
_DOMAIN = re.compile(r"(?<![\w./-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+([A-Za-z]{2,24}))(?![\w/-])")


def configure(home: Path) -> None:
    global _home
    _home = Path(home)


def _file() -> Path:
    if _home is None:
        raise RuntimeError("engagements are not configured")
    return _home / "engagements.json"


def _load() -> dict[str, Any]:
    try:
        return json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"engagements": [], "active": None}


def _save(data: dict[str, Any]) -> None:
    f = _file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(f)


def _clean_scope(scope: list[str]) -> list[str]:
    out = []
    for s in scope:
        s = str(s).strip().lower().rstrip(".")
        if not s:
            continue
        try:
            ipaddress.ip_network(s, strict=False)
        except ValueError:
            if not re.fullmatch(r"(\*\.)?[a-z0-9.-]+", s):
                raise ValueError(f"not a host, IP address, range or domain: {s!r}") from None
        out.append(s)
    if not out:
        raise ValueError("an engagement needs at least one host, IP range or domain in scope")
    return out


def all_() -> dict[str, Any]:
    with _lock:
        return _load()


def create(name: str, scope: list[str], starts_at: float | None = None, ends_at: float | None = None,
           notes: str = "") -> dict[str, Any]:
    eng = {"id": uuid.uuid4().hex[:12], "name": name.strip()[:120] or "Engagement", "scope": _clean_scope(scope),
           "starts_at": starts_at, "ends_at": ends_at, "notes": notes[:4000], "created_at": time.time()}
    if starts_at and ends_at and ends_at <= starts_at:
        raise ValueError("the engagement must end after it starts")
    with _lock:
        data = _load()
        data["engagements"].append(eng)
        _save(data)
    return eng


def delete(eid: str) -> None:
    with _lock:
        data = _load()
        data["engagements"] = [e for e in data["engagements"] if e["id"] != eid]
        if data.get("active") == eid:
            data["active"] = None
        _save(data)


def activate(eid: str | None) -> None:
    with _lock:
        data = _load()
        if eid is not None and not any(e["id"] == eid for e in data["engagements"]):
            raise ValueError("unknown engagement")
        data["active"] = eid
        _save(data)


def active() -> dict[str, Any] | None:
    if _home is None:
        return None
    data = all_()
    return next((e for e in data["engagements"] if e["id"] == data.get("active")), None)


def targets(command: str) -> list[str]:
    """Network targets named in a command: IP addresses and ranges, URL hosts, user@host and domains."""
    found: list[str] = []
    for m in _IPV4.finditer(command):
        ip = m.group(1)
        if all(0 <= int(p) <= 255 for p in ip.split(".")):
            found.append(ip + (f"/{m.group(2)}" if m.group(2) else ""))
    for rx in (_URL, _USERHOST):
        found += [m.group(1).lower() for m in rx.finditer(command)]
    for m in _DOMAIN.finditer(command):
        if m.group(2).lower() not in _FILE_EXT:
            found.append(m.group(1).lower())
    seen, out = set(), []
    for t in found:
        t = t.rstrip(".")
        if t not in seen and t not in ("localhost",):
            seen.add(t)
            out.append(t)
    return out


def _in_scope(target: str, scope: list[str]) -> bool:
    try:
        net = ipaddress.ip_network(target, strict=False)
    except ValueError:
        net = None
    for s in scope:
        try:
            allowed = ipaddress.ip_network(s, strict=False)
        except ValueError:
            allowed = None
        if net is not None and allowed is not None:
            if net.version == allowed.version and net.subnet_of(allowed):
                return True
        elif net is None and allowed is None:
            dom = s[2:] if s.startswith("*.") else s
            if target == dom or target.endswith("." + dom):
                return True
    return False


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    targets: list[str] | None = None


def check(command: str, host: str | None = None) -> Verdict:
    """Is ``command`` (run locally, or on ``host`` over SSH) allowed under the active engagement?"""
    eng = active()
    if eng is None:
        return Verdict(True)
    named = targets(command) + ([host.lower()] if host else [])
    if not named:
        return Verdict(True, targets=[])
    now = time.time()
    if eng.get("starts_at") and now < float(eng["starts_at"]):
        return Verdict(False, f"engagement '{eng['name']}' has not started yet", named)
    if eng.get("ends_at") and now > float(eng["ends_at"]):
        return Verdict(False, f"engagement '{eng['name']}' has ended", named)
    outside = [t for t in named if not _in_scope(t, eng["scope"])]
    if outside:
        return Verdict(False, f"outside the scope of engagement '{eng['name']}': {', '.join(outside)}", named)
    return Verdict(True, targets=named)


def log(command: str, where: str, ok: bool, exit_code: int | None, output: str = "") -> None:
    eng = active()
    if eng is None or _home is None:
        return
    d = _home / "engagements"
    d.mkdir(parents=True, exist_ok=True)
    with _lock, open(d / f"{eng['id']}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.time(), "where": where, "command": command, "ok": ok, "exit_code": exit_code,
                            "output_tail": output[-2000:]}) + "\n")


def read_log(eid: str, limit: int = 500) -> list[dict[str, Any]]:
    if _home is None:
        return []
    p = _home / "engagements" / f"{eid}.jsonl"
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(x) for x in lines if x.strip()]
