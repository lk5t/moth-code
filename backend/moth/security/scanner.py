"""2.0 chat pentesting: "check 10.0.0.5:8080 for vulnerabilities" → one Yes → a safe scan from this computer.

What it does, in order, and only after the user confirmed the exact target:

1. TCP connect scan of the asked ports (or ~40 common ones), with a global speed limit.
2. Reads what each open port says about itself (banners, HTTP headers, TLS certificate, a harmless PING to Redis).
3. Looks-only checks: known-vulnerable versions, services that should not be exposed, missing web security
   headers, exposed files such as ``/.git/HEAD`` and ``/.env``, directory listings, weak TLS.

Nothing here logs in, sends exploits or changes anything. The one stronger step (trying an anonymous FTP login)
is only offered, and runs only after a second Yes for that step. Every connection is written to the scan's log,
together with when the user confirmed. Scans run from the user's own computer, never from MOTH Cloud.

Guard rails: one host per scan (a private /24 at most), at most 1024 ports, no multicast/broadcast/unspecified
addresses, at most two scans at a time, a stop button, and a connection rate limit.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
import secrets
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 111, 135, 139, 143, 443, 445, 465, 587, 993, 995, 1433, 1521, 2049,
                2375, 3000, 3306, 3389, 5000, 5432, 5900, 6379, 8000, 8008, 8080, 8081, 8443, 8888, 9000, 9200,
                11211, 27017]
SERVICE = {21: "ftp", 22: "ssh", 23: "telnet", 25: "smtp", 53: "dns", 80: "http", 110: "pop3", 111: "rpcbind",
           135: "msrpc", 139: "netbios", 143: "imap", 443: "https", 445: "smb", 465: "smtps", 587: "smtp",
           993: "imaps", 995: "pop3s", 1433: "mssql", 1521: "oracle", 2049: "nfs", 2375: "docker", 3000: "http",
           3306: "mysql", 3389: "rdp", 5000: "http", 5432: "postgresql", 5900: "vnc", 6379: "redis", 8000: "http",
           8008: "http", 8080: "http", 8081: "http", 8443: "https", 8888: "http", 9000: "http", 9200: "elasticsearch",
           11211: "memcached", 27017: "mongodb"}
HTTP_PORTS = {80, 3000, 5000, 8000, 8008, 8080, 8081, 8888, 9000, 9200, 2375}
HTTPS_PORTS = {443, 8443}
MAX_PORTS = 1024
MAX_HOSTS = 256
MAX_RUNNING = 2
RATE_PER_SEC = 150
CONNECT_TIMEOUT = 1.0
SEVERITIES = ["critical", "high", "medium", "low", "info"]

_INTENT = re.compile(
    r"\b(scan|scans|scanning|check|test|pentest|pen-?test|audit|probe|enumerate|assess|"
    r"find\s+(?:any\s+|the\s+|some\s+)?(?:vulns?|vulnerabilit(?:y|ies)|issues|weaknesses|open\s+ports|problems|holes)|"
    r"look\s+for\s+(?:vulns?|vulnerabilit)|vulnerabilit(?:y|ies)\s+(?:on|in|for|at)|vuln\s+scan|port\s*scan)", re.I)
_URL = re.compile(r"\b(https?)://([A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\])(?::(\d{1,5}))?(/[^\s'\"<>]*)?", re.I)
# 2.1: asking about a website or web app (not just a host) starts the website test instead of a port scan
_WEB = re.compile(r"\b(web\s?site|web\s?app\w*|site|page|xss|cross.site|sql\s?injection|sqli|csrf|forms?|open\s?redirect|"
                  r"owasp|web\s?(vuln\w*|security|test\w*))\b", re.I)
_IP = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/(\d{1,2}))?(?::(\d{1,5}))?(?![\w.])")
_HOST = re.compile(r"(?<![\w./@-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}|localhost)(?::(\d{1,5}))?(?![\w-])")
_PORTS = re.compile(r"\bports?\s+((?:\d{1,5}\s*(?:-\s*\d{1,5})?\s*(?:,|and|&|\s)\s*)*\d{1,5}(?:\s*-\s*\d{1,5})?)", re.I)
_FILE_TLD = {"py", "js", "ts", "md", "txt", "json", "html", "css", "sh", "yml", "yaml", "log", "zip", "exe", "png",
             "jpg", "pdf", "toml", "lock", "csv", "xml", "rs", "go", "java", "cpp", "php", "rb"}


class ScanRefused(ValueError):
    pass


@dataclass
class ScanPlan:
    target: str               # what the user wrote (host, IP, CIDR or URL host)
    hosts: list[str]
    ports: list[int]
    default_ports: bool
    scheme: str | None = None
    kind: str = "network"     # 2.1: "network" (ports and services) or "web" (website test)
    path: str = "/"

    def describe(self) -> str:
        if self.kind == "web":
            port = "" if self.ports[0] in (80, 443) else f":{self.ports[0]}"
            return f"the website {self.scheme or 'http'}://{self.target}{port}{self.path}"
        where = self.target if len(self.hosts) == 1 else f"{self.target} ({len(self.hosts)} addresses)"
        if self.default_ports:
            return f"{where}, {len(self.ports)} common ports"
        if len(self.ports) <= 6:
            return f"{where} port{'s' if len(self.ports) > 1 else ''} {', '.join(map(str, self.ports))}"
        return f"{where}, {len(self.ports)} ports ({self.ports[0]}–{self.ports[-1]})"


def _parse_ports(text: str) -> list[int]:
    out: list[int] = []
    for m in _PORTS.finditer(text):
        for part in re.split(r"\s*(?:,|and|&|\s)\s*", m.group(1)):
            if not part:
                continue
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if a > b:
                    a, b = b, a
                if b - a + 1 > MAX_PORTS:
                    raise ScanRefused(f"that is {b - a + 1} ports; one scan checks at most {MAX_PORTS}")
                out += range(a, b + 1)
            else:
                out.append(int(part))
    return out


def parse_request(text: str) -> ScanPlan | None:
    """A scan request in a chat message, or None when the message is not asking for one."""
    if not _INTENT.search(text or ""):
        return None
    target, scheme, ports, path = None, None, [], "/"
    m = _URL.search(text)
    if m:
        scheme, target = m.group(1).lower(), m.group(2).strip("[]")
        if m.group(3):
            ports.append(int(m.group(3)))
        path = (m.group(4) or "/").rstrip(".,)")[:300] or "/"
    if target is None:
        m = _IP.search(text)
        if m and all(0 <= int(p) <= 255 for p in m.group(1).split(".")):
            target = m.group(1) + (f"/{m.group(2)}" if m.group(2) else "")
            if m.group(3):
                ports.append(int(m.group(3)))
    if target is None:
        for m in _HOST.finditer(text):
            tld = m.group(1).rsplit(".", 1)[-1].lower()
            if tld in _FILE_TLD:
                continue
            target = m.group(1).lower()
            if m.group(2):
                ports.append(int(m.group(2)))
            break
    if target is None:
        return None
    ports += _parse_ports(text)
    if scheme and not ports:
        ports = [443 if scheme == "https" else 80]
    default = not ports
    ports = sorted({p for p in (ports or COMMON_PORTS)})
    bad = [p for p in ports if not 1 <= p <= 65535]
    if bad:
        raise ScanRefused(f"not a valid port: {bad[0]}")
    if len(ports) > MAX_PORTS:
        raise ScanRefused(f"one scan checks at most {MAX_PORTS} ports")
    hosts = _expand(target)
    if _WEB.search(text) and len(hosts) == 1 and (scheme or len(ports) == 1):
        port = ports[0] if not default else (443 if scheme == "https" else 80)
        return ScanPlan(target=target, hosts=hosts, ports=[port], default_ports=False,
                        scheme=scheme or ("https" if port in HTTPS_PORTS else "http"), kind="web", path=path)
    return ScanPlan(target=target, hosts=hosts, ports=ports, default_ports=default, scheme=scheme)


def _expand(target: str) -> list[str]:
    if "/" in target:
        try:
            net = ipaddress.ip_network(target, strict=False)
        except ValueError as e:
            raise ScanRefused(f"not a valid address range: {target}") from e
        if net.num_addresses > MAX_HOSTS:
            raise ScanRefused(f"{target} is {net.num_addresses} addresses; MOTH scans one host or a small "
                              f"private network (/24 at most) at a time")
        if not net.is_private:
            raise ScanRefused("address ranges can only be scanned on private networks (your home or lab); "
                              "scan public systems one address at a time")
        hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
    else:
        hosts = [target]
    for h in hosts:
        _check_address(h)
    return hosts


def _check_address(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return  # a name; checked again once resolved
    if ip.is_multicast or ip.is_unspecified or ip.is_reserved or str(ip) == "255.255.255.255":
        raise ScanRefused(f"{host} is not a single machine (multicast, broadcast or reserved address)")


# ---- findings ---------------------------------------------------------------------------------------------

@dataclass
class Finding:
    severity: str
    title: str
    port: int | None
    evidence: str
    fix: str
    host: str = ""
    ref: str = ""

    def key(self) -> tuple:
        return (self.host, self.port, self.title)


def _version(text: str, name: str) -> tuple[int, ...] | None:
    m = re.search(re.escape(name) + r"[/_ ]v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", text, re.I)
    return tuple(int(x) for x in m.groups() if x is not None) if m else None


def version_findings(text: str, port: int | None, host: str = "") -> list[Finding]:
    """Known-vulnerable or out-of-support versions named in a banner or HTTP header."""
    out: list[Finding] = []

    def add(sev, title, evidence, fix, ref=""):
        out.append(Finding(sev, title, port, evidence, fix, host, ref))

    if v := _version(text, "OpenSSH"):
        ev = f"SSH banner: {text.strip()[:120]}"
        backport = " Linux distributions often backport fixes, so check the installed package version too."
        if v < (7, 7):
            add("medium", f"Old OpenSSH {'.'.join(map(str, v))} (username enumeration, end of support)", ev,
                "Update OpenSSH to a current release." + backport, "CVE-2018-15473")
        elif (8, 5) <= v[:2] <= (9, 7):
            add("high", f"OpenSSH {'.'.join(map(str, v))} may be affected by regreSSHion", ev,
                "Update OpenSSH to 9.8 or later, or set LoginGraceTime 0 until you can." + backport, "CVE-2024-6387")
    if v := _version(text, "Apache"):
        ev = f"Server header: {text.strip()[:120]}"
        if v[:3] == (2, 4, 49):
            add("critical", "Apache 2.4.49 path traversal and remote code execution", ev,
                "Update Apache HTTP Server to 2.4.51 or later now.", "CVE-2021-41773")
        elif v[:3] == (2, 4, 50):
            add("critical", "Apache 2.4.50 path traversal and remote code execution", ev,
                "Update Apache HTTP Server to 2.4.51 or later now.", "CVE-2021-42013")
        elif v[:2] < (2, 4):
            add("high", f"Apache {'.'.join(map(str, v))} is no longer supported", ev,
                "Move to a supported Apache 2.4 release.")
    if (v := _version(text, "Microsoft-IIS")) and v[:2] <= (6, 0):
        add("critical", "IIS 6.0 (WebDAV buffer overflow, no longer supported)", f"Server header: {text.strip()[:120]}",
            "Replace this server; IIS 6.0 has had no security updates since 2015.", "CVE-2017-7269")
    if (v := _version(text, "PHP")) and v[:2] < (8, 1):
        add("high", f"PHP {'.'.join(map(str, v))} no longer gets security fixes", f"Header: {text.strip()[:120]}",
            "Upgrade to a supported PHP release, and hide the version (expose_php = Off).")
    if (v := _version(text, "OpenSSL")) and v[:2] < (1, 1):
        add("high", f"OpenSSL {'.'.join(map(str, v))} is out of support", f"Header: {text.strip()[:120]}",
            "Upgrade OpenSSL (3.x).")
    if re.search(r"vsFTPd 2\.3\.4\b", text, re.I):
        add("critical", "vsftpd 2.3.4 (known backdoored release)", f"FTP banner: {text.strip()[:120]}",
            "Remove this build and install a current vsftpd from your distribution.", "CVE-2011-2523")
    if re.search(r"ProFTPD 1\.3\.5\b", text, re.I):
        add("critical", "ProFTPD 1.3.5 mod_copy lets anyone copy files", f"FTP banner: {text.strip()[:120]}",
            "Update ProFTPD, or disable mod_copy.", "CVE-2015-3306")
    return out


EXPOSED = {  # port: (severity, title, fix)
    23: ("high", "Telnet is open (passwords travel in clear text)", "Turn Telnet off and use SSH."),
    21: ("medium", "FTP is open (clear-text logins)", "Use SFTP or FTPS instead, or limit who can reach it."),
    445: ("medium", "SMB file sharing is reachable", "Do not expose SMB beyond your local network; block port 445 at the firewall."),
    139: ("medium", "NetBIOS is reachable", "Block port 139 outside your local network."),
    135: ("low", "Windows RPC is reachable", "Block port 135 outside your local network."),
    3389: ("medium", "Remote Desktop is reachable", "Put RDP behind a VPN, require Network Level Authentication and strong passwords."),
    5900: ("medium", "VNC is reachable", "Put VNC behind a VPN or SSH tunnel and set a strong password."),
    3306: ("medium", "MySQL database port is reachable", "Bind the database to localhost or a private network and firewall it."),
    5432: ("medium", "PostgreSQL database port is reachable", "Bind the database to localhost or a private network and firewall it."),
    1433: ("medium", "SQL Server port is reachable", "Firewall the database so only your application servers can reach it."),
    1521: ("medium", "Oracle database port is reachable", "Firewall the database so only your application servers can reach it."),
    27017: ("medium", "MongoDB port is reachable", "Bind MongoDB to localhost/private addresses and enable authentication."),
    111: ("low", "rpcbind is reachable", "Block port 111 unless you need NFS from outside."),
    2049: ("medium", "NFS is reachable", "Limit NFS exports to trusted addresses and firewall port 2049."),
}


# ---- the scan ---------------------------------------------------------------------------------------------

class _Rate:
    def __init__(self, per_sec: int):
        self.gap = 1.0 / per_sec
        self.next = time.monotonic()
        self.lock = threading.Lock()

    def wait(self, cancel: threading.Event) -> bool:
        with self.lock:
            now = time.monotonic()
            at = max(now, self.next)
            self.next = at + self.gap
        delay = at - time.monotonic()
        return not (delay > 0 and cancel.wait(delay)) and not cancel.is_set()


_RATE = _Rate(RATE_PER_SEC)


@dataclass
class Scan:
    id: str
    target: str
    hosts: list[str]
    ports: list[int]
    confirmed_at: float
    status: str = "running"         # running | done | stopped | error
    phase: str = "Starting"
    progress: float = 0.0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    open_ports: list[dict[str, Any]] = field(default_factory=list)
    findings: list[dict[str, Any]] = field(default_factory=list)
    stronger: list[dict[str, Any]] = field(default_factory=list)   # offered stronger steps
    log: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    resolved: dict[str, str] = field(default_factory=dict)
    kind: str = "network"
    scheme: str | None = None
    path: str = "/"

    def public(self, with_log: bool = False) -> dict[str, Any]:
        d = asdict(self)
        if not with_log:
            d["log_count"] = len(d.pop("log"))
        d["counts"] = {s: sum(1 for f in self.findings if f["severity"] == s) for s in SEVERITIES}
        return d


class ScanManager:
    def __init__(self, home: Path, publish: Callable[[dict[str, Any]], None] = lambda e: None,
                 connect: Callable[..., socket.socket] | None = None):
        self.dir = Path(home) / "scans"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.publish = publish
        self._connect = connect or socket.create_connection
        self._scans: dict[str, Scan] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._load()

    # -- storage
    def _load(self) -> None:
        for p in sorted(self.dir.glob("*.json"))[-200:]:
            try:
                s = Scan(**json.loads(p.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                continue
            if s.status == "running":
                s.status, s.phase = "stopped", "Stopped (MOTH was closed)"
            self._scans[s.id] = s

    def _save(self, s: Scan) -> None:
        tmp = self.dir / f"{s.id}.tmp"
        tmp.write_text(json.dumps(asdict(s)), encoding="utf-8")
        tmp.replace(self.dir / f"{s.id}.json")

    def _emit(self, s: Scan, kind: str = "progress") -> None:
        self.publish({"kind": kind, "scan": s.public()})

    def _log(self, s: Scan, action: str, **kw) -> None:
        s.log.append({"at": time.time(), "action": action, **kw})

    # -- api
    def list(self) -> list[dict[str, Any]]:
        return [s.public() for s in sorted(self._scans.values(), key=lambda x: x.started_at, reverse=True)]

    def get(self, sid: str, with_log: bool = True) -> dict[str, Any]:
        s = self._scans.get(sid)
        if not s:
            raise KeyError(sid)
        return s.public(with_log)

    def delete(self, sid: str) -> None:
        self.stop(sid)
        self._scans.pop(sid, None)
        (self.dir / f"{sid}.json").unlink(missing_ok=True)

    def stop(self, sid: str | None = None) -> int:
        ids = [sid] if sid else list(self._cancel)
        n = 0
        for i in ids:
            ev = self._cancel.get(i)
            if ev and not ev.is_set():
                ev.set()
                n += 1
        return n

    def start(self, plan: ScanPlan, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise ScanRefused("MOTH needs your Yes before it scans anything")
        with self._lock:
            running = sum(1 for s in self._scans.values() if s.status == "running")
            if running >= MAX_RUNNING:
                raise ScanRefused(f"{running} scans are already running; wait for one to finish or stop it")
            s = Scan(id=time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3), target=plan.target, hosts=plan.hosts,
                     ports=plan.ports, confirmed_at=time.time(), kind=plan.kind, scheme=plan.scheme, path=plan.path)
            self._scans[s.id] = s
            self._cancel[s.id] = threading.Event()
        self._log(s, "confirmed", target=plan.describe())
        self._save(s)
        threading.Thread(target=self._run, args=(s,), daemon=True, name=f"scan-{s.id}").start()
        self._emit(s, "started")
        return s.public()

    # -- running
    def _run(self, s: Scan) -> None:
        cancel = self._cancel[s.id]
        try:
            s.phase = "Finding the target"
            for h in s.hosts:
                try:
                    ip = socket.getaddrinfo(h, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
                except (socket.gaierror, IndexError):
                    try:
                        ip = socket.getaddrinfo(h, None)[0][4][0]
                    except socket.gaierror as e:
                        raise ScanRefused(f"cannot find {h}: {e.strerror or e}") from None
                _check_address(ip)
                s.resolved[h] = ip
                self._log(s, "resolve", host=h, ip=ip)
            if s.kind == "web":
                self._web_test(s, cancel)
                s.status = "stopped" if cancel.is_set() else "done"
                s.phase = "Stopped" if cancel.is_set() else "Finished"
                s.progress = s.progress if cancel.is_set() else 1.0
                return
            s.phase = "Scanning ports"
            jobs = [(h, p) for h in s.hosts for p in s.ports]
            done = 0
            last_emit = 0.0

            def probe(hp):
                h, p = hp
                if not _RATE.wait(cancel):
                    return None
                ip = s.resolved[h]
                try:
                    sock = self._connect((ip, p), timeout=CONNECT_TIMEOUT)
                except OSError:
                    return None
                try:
                    sock.close()
                except OSError:
                    pass
                return h, p

            with ThreadPoolExecutor(max_workers=min(64, max(1, len(jobs)))) as pool:
                for res in pool.map(probe, jobs):
                    done += 1
                    if res:
                        h, p = res
                        self._log(s, "open", host=h, port=p)
                        s.open_ports.append({"host": h, "port": p, "service": SERVICE.get(p, "unknown"), "banner": ""})
                        self._emit(s, "port")
                    s.progress = 0.6 * done / len(jobs)
                    if time.time() - last_emit > 0.4:
                        last_emit = time.time()
                        self._emit(s)
                    if cancel.is_set():
                        break
            self._log(s, "connect_scan", tried=done, open=len(s.open_ports))
            s.phase = "Looking at open services"
            for i, op in enumerate(list(s.open_ports)):
                if cancel.is_set():
                    break
                self._inspect(s, op, cancel)
                s.progress = 0.6 + 0.4 * (i + 1) / max(1, len(s.open_ports))
                self._emit(s)
            self._offer_stronger(s)
            s.status = "stopped" if cancel.is_set() else "done"
            s.phase = "Stopped" if cancel.is_set() else "Finished"
            s.progress = s.progress if cancel.is_set() else 1.0
        except ScanRefused as e:
            s.status, s.error, s.phase = "error", str(e), "Could not scan"
        except Exception as e:  # noqa: BLE001 - a scan must always finish with a status
            s.status, s.error, s.phase = "error", f"{type(e).__name__}: {e}", "Could not scan"
        finally:
            s.finished_at = time.time()
            s.findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), f.get("port") or 0))
            self._log(s, "finished", status=s.status)
            self._save(s)
            self._cancel.pop(s.id, None)
            self._emit(s, "finished")

    def _add(self, s: Scan, f: Finding) -> None:
        if any((x["host"], x["port"], x["title"]) == f.key() for x in s.findings):
            return
        s.findings.append(asdict(f))
        self._emit(s, "finding")

    def _raw(self, ip: str, port: int, send: bytes | None = None, timeout: float = 2.0) -> str:
        sock = self._connect((ip, port), timeout=timeout)
        try:
            sock.settimeout(timeout)
            if send:
                sock.sendall(send)
            try:
                data = sock.recv(2048)
            except (socket.timeout, OSError):
                data = b""
            return data.decode("latin-1", errors="replace")
        finally:
            sock.close()

    def _http(self, s: Scan, host: str, ip: str, port: int, tls: bool, path: str = "/", method: str = "GET"):
        cls = http.client.HTTPSConnection if tls else http.client.HTTPConnection
        kw: dict[str, Any] = {"timeout": 4}
        if tls:
            kw["context"] = ssl._create_unverified_context()  # we inspect the certificate separately
        conn = cls(ip, port, **kw)
        try:
            conn.request(method, path, headers={"Host": host, "User-Agent": "MOTH-security-check/2.0", "Accept": "*/*"})
            r = conn.getresponse()
            body = r.read(65536).decode("utf-8", errors="replace")
            self._log(s, "http", host=host, port=port, path=path, status=r.status)
            return r.status, {k.lower(): v for k, v in r.getheaders()}, body
        finally:
            conn.close()

    def _inspect(self, s: Scan, op: dict[str, Any], cancel: threading.Event) -> None:
        host, port = op["host"], op["port"]
        ip = s.resolved[host]
        svc = op["service"]
        try:
            if port in HTTPS_PORTS or svc in ("https",):
                self._inspect_tls(s, host, ip, port)
                self._inspect_http(s, host, ip, port, tls=True)
            elif port in HTTP_PORTS or svc == "http":
                self._inspect_http(s, host, ip, port, tls=False)
            elif port == 6379:
                reply = self._raw(ip, port, b"PING\r\n")
                self._log(s, "redis_ping", host=host, port=port)
                op["banner"] = reply.strip()[:80]
                if reply.startswith("+PONG"):
                    self._add(s, Finding("high", "Redis answers without a password", port, "PING → +PONG",
                                         "Set requirepass (or ACLs), bind Redis to localhost and firewall port 6379.", host))
            elif port == 11211:
                reply = self._raw(ip, port, b"version\r\n")
                self._log(s, "memcached_version", host=host, port=port)
                op["banner"] = reply.strip()[:80]
                if reply.startswith("VERSION"):
                    self._add(s, Finding("high", "Memcached is open to anyone", port, reply.strip()[:80],
                                         "Bind memcached to localhost and disable UDP (-U 0).", host))
            else:
                banner = self._raw(ip, port)
                self._log(s, "banner", host=host, port=port)
                op["banner"] = banner.strip()[:160]
                if not banner.strip():  # silent until spoken to: most often a web server on an unusual port
                    try:
                        self._inspect_http(s, host, ip, port, tls=False)
                        op["service"] = "http"
                        return self._exposed(s, op, ip)
                    except (OSError, http.client.HTTPException, ValueError):
                        pass
                if banner.startswith("SSH-"):
                    op["service"] = "ssh"
                elif banner.startswith("RFB "):
                    op["service"] = "vnc"
                for f in version_findings(banner, port, host):
                    self._add(s, f)
        except (OSError, ssl.SSLError, http.client.HTTPException, ValueError) as e:
            self._log(s, "inspect_error", host=host, port=port, error=str(e)[:200])
        self._exposed(s, op, ip)

    def _exposed(self, s: Scan, op: dict[str, Any], ip: str) -> None:
        host, port = op["host"], op["port"]
        if port in EXPOSED:
            sev, title, fix = EXPOSED[port]
            public = not ipaddress.ip_address(ip).is_private
            if public and sev == "medium":
                sev = "high"
            self._add(s, Finding(sev, title + (" from the internet" if public else ""), port,
                                 f"Port {port} ({SERVICE.get(port, 'service')}) accepted a connection"
                                 + (f"; banner: {op['banner'][:80]}" if op.get("banner") else ""), fix, host))

    def _inspect_tls(self, s: Scan, host: str, ip: str, port: int) -> None:
        name = host if not _is_ip(host) else None
        ctx = ssl.create_default_context()
        if not name:
            ctx.check_hostname = False
        try:
            with self._connect((ip, port), timeout=4) as raw, ctx.wrap_socket(raw, server_hostname=name) as tls:
                ver = tls.version()
            self._log(s, "tls", host=host, port=port, version=ver)
        except ssl.SSLCertVerificationError as e:
            msg = (e.verify_message or str(e)).lower()
            self._log(s, "tls", host=host, port=port, error=msg)
            if "expired" in msg:
                self._add(s, Finding("high", "TLS certificate has expired", port, e.verify_message or str(e),
                                     "Renew the certificate (for example with Let's Encrypt) and set up automatic renewal.", host))
            elif "self" in msg and "signed" in msg:
                self._add(s, Finding("medium", "TLS certificate is self-signed", port, e.verify_message or str(e),
                                     "Use a certificate from a trusted authority so browsers and clients can verify the server.", host))
            elif "hostname" in msg or "mismatch" in msg:
                self._add(s, Finding("medium", "TLS certificate is for a different name", port, e.verify_message or str(e),
                                     "Issue a certificate that covers this host name.", host))
            else:
                self._add(s, Finding("medium", "TLS certificate cannot be verified", port, e.verify_message or str(e),
                                     "Serve the full certificate chain from a trusted authority.", host))
        except (OSError, ssl.SSLError) as e:
            self._log(s, "tls_error", host=host, port=port, error=str(e)[:200])
            return
        old = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        old.check_hostname, old.verify_mode = False, ssl.CERT_NONE
        try:
            old.minimum_version = ssl.TLSVersion.TLSv1
            old.maximum_version = ssl.TLSVersion.TLSv1_1
            old.set_ciphers("DEFAULT:@SECLEVEL=0")
            with self._connect((ip, port), timeout=4) as raw, old.wrap_socket(raw, server_hostname=name) as tls:
                ver = tls.version()
            self._log(s, "tls_old", host=host, port=port, accepted=ver)
            self._add(s, Finding("medium", f"Server still accepts {ver}", port, f"Handshake with {ver} succeeded",
                                 "Allow only TLS 1.2 and 1.3.", host))
        except (OSError, ssl.SSLError, ValueError):
            pass  # refused (good) or not testable with this computer's OpenSSL

    def _inspect_http(self, s: Scan, host: str, ip: str, port: int, tls: bool) -> None:
        status, headers, body = self._http(s, host, ip, port, tls)
        server = headers.get("server", "")
        powered = headers.get("x-powered-by", "")
        op = next(o for o in s.open_ports if o["host"] == host and o["port"] == port)
        op["banner"] = " · ".join(x for x in (f"HTTP {status}", server, powered) if x)[:160]
        for text in (server, powered):
            for f in version_findings(text, port, host):
                self._add(s, f)
        if re.search(r"\d", server) or powered:
            self._add(s, Finding("low", "Server reveals its software version", port, f"Server: {server}" + (f" · X-Powered-By: {powered}" if powered else ""),
                                 "Hide version details (Apache: ServerTokens Prod; nginx: server_tokens off; PHP: expose_php Off).", host))
        if port == 9200 and '"cluster_name"' in body:
            self._add(s, Finding("high", "Elasticsearch answers without a login", port, "GET / returned cluster information",
                                 "Enable Elasticsearch security (authentication) and do not expose port 9200.", host))
        if port == 2375:
            try:
                st, _, b = self._http(s, host, ip, port, False, "/version")
                if st == 200 and "ApiVersion" in b:
                    self._add(s, Finding("critical", "Docker API is open without TLS (full control of the machine)", port,
                                         "GET /version answered", "Never expose the Docker socket; use SSH or TLS with client certificates.", host))
            except (OSError, http.client.HTTPException):
                pass
        if re.search(r"<title>\s*Index of /", body, re.I):
            self._add(s, Finding("medium", "Directory listing is turned on", port, "GET / shows 'Index of /'",
                                 "Turn off directory listing (Apache: Options -Indexes; nginx: autoindex off).", host))
        if status < 400 or status in (401, 403):
            missing = []
            if tls and "strict-transport-security" not in headers:
                missing.append("Strict-Transport-Security")
            if "x-content-type-options" not in headers:
                missing.append("X-Content-Type-Options")
            csp = headers.get("content-security-policy", "")
            if "x-frame-options" not in headers and "frame-ancestors" not in csp:
                missing.append("X-Frame-Options (or CSP frame-ancestors)")
            if not csp:
                missing.append("Content-Security-Policy")
            if missing:
                self._add(s, Finding("low", "Missing security headers", port, "Not sent: " + ", ".join(missing),
                                     "Add the missing headers in your web server or app (they are one line each).", host))
            cookie = headers.get("set-cookie", "")
            if cookie and ("httponly" not in cookie.lower() or (tls and "secure" not in cookie.lower())):
                self._add(s, Finding("low", "Cookie set without HttpOnly/Secure", port, cookie.split(";")[0][:60] + "…",
                                     "Mark session cookies HttpOnly, Secure and SameSite.", host))
        # exposed files (plain GETs; nothing is changed). A random path first, so a site that answers 200 to everything
        # is not reported.
        try:
            ref_status, _, ref_body = self._http(s, host, ip, port, tls, f"/moth-check-{secrets.token_hex(4)}")
        except (OSError, http.client.HTTPException):
            return
        soft404 = ref_status == 200
        checks = [("/.git/HEAD", lambda b: b.startswith("ref:") or re.fullmatch(r"[0-9a-f]{40}\s*", b) is not None,
                   "critical", "Git repository is downloadable (/.git/)", "Block /.git in the web server and remove it from the web root; rotate any secrets that were in it."),
                  ("/.env", lambda b: re.search(r"^[A-Z][A-Z0-9_]{2,}=", b, re.M) is not None and "<html" not in b.lower(),
                   "critical", "Environment file with secrets is downloadable (/.env)", "Remove .env from the web root, block dotfiles, and rotate every secret in it."),
                  ("/server-status", lambda b: "Apache Server Status" in b, "medium", "Apache server-status page is public",
                   "Restrict /server-status to localhost (Require local)."),
                  ("/phpinfo.php", lambda b: "phpinfo()" in b or "PHP Version" in b, "medium", "phpinfo() page is public",
                   "Delete phpinfo.php from the server.")]
        for path, test, sev, title, fix in checks:
            try:
                st, _, b = self._http(s, host, ip, port, tls, path)
            except (OSError, http.client.HTTPException):
                continue
            if st == 200 and test(b) and not (soft404 and b == ref_body):
                self._add(s, Finding(sev, title, port, f"GET {path} → 200", fix, host))

    # ---- 2.1 website test ------------------------------------------------------------------------------
    WEB_MAX_PAGES = 12
    WEB_MAX_PROBES = 24
    SQL_ERRORS = re.compile(r"you have an error in your sql syntax|warning: mysql|mysqli?_|unclosed quotation mark|"
                            r"quoted string not properly terminated|pg::syntaxerror|psycopg2\.|sqlite3?::|sqlite_error|"
                            r"ora-\d{5}|syntax error at or near|unterminated quoted string|sqlstate\[", re.I)
    REDIRECT_PARAMS = {"next", "url", "redirect", "redirect_uri", "redirect_url", "return", "returnto", "return_to",
                       "continue", "dest", "destination", "goto"}

    def _web_test(self, s: Scan, cancel: threading.Event) -> None:
        """Looks at the site's pages and forms, then sends a few harmless test values (GET only, never submits
        forms, never changes data): unencoded reflection (possible XSS), database errors on a quote (possible
        SQL injection), open redirects, and forms without CSRF protection."""
        from html.parser import HTMLParser
        from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

        host, port, tls = s.hosts[0], s.ports[0], (s.scheme == "https")
        ip = s.resolved[host]
        base = f"{s.scheme}://{host}{'' if port in (80, 443) else f':{port}'}"
        s.open_ports.append({"host": host, "port": port, "service": "https" if tls else "http", "banner": ""})

        class Page(HTMLParser):
            def __init__(self):
                super().__init__()
                self.links, self.forms, self._form = [], [], None

            def handle_starttag(self, tag, attrs):
                a = dict(attrs)
                if tag == "a" and a.get("href"):
                    self.links.append(a["href"])
                elif tag == "form":
                    self._form = {"method": (a.get("method") or "get").lower(), "action": a.get("action") or "", "inputs": []}
                    self.forms.append(self._form)
                elif tag in ("input", "textarea", "select") and self._form is not None:
                    self._form["inputs"].append({"name": a.get("name") or "", "type": (a.get("type") or "text").lower()})

            def handle_endtag(self, tag):
                if tag == "form":
                    self._form = None

        def get(path):
            if not _RATE.wait(cancel):
                raise OSError("stopped")
            return self._http(s, host, ip, port, tls, path)

        s.phase = "Reading the site"
        try:
            self._inspect_http(s, host, ip, port, tls)  # headers, versions, exposed files, directory listing
            if tls:
                self._inspect_tls(s, host, ip, port)
        except (OSError, http.client.HTTPException, ssl.SSLError) as e:
            raise ScanRefused(f"the website did not answer: {str(e)[:120]}") from None
        queue, seen, params = [s.path or "/"], set(), []   # params: (path, name, other query pairs)
        pages = 0
        while queue and pages < self.WEB_MAX_PAGES and not cancel.is_set():
            path = queue.pop(0)
            if path in seen:
                continue
            seen.add(path)
            try:
                status, headers, body = get(path)
            except (OSError, http.client.HTTPException):
                continue
            pages += 1
            s.progress = 0.4 * pages / self.WEB_MAX_PAGES
            self._emit(s)
            if "html" not in headers.get("content-type", "html"):
                continue
            pg = Page()
            try:
                pg.feed(body)
            except Exception:  # noqa: BLE001 - broken HTML is still a page
                pass
            for href in pg.links:
                u = urlsplit(urljoin(base + path, href))
                if u.scheme in ("http", "https") and u.hostname == host and (u.port or (443 if u.scheme == "https" else 80)) == port:
                    p = (u.path or "/") + (f"?{u.query}" if u.query else "")
                    if p not in seen and len(queue) < 50:
                        queue.append(p)
                    q = parse_qsl(u.query, keep_blank_values=True)
                    for i, (k, _) in enumerate(q):
                        params.append((u.path or "/", k, q[:i] + q[i + 1:]))
            for f in pg.forms:
                names = [i["name"] for i in f["inputs"] if i["name"]]
                if f["method"] == "post" and not any(re.search(r"csrf|xsrf|token|authenticity|nonce", n, re.I) for n in names):
                    self._add(s, Finding("medium", "Form without a CSRF token", port, f"POST form on {path} (fields: {', '.join(names[:6]) or 'none'})",
                                         "Add a per-session CSRF token to every form that changes something, and set SameSite cookies.", host, "CWE-352"))
                if not tls and any(i["type"] == "password" for i in f["inputs"]):
                    self._add(s, Finding("high", "Password form over plain HTTP", port, f"login form on {path}",
                                         "Serve the site only over HTTPS and redirect HTTP to HTTPS.", host, "CWE-319"))
                if f["method"] == "get":
                    action = urlsplit(urljoin(base + path, f["action"] or path)).path or "/"
                    for n in names:
                        params.append((action, n, [(o, "1") for o in names if o != n]))
        # harmless probes, one parameter at a time
        uniq = list({(p, n): (p, n, rest) for p, n, rest in params}.values())[: self.WEB_MAX_PROBES]
        s.phase = f"Testing {len(uniq)} input{'s' if len(uniq) != 1 else ''} with harmless values"
        marker = "moth" + secrets.token_hex(3)
        for i, (path, name, rest) in enumerate(uniq):
            if cancel.is_set():
                break
            q = lambda v: path + "?" + urlencode(rest + [(name, v)])  # noqa: E731
            try:
                _, _, body = get(q(f"{marker}<x\">"))
                if f"{marker}<x\">" in body:
                    self._add(s, Finding("high", "Input shown back without encoding (possible XSS)", port,
                                         f"parameter '{name}' on {path} returns <x\"> unchanged",
                                         "Encode output for where it is placed (HTML, attribute, JavaScript), and add a Content-Security-Policy.", host, "CWE-79"))
                _, _, normal = get(q("1"))
                _, _, quoted = get(q("1'"))
                if self.SQL_ERRORS.search(quoted) and not self.SQL_ERRORS.search(normal):
                    self._add(s, Finding("critical", "Database error on a quote (possible SQL injection)", port,
                                         f"parameter '{name}' on {path} shows a database error for 1'",
                                         "Use parameterised queries everywhere and hide database errors from visitors.", host, "CWE-89"))
                if name.lower() in self.REDIRECT_PARAMS:
                    st, hd, _ = get(q("https://example.org/moth-check"))
                    if 300 <= st < 400 and hd.get("location", "").startswith("https://example.org/moth-check"):
                        self._add(s, Finding("medium", "Open redirect", port, f"parameter '{name}' on {path} redirects anywhere",
                                             "Only redirect to your own paths or an allow-list of sites.", host, "CWE-601"))
            except (OSError, http.client.HTTPException):
                continue
            s.progress = 0.4 + 0.6 * (i + 1) / max(1, len(uniq))
            self._emit(s)
        self._log(s, "web_test", pages=pages, inputs=len(uniq))

    def _offer_stronger(self, s: Scan) -> None:
        for op in s.open_ports:
            if op["port"] == 21 or op.get("service") == "ftp":
                s.stronger.append({"id": f"ftp-anon-{op['host']}-{op['port']}", "check": "ftp_anonymous", "host": op["host"],
                                   "port": op["port"], "status": "offered",
                                   "title": "Try an anonymous FTP login",
                                   "what": "Logs in to FTP as 'anonymous' to see whether anyone can read files. It logs straight out again and changes nothing."})

    def run_stronger(self, sid: str, step_id: str, confirmed: bool) -> dict[str, Any]:
        s = self._scans.get(sid)
        if not s:
            raise KeyError(sid)
        step = next((x for x in s.stronger if x["id"] == step_id), None)
        if not step:
            raise KeyError(step_id)
        if not confirmed:
            raise ScanRefused("this step needs its own Yes")
        if step["status"] == "done":
            return s.public()
        self._log(s, "stronger_confirmed", step=step["check"], host=step["host"], port=step["port"])
        if step["check"] == "ftp_anonymous":
            import ftplib
            ip = s.resolved.get(step["host"], step["host"])
            try:
                ftp = ftplib.FTP()
                ftp.connect(ip, step["port"], timeout=5)
                ftp.login("anonymous", "anonymous@example.com")
                listing = []
                try:
                    listing = ftp.nlst()[:10]
                except ftplib.all_errors:
                    pass
                ftp.quit()
                step["result"] = "Anonymous login worked"
                self._add(s, Finding("high", "Anyone can log in to FTP anonymously", step["port"],
                                     "anonymous login accepted" + (f"; files: {', '.join(listing)}" if listing else ""),
                                     "Disable anonymous FTP (vsftpd: anonymous_enable=NO).", step["host"]))
            except ftplib.all_errors as e:
                step["result"] = f"Anonymous login refused ({str(e)[:80]})"
            self._log(s, "stronger_done", step=step["check"], result=step["result"])
        step["status"] = "done"
        s.findings.sort(key=lambda f: (SEVERITIES.index(f["severity"]), f.get("port") or 0))
        self._save(s)
        self._emit(s, "finished")
        return s.public()


def _is_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def summary_markdown(scan: dict[str, Any]) -> str:
    """What MOTH says in chat about a finished scan: plain-language summary, each finding, and how to fix it."""
    c = scan["counts"]
    opened = scan["open_ports"]
    what = "Website test" if scan.get("kind") == "web" else "Scan"
    lines = [f"**{what} of {scan['target']}** — {scan['status']}"]
    if scan.get("error"):
        lines.append(f"\nThe scan could not finish: {scan['error']}")
        return "\n".join(lines)
    if not opened:
        lines.append(f"\nNo open ports among the {len(scan['ports'])} checked. Either nothing is listening, or a firewall "
                     "is dropping the connections (which is good).")
        return "\n".join(lines)
    total = sum(c.values())
    sev_text = ", ".join(f"{n} {s}" for s, n in c.items() if n)
    if scan.get("kind") != "web":
        lines.append(f"\nOpen ports: {', '.join(str(o['port']) + ' (' + o['service'] + ')' for o in opened[:12])}"
                     + (" …" if len(opened) > 12 else ""))
    lines.append(f"\nFound {total} issue{'s' if total != 1 else ''}" + (f" ({sev_text})." if total else ". Nothing stood out in the safe checks."))
    for f in scan["findings"][:20]:
        ref = f" ({f['ref']})" if f.get("ref") else ""
        lines.append(f"\n- **[{f['severity'].upper()}] {f['title']}**{ref} — port {f['port']}\n  Evidence: {f['evidence']}\n  Fix: {f['fix']}")
    if scan.get("stronger"):
        lines.append("\nA stronger check is available (it asks again before it runs): "
                     + "; ".join(x["title"] for x in scan["stronger"] if x["status"] == "offered") + ".")
    lines.append("\nAsk me about any finding and I'll explain it or help you fix it.")
    return "\n".join(lines)
