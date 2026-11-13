#!/usr/bin/env python3
"""MOTH Cloud update agent — keeps a MOTH Cloud installation updated, healthy and recoverable.

Runs next to the MOTH Server, supervised by systemd (or cron where systemd isn't available), and is
deliberately independent of it: standard library only, its own copy of the code, its own process.
If a server update breaks the server, the agent is still there to roll it back.

Every cycle (default every 15 minutes, or immediately when the Owner presses "Check now"):

1. finish or undo any update that was interrupted (agent restart, VPS reboot);
2. read the Owner's controls (pause, rollback request, retries, approved migrations);
3. list releases from the release source (GitHub Releases of the MOTH repository, or a directory),
   verify each signed manifest (ed25519) and hand verified ones to the server, together with the
   desktop and worker files the server distributes;
4. if a newer server release is available on this channel: check disk space and migrations, download
   and verify the bundle, prepare its Python runtime, back up and verify the database, switch the
   ``current`` release, restart the server and verify health (version, schema, authentication, model
   registry, inference). Any failure switches back to the previous release (restoring the database
   backup if the schema had changed) and is reported to the Owner Dashboard;
5. update itself last, from the same verified release.

Operator commands (exceptional recovery only)::

    moth status | check | rollback | backup | restart | logs | supervise | run
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

AGENT_VERSION = "0.7.1"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ed25519_verify  # noqa: E402  (stdlib-only verifier shipped next to this file)

DEFAULTS = {
    "channel": "stable", "check_interval_s": 900, "server_url": "http://127.0.0.1:8900", "supervisor": "cron",
    "python": sys.executable, "torch_index": "https://download.pytorch.org/whl/cpu", "keep_releases": 3,
    "keep_backups": 5, "health_timeout_s": 240, "min_free_bytes": 2 * 1024 ** 3, "source": "",
    # use packages already installed for the system Python (e.g. an administrator-installed PyTorch)
    "venv_system_site_packages": False,
}


class AgentError(Exception):
    pass


def _vt(v: str) -> tuple:
    core = v.split("-")[0].split("+")[0]
    return tuple(int(x) for x in core.split("."))


# ---- installation layout -----------------------------------------------------------------------
class Install:
    def __init__(self, home: Path):
        self.home = home.resolve()
        self.config_dir = self.home / "config"
        self.cfg = {**DEFAULTS, **json.loads((self.config_dir / "agent.json").read_text())}
        self.env = self._read_env(self.config_dir / "moth.env")
        for d in ("releases", "runtime", "backups", "logs", "run", "state", "downloads", "agent", "bin"):
            (self.home / d).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _read_env(path: Path) -> dict:
        env = {}
        if path.exists():
            for line in path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
        return env

    @property
    def data_dir(self) -> Path:
        p = Path(self.env.get("MOTH_SERVER_DATA_DIR", str(self.home / "data")))
        return p if p.is_absolute() else (self.home / p).resolve()

    @property
    def db_url(self) -> str:
        return self.env.get("MOTH_SERVER_DATABASE_URL") or f"sqlite:///{self.data_dir / 'moth-server.db'}"

    @property
    def agent_token(self) -> str:
        p = Path(self.env.get("MOTH_AGENT_TOKEN_FILE", str(self.config_dir / "agent.token")))
        return p.read_text().strip() if p.exists() else ""

    def link(self, name: str) -> Path | None:
        p = self.home / name
        return p.resolve() if p.is_symlink() and p.resolve().exists() else None

    def version_of(self, release_dir: Path | None) -> str | None:
        if release_dir and (release_dir / "VERSION").exists():
            return (release_dir / "VERSION").read_text().strip()
        return None

    @property
    def current_version(self) -> str | None:
        return self.version_of(self.link("current"))

    def set_link(self, name: str, target: Path | None) -> None:
        link = self.home / name
        if target is None:
            if link.is_symlink():
                link.unlink()
            return
        tmp = self.home / f".{name}.{uuid.uuid4().hex[:6]}"
        os.symlink(target, tmp)
        os.replace(tmp, link)  # atomic

    # state (survives agent restarts and reboots)
    @property
    def state_file(self) -> Path:
        return self.home / "state" / "agent-state.json"

    def state(self) -> dict:
        try:
            return json.loads(self.state_file.read_text())
        except (OSError, ValueError):
            return {"failed": {}, "needs_approval": {}}

    def save_state(self, st: dict) -> None:
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=2))
        os.replace(tmp, self.state_file)


# ---- logging & server API ------------------------------------------------------------------------
class Agent:
    def __init__(self, home: Path):
        self.i = Install(home)
        self.cfg = self.i.cfg
        self.deployment_id = None
        self.log_buffer: list[str] = []

    def log(self, msg: str) -> None:
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        print(line, flush=True)
        self.log_buffer.append(line)
        lf = self.i.home / "logs" / "agent.log"
        if lf.exists() and lf.stat().st_size > 5 * 1024 * 1024:
            os.replace(lf, lf.with_suffix(".log.1"))
        with open(lf, "a") as f:
            f.write(line + "\n")

    def api(self, method: str, path: str, body: dict | None = None, timeout: float = 20) -> dict | None:
        req = urllib.request.Request(self.cfg["server_url"].rstrip("/") + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-Moth-Agent-Token": self.i.agent_token,
                                              "User-Agent": f"moth-agent/{AGENT_VERSION}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return json.loads(data) if data else {}
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def health(self, timeout: float = 5) -> dict | None:
        try:
            with urllib.request.urlopen(self.cfg["server_url"].rstrip("/") + "/v1/health", timeout=timeout) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def report(self, **fields) -> None:
        """Deployment progress for the Owner Dashboard (best effort: the server may be the thing that's down)."""
        if fields.get("log") is None and self.log_buffer:
            fields["log"] = "\n".join(self.log_buffer) + "\n"
            self.log_buffer = []
        if self.deployment_id:
            fields["id"] = self.deployment_id
        res = self.api("POST", "/v1/agent/deployments", fields)
        if res and not self.deployment_id:
            self.deployment_id = res.get("id")

    def heartbeat(self, state: str, message: str = "", **extra) -> None:
        free = shutil.disk_usage(self.i.home).free
        backups = sorted(p.name for p in (self.i.home / "backups").glob("*") if p.is_dir())[-3:]
        self.api("POST", "/v1/agent/heartbeat", {
            "agent_version": AGENT_VERSION, "state": state, "message": message, "current": self.i.current_version,
            "previous": self.i.version_of(self.i.link("previous")), "last_check": time.time(),
            "next_check": time.time() + float(self.cfg["check_interval_s"]), "disk_free": free,
            "supervisor": self.cfg["supervisor"], "backups": backups, **extra})

    # ---- release source --------------------------------------------------------------------------------
    def _http_get(self, url: str, headers: dict | None = None, dest: Path | None = None, timeout: float = 60,
                  size: int | None = None):
        """GET ``url``; with ``dest``, download to that file.

        Downloads are checked for completeness: ``urllib`` returns a short body without an error when a
        connection drops part-way, so the received length is compared with the length the server
        announced (and the size in the signed manifest, when known). An interrupted download is resumed
        with an HTTP Range request from where it stopped. Integrity is still decided only by the SHA-256
        in the signed manifest (``fetch_verified``); this only makes sure a complete file reaches it.
        """
        h = {"User-Agent": f"moth-agent/{AGENT_VERSION}", **(headers or {})}
        tok_file = self.cfg.get("github_token_file")
        if urllib.parse.urlsplit(url).hostname == "api.github.com" and tok_file and Path(tok_file).exists():
            h["Authorization"] = "Bearer " + Path(tok_file).read_text().strip()
        name = url.split("?")[0]
        tmp = dest.with_suffix(dest.suffix + ".part") if dest is not None else None
        if tmp is not None:
            tmp.unlink(missing_ok=True)  # never resume a file left over from an earlier, unrelated run
        last = None
        delays = (0, 2, 5, 15) if dest is None else (0, 2, 5, 10, 20, 30, 60, 60, 60, 60)
        for delay in delays:
            time.sleep(delay)
            have = tmp.stat().st_size if tmp is not None and tmp.exists() else 0
            if size is not None and have > size:
                tmp.unlink(missing_ok=True)
                have = 0
            hdrs = dict(h)
            if have:
                hdrs["Range"] = f"bytes={have}-"
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=hdrs), timeout=timeout) as r:
                    if dest is None:
                        body = r.read()
                        n = r.headers.get("Content-Length")
                        if n is not None and n.isdigit() and len(body) != int(n):
                            raise OSError(f"connection closed after {len(body)} of {n} bytes")
                        return body
                    resumed = have and r.status == 206
                    if have and not resumed:
                        have = 0  # the server ignored the Range request: start again from the beginning
                    n = r.headers.get("Content-Length")
                    expected = have + int(n) if n is not None and n.isdigit() else size
                    with open(tmp, "ab" if resumed else "wb") as f:
                        shutil.copyfileobj(r, f, 1 << 20)
                got = tmp.stat().st_size
                if expected is not None and got < expected:
                    raise OSError(f"connection closed after {got} of {expected} bytes")
                if size is not None and got != size:
                    raise OSError(f"received {got} bytes, the signed manifest says {size}")
                os.replace(tmp, dest)
                if have:
                    self.log(f"download of {dest.name} resumed at byte {have} and completed ({got} bytes)")
                return dest
            except (urllib.error.URLError, OSError) as e:
                last = e
                if isinstance(e, urllib.error.HTTPError) and e.code in (401, 403, 404):
                    break
                if isinstance(e, urllib.error.HTTPError) and e.code == 416 and tmp is not None:
                    tmp.unlink(missing_ok=True)  # resume point not satisfiable: start again
                if dest is not None:
                    self.log(f"download of {dest.name} interrupted ({e}); retrying")
        if tmp is not None:
            tmp.unlink(missing_ok=True)
        raise AgentError(f"download failed: {name}: {last}")

    def list_releases(self) -> list[dict]:
        """Verified releases, newest first: {version, manifest, raw, sig, fetch(name)->Path}."""
        src = self.cfg.get("source") or ""
        found = []
        if src.startswith("dir:"):
            root = Path(src[4:])
            for mf in root.rglob("moth-release-*.json"):
                sig = mf.with_name(mf.name + ".sig")
                if sig.exists():
                    found.append((mf.read_bytes(), sig.read_text(), lambda name, size=None, d=mf.parent: self._dir_fetch(d, name)))
        elif src.startswith("github:"):
            repo = src[7:]
            cache = self._gh_cache()
            data = self._gh_releases(f"https://api.github.com/repos/{repo}/releases?per_page=20", cache)
            token_file = self.cfg.get("github_token_file")
            authenticated = bool(token_file and Path(token_file).is_file() and Path(token_file).read_text().strip())
            unavailable = []
            for rel in data:
                if rel.get("draft"):
                    continue
                # Public files belong on GitHub's download endpoint, not the rate-limited REST
                # asset endpoint. Keep authenticated REST downloads for private repositories.
                assets = {a["name"]: a["url"] if authenticated else a.get("browser_download_url") or a["url"]
                          for a in rel.get("assets", [])}
                mf = next((n for n in assets if n.startswith("moth-release-") and n.endswith(".json")), None)
                if not mf or mf + ".sig" not in assets:
                    continue
                try:
                    known = cache["manifests"].get(assets[mf])
                    if known and known[2] == assets[mf + ".sig"]:  # unchanged asset: no download needed
                        raw, sig = base64.b64decode(known[0]), known[1]
                    else:
                        raw = self._http_get(assets[mf], {"Accept": "application/octet-stream"})
                        sig = self._http_get(assets[mf + ".sig"], {"Accept": "application/octet-stream"}).decode()
                        cache["manifests"][assets[mf]] = [base64.b64encode(raw).decode(), sig, assets[mf + ".sig"]]
                except AgentError as e:
                    unavailable.append(str(e))
                    self.log(f"could not read GitHub release {rel.get('tag_name') or mf}: {e}")
                    continue  # an unavailable historical release must not block verified newer ones
                found.append((raw, sig, lambda name, size=None, a=assets: self._gh_fetch(a, name, size)))
            live = {a["url"] if authenticated else a.get("browser_download_url") or a["url"]
                    for rel in data for a in rel.get("assets", [])}
            cache["manifests"] = {k: v for k, v in cache["manifests"].items() if k in live}
            self._gh_save(cache)
            if not found and unavailable:
                raise AgentError("no GitHub release manifests could be read: " + unavailable[0])
        elif src:
            raise AgentError(f"unknown release source {src!r}")
        out = []
        for raw, sig, fetch in found:
            if not ed25519_verify.verify_b64(self.cfg["pubkey"], raw, sig):
                self.log("ignoring a release whose signature does not verify")
                continue
            m = json.loads(raw)
            out.append({"version": m["version"], "manifest": m, "raw": raw, "sig": sig.strip(), "fetch": fetch})
        out.sort(key=lambda r: _vt(r["version"]), reverse=True)
        return out

    # ---- GitHub: conditional requests and rate limits (0.7.1) -------------------------------------
    # The release list is requested with the ETag of the previous answer: an unchanged list returns
    # 304 Not Modified, which GitHub does not count against the rate limit, and the signed manifests
    # read before are reused from the cache (each is still verified against its signature below).
    # A rate-limit answer (403/429 with Retry-After or X-RateLimit-Remaining: 0) is not retried: the
    # agent waits until GitHub's reset time and serves the cached list meanwhile.
    def _gh_cache_file(self) -> Path:
        return self.i.home / "state" / "github-cache.json"

    def _gh_cache(self) -> dict:
        try:
            c = json.loads(self._gh_cache_file().read_text())
        except (OSError, ValueError):
            c = {}
        return {"etag": c.get("etag"), "data": c.get("data"), "manifests": c.get("manifests") or {},
                "wait_until": float(c.get("wait_until") or 0)}

    def _gh_save(self, cache: dict) -> None:
        f = self._gh_cache_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        os.replace(tmp, f)

    def _gh_releases(self, url: str, cache: dict) -> list:
        if time.time() < cache["wait_until"]:
            if cache["data"] is not None:
                return cache["data"]
            raise AgentError(f"GitHub rate limit: waiting until {time.ctime(cache['wait_until'])}")
        h = {"User-Agent": f"moth-agent/{AGENT_VERSION}", "Accept": "application/vnd.github+json"}
        tok_file = self.cfg.get("github_token_file")
        if tok_file and Path(tok_file).exists() and Path(tok_file).read_text().strip():
            h["Authorization"] = "Bearer " + Path(tok_file).read_text().strip()
        if cache["etag"] and cache["data"] is not None:
            h["If-None-Match"] = cache["etag"]
        last = None
        for delay in (0, 2, 5):
            time.sleep(delay)
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
                    data = json.loads(r.read())
                    cache.update(etag=r.headers.get("ETag"), data=data, wait_until=0)
                    return data
            except urllib.error.HTTPError as e:
                if e.code == 304 and cache["data"] is not None:
                    return cache["data"]
                if e.code in (403, 429):
                    retry = e.headers.get("Retry-After")
                    reset = e.headers.get("X-RateLimit-Reset")
                    limited = e.code == 429 or retry or e.headers.get("X-RateLimit-Remaining") == "0"
                    if limited:
                        until = time.time() + float(retry) if retry and retry.isdigit() else \
                            float(reset) if reset and reset.isdigit() else time.time() + 3600
                        cache["wait_until"] = min(until, time.time() + 6 * 3600)
                        self._gh_save(cache)
                        self.log(f"GitHub rate limit reached; next release check after {time.ctime(cache['wait_until'])}")
                        if cache["data"] is not None:
                            return cache["data"]
                    raise AgentError(f"GitHub refused the release list: HTTP {e.code}") from None
                if e.code in (401, 404):
                    raise AgentError(f"GitHub release list: HTTP {e.code}") from None
                last = e
            except (urllib.error.URLError, OSError, ValueError) as e:
                last = e
        if cache["data"] is not None:
            self.log(f"GitHub unreachable ({last}); using the last known release list")
            return cache["data"]
        raise AgentError(f"GitHub release list unavailable: {last}")

    def _dir_fetch(self, d: Path, name: str) -> Path:
        hits = list(d.rglob(name)) or list(d.parent.rglob(name))
        if not hits:
            raise AgentError(f"{name} is missing from the release directory")
        dest = self.i.home / "downloads" / name
        shutil.copyfile(hits[0], dest)
        return dest

    def _gh_fetch(self, assets: dict, name: str, size: int | None = None) -> Path:
        if name not in assets:
            raise AgentError(f"{name} is missing from the GitHub release")
        return self._http_get(assets[name], {"Accept": "application/octet-stream"},
                              dest=self.i.home / "downloads" / name, timeout=600, size=size)

    @staticmethod
    def sha256(path: Path) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    def fetch_verified(self, rel: dict, entry: dict) -> Path:
        """Download a release file and accept it only if its SHA-256 matches the signed manifest."""
        size = entry.get("size") if isinstance(entry.get("size"), int) else None
        p = rel["fetch"](entry["file"], size=size)
        got_size, got_hash = p.stat().st_size, self.sha256(p)
        if got_hash != entry["sha256"]:
            p.unlink(missing_ok=True)
            raise AgentError(f"{entry['file']} does not match the SHA-256 in the signed manifest "
                             f"(received {got_size} bytes, SHA-256 {got_hash[:16]}…; "
                             f"expected {size if size is not None else '?'} bytes, {entry['sha256'][:16]}…)")
        return p

    # ---- distribution of desktop/worker files through the server --------------------------------------
    @staticmethod
    def kind_of(rel: dict) -> str:
        m = rel["manifest"]
        if m.get("kind") in ("desktop", "server", "model"):
            return m["kind"]
        return "desktop" if set((m.get("components") or {}).keys()) == {"desktop"} else "server"

    def publish_to_server(self, rels: list[dict]) -> None:
        """Hand the newest releases of each kind (server, desktop) to the server, which distributes the
        desktop and worker files to clients. Desktop releases are never installed on this machine."""
        newest: list[dict] = []
        for kind in ("server", "desktop"):
            newest += [r for r in rels if self.kind_of(r) == kind][:2]
        self.publish_models([r for r in rels if self.kind_of(r) == "model"][:3])
        for rel in newest:
            res = self.api("POST", "/v1/agent/releases", {"manifest": base64.b64encode(rel["raw"]).decode(),
                                                          "signature": rel["sig"]})
            if res is None:
                self.log(f"could not register release {rel['version']} with the server (is it running?)")
                continue
            comps = rel["manifest"].get("components", {})
            entries = [("worker", comps["worker"])] if comps.get("worker") else []
            entries += [("desktop", e) for e in (comps.get("desktop") or {}).values()]
            for comp, entry in entries:
                served = self.i.data_dir / "storage" / "software" / comp / rel["version"] / entry["file"]
                if served.exists():
                    continue
                try:
                    p = self.fetch_verified(rel, entry)
                    incoming = self.i.data_dir / "storage" / "software" / "incoming" / entry["file"]
                    incoming.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(p), incoming)
                    if self.api("POST", "/v1/agent/files", {"component": comp, "version": rel["version"],
                                                           "path": str(incoming)}, timeout=300) is None:
                        self.log(f"server did not accept {entry['file']}")
                    else:
                        self.log(f"{comp} {rel['version']} is now available to clients")
                except AgentError as e:
                    self.log(f"could not fetch {comp} {rel['version']}: {e}")

    def publish_models(self, rels: list[dict]) -> None:
        """Official MOTH model releases (0.5.2): download once, verify, and hand to the server, which
        re-verifies the signature and checksum, evaluates the model and deploys it if it passes."""
        st = self.i.state()
        done = st.setdefault("models_imported", {})
        for rel in rels:
            if rel["manifest"].get("channel", "stable") != "stable" or done.get(rel["version"]):
                continue
            entry = (rel["manifest"].get("components") or {}).get("model")
            if not entry:
                continue
            try:
                p = self.fetch_verified(rel, entry)
                incoming = self.i.data_dir / "storage" / "software" / "incoming" / entry["file"]
                incoming.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), incoming)
                res = self.api("POST", "/v1/agent/models", {"manifest": base64.b64encode(rel["raw"]).decode(),
                                                            "signature": rel["sig"], "path": str(incoming)},
                               timeout=1800)
                if res is None:
                    self.log(f"the server did not import model {rel['version']} (is it 0.5.2 or newer?)")
                    continue
                done[rel["version"]] = time.time()
                self.i.save_state(st)
                self.log(f"model {rel['version']} imported as release v{res.get('version')} ({res.get('status')})")
            except AgentError as e:
                self.log(f"could not fetch model {rel['version']}: {e}")

    # ---- runtime, backups, process control ------------------------------------------------------------------
    def runtime_for(self, release_dir: Path) -> Path:
        req = (release_dir / "requirements.txt").read_bytes()
        key = hashlib.sha256(req + self.cfg["python"].encode() + self.cfg["torch_index"].encode()
                             + str(self.cfg.get("venv_system_site_packages")).encode()).hexdigest()[:16]
        rt = self.i.home / "runtime" / key
        if (rt / ".ready").exists():
            return rt
        self.log(f"preparing Python runtime {key} (first time for these dependencies)")
        shutil.rmtree(rt, ignore_errors=True)
        run([self.cfg["python"], "-m", "venv", str(rt)]
            + (["--system-site-packages"] if self.cfg.get("venv_system_site_packages") else []))
        pip = [str(rt / "bin" / "python"), "-m", "pip", "install", "--disable-pip-version-check", "-q"]
        run(pip + ["--upgrade", "pip"])
        if any(line.strip().startswith("torch") for line in req.decode().splitlines()) and not \
                self.cfg.get("venv_system_site_packages"):
            run(pip + ["torch", "--index-url", self.cfg["torch_index"]], timeout=3600)
        run(pip + ["-r", str(release_dir / "requirements.txt")], timeout=3600)
        (rt / ".ready").write_text(time.ctime())
        return rt

    def release_env(self, release_dir: Path) -> dict:
        env = {**os.environ, **self.i.env}
        env["PYTHONPATH"] = os.pathsep.join(str(release_dir / d) for d in ("server", "backend", "worker"))
        env.setdefault("MOTH_AGENT_TOKEN_FILE", str(self.i.config_dir / "agent.token"))
        return env

    def server_python(self, release_dir: Path) -> str:
        rt_file = release_dir / "RUNTIME"
        return str(Path(rt_file.read_text().strip()) / "bin" / "python")

    def migration_plan(self, release_dir: Path) -> dict:
        out = run([self.server_python(release_dir), "-m", "moth_server.cli", "migrate", "--plan"],
                  env=self.release_env(release_dir), capture=True)
        return json.loads(out.strip().splitlines()[-1])

    def backup(self, tag: str) -> Path:
        """Consistent database backup + configuration, verified before it is trusted."""
        dest = self.i.home / "backups" / f"{time.strftime('%Y%m%d-%H%M%S')}-{tag}"
        dest.mkdir(parents=True)
        url = self.i.db_url
        if url.startswith("sqlite"):
            src = Path(url.split("///", 1)[1])
            if src.exists():
                with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dest / "moth-server.db") as d:
                    s.backup(d)
                with sqlite3.connect(dest / "moth-server.db") as d:
                    if d.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise AgentError("database backup failed its integrity check")
        else:
            pg = url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+psycopg2://", "postgresql://")
            if not shutil.which("pg_dump"):
                raise AgentError("pg_dump is not installed; PostgreSQL backups need the PostgreSQL client tools "
                                 "(an administrator can install the 'postgresql-client' package)")
            run(["pg_dump", "--format=custom", "--file", str(dest / "moth-server.pgdump"), pg], timeout=3600)
            run(["pg_restore", "--list", str(dest / "moth-server.pgdump")], capture=True)  # verifies the archive
        shutil.copytree(self.i.config_dir, dest / "config", ignore=shutil.ignore_patterns("github.token"))
        sums = {p.relative_to(dest).as_posix(): self.sha256(p) for p in dest.rglob("*") if p.is_file()}
        (dest / "SHA256SUMS.json").write_text(json.dumps(sums, indent=1))
        backups = sorted(p for p in (self.i.home / "backups").iterdir() if p.is_dir())
        for old in backups[:-int(self.cfg["keep_backups"])]:
            shutil.rmtree(old, ignore_errors=True)
        self.log(f"backup verified: {dest.name}")
        return dest

    def restore_db(self, backup: Path) -> None:
        url = self.i.db_url
        if url.startswith("sqlite"):
            target = Path(url.split("///", 1)[1])
            for suffix in ("-wal", "-shm"):
                Path(str(target) + suffix).unlink(missing_ok=True)
            shutil.copyfile(backup / "moth-server.db", target)
        else:
            pg = url.replace("postgresql+psycopg://", "postgresql://")
            run(["pg_restore", "--clean", "--if-exists", "--no-owner", "-d", pg, str(backup / "moth-server.pgdump")],
                timeout=3600)
        self.log(f"database restored from {backup.name}")

    def pid(self, name: str) -> int | None:
        """The live process for ``name``. A killed process whose parent hasn't reaped it yet (a zombie)
        still answers ``kill -0``, so the process state is checked as well."""
        try:
            p = int((self.i.home / "run" / f"{name}.pid").read_text().strip())
            os.kill(p, 0)
        except (OSError, ValueError):
            return None
        try:
            state = Path(f"/proc/{p}/stat").read_text().rsplit(")", 1)[1].split()[0]
            if state in ("Z", "X"):
                return None
        except (OSError, IndexError):
            pass
        return p

    @property
    def maintenance_flag(self) -> Path:
        return self.i.home / "run" / "maintenance"

    def stop_server(self) -> None:
        """Stop the server and hold it stopped: the launch script waits while the maintenance flag
        exists, so a supervisor that restarts it immediately (systemd) cannot race a restore."""
        self.maintenance_flag.write_text(str(time.time()))
        if self.cfg["supervisor"] == "systemd-user":
            run(["systemctl", "--user", "stop", "moth-server"], check=False)
            return
        p = self.pid("server")
        if not p:
            return
        os.kill(p, signal.SIGTERM)
        for _ in range(60):
            time.sleep(0.5)
            if not self.pid("server"):
                return
        os.kill(p, signal.SIGKILL)

    def start_server(self) -> None:
        self.maintenance_flag.unlink(missing_ok=True)
        if self.cfg["supervisor"] == "systemd-user":
            run(["systemctl", "--user", "start", "moth-server"], check=False)
            return
        if self.cfg["supervisor"] == "systemd-system":
            return  # systemd (Restart=always) is already waiting on the flag; removing it lets it start
        if self.pid("server"):
            return
        logf = open(self.i.home / "logs" / "server.log", "a")
        subprocess.Popen([str(self.i.home / "bin" / "moth-server-run")], stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(self.i.home))

    def restart_server(self) -> None:
        self.stop_server()
        self.start_server()

    def wait_healthy(self, version: str, expect: dict) -> dict:
        """Verify the restarted server: version, schema, authentication, model registry, inference."""
        deadline = time.time() + float(self.cfg["health_timeout_s"])
        h = None
        while time.time() < deadline:
            h = self.health()
            if h and h.get("version") == version and h.get("status") == "ok":
                break
            time.sleep(2)
        else:
            raise AgentError(f"MOTH Cloud did not come back healthy on {version} within "
                             f"{self.cfg['health_timeout_s']}s (last health: {h})")
        if expect.get("schema_version") and h.get("schema_version") != expect["schema_version"]:
            raise AgentError(f"database schema is {h.get('schema_version')}, expected {expect['schema_version']}")
        base = self.cfg["server_url"].rstrip("/")
        req = urllib.request.Request(base + "/v1/auth/login", method="POST",
                                     data=json.dumps({"username": "health-check-" + uuid.uuid4().hex[:8],
                                                      "password": uuid.uuid4().hex}).encode(),
                                     headers={"Content-Type": "application/json", "X-Moth-Client": "desktop/9.9.9"})
        try:
            urllib.request.urlopen(req, timeout=15)
            raise AgentError("authentication check failed: a bogus login was accepted")
        except urllib.error.HTTPError as e:
            if e.code not in (401, 429):
                raise AgentError(f"authentication check failed: HTTP {e.code}") from None
        try:
            urllib.request.urlopen(base + "/v1/models/current", timeout=15).read()
        except (urllib.error.URLError, OSError) as e:
            raise AgentError(f"model registry check failed: {e}") from None
        if expect.get("model_version"):
            deadline2 = time.time() + 120
            while time.time() < deadline2:
                h = self.health()
                if h and h.get("model_version") == expect["model_version"]:
                    break
                time.sleep(2)
            else:
                raise AgentError(f"inference check failed: model v{expect['model_version']} is not serving after the "
                                 "update")
        return h

    # ---- update / rollback --------------------------------------------------------------------------------
    def install_release(self, rel: dict) -> Path:
        entry = rel["manifest"]["components"]["server"]
        need = int(entry.get("size") or 0) * 4 + int(self.cfg["min_free_bytes"])
        free = shutil.disk_usage(self.i.home).free
        if free < need:
            raise AgentError(f"not enough disk space: {need / 2**30:.1f} GB needed, {free / 2**30:.1f} GB free")
        dest = self.i.home / "releases" / rel["version"]
        if (dest / ".installed").exists():
            return dest
        bundle = self.fetch_verified(rel, entry)
        staging = Path(tempfile.mkdtemp(prefix=f".{rel['version']}-", dir=self.i.home / "releases"))
        try:
            with tarfile.open(bundle) as tar:
                for m in tar.getmembers():
                    if m.issym() or m.islnk() or m.name.startswith("/") or ".." in Path(m.name).parts:
                        raise AgentError("server bundle contains unsafe paths")
                tar.extractall(staging)
            roots = [p for p in staging.iterdir() if p.is_dir()]
            if len(roots) != 1 or not (roots[0] / "VERSION").exists():
                raise AgentError("server bundle layout is not recognised")
            if roots[0].joinpath("VERSION").read_text().strip() != rel["version"]:
                raise AgentError("server bundle version does not match its manifest")
            shutil.rmtree(dest, ignore_errors=True)
            os.replace(roots[0], dest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
            bundle.unlink(missing_ok=True)
        rt = self.runtime_for(dest)
        (dest / "RUNTIME").write_text(str(rt))
        run([self.server_python(dest), "-c", "import moth_server, moth; print(moth_server.__version__)"],
            env=self.release_env(dest), capture=True)
        (dest / ".installed").write_text(time.ctime())
        return dest

    def update_to(self, rel: dict, control: dict) -> bool:
        st = self.i.state()
        cur_dir, cur_v = self.i.link("current"), self.i.current_version
        v = rel["version"]
        self.deployment_id = None
        self.log_buffer = []
        self.log(f"updating MOTH Cloud {cur_v} → {v}")
        self.report(component="server", from_version=cur_v, to_version=v, status="started", step="preflight")
        before = self.health() or {}
        try:
            dest = self.install_release(rel)
            self.report(step="migration check")
            plan = self.migration_plan(dest)
            blocked = [m for m in plan.get("pending", []) if m["destructive"]
                       and m["version"] not in set(control.get("approved_migrations", []))]
            if blocked:
                msg = "this update contains a destructive database migration that needs your approval: " + \
                      ", ".join(f"#{m['version']} {m['description']}" for m in blocked)
                self.log(msg)
                st.setdefault("needs_approval", {})[v] = msg
                self.i.save_state(st)
                self.report(status="needs_approval", step="waiting for approval", error=msg)
                return False
            self.report(step="backup")
            backup = self.backup(f"pre-{v}")
            st["in_progress"] = {"to": v, "from": cur_v, "from_dir": str(cur_dir) if cur_dir else None,
                                 "backup": str(backup), "schema_before": before.get("schema_version"),
                                 "model_version": before.get("model_version"), "started": time.time(),
                                 "deployment_id": self.deployment_id}
            self.i.save_state(st)
            self.report(step="switching and restarting")
            if cur_dir:
                self.i.set_link("previous", cur_dir)
            self.i.set_link("current", dest)
            if os.environ.get("MOTH_AGENT_TEST_CRASH") == "after-switch":  # integration tests: simulate a crash
                os._exit(9)
            self.restart_server()
            self.report(step="health checks")
            h = self.wait_healthy(v, {"schema_version": rel["manifest"].get("schema_version"),
                                      "model_version": before.get("model_version")})
            self.finish_success(v, h)
            return True
        except Exception as e:  # noqa: BLE001 — every failure is reported and undone
            err = str(e) if isinstance(e, AgentError) else f"{type(e).__name__}: {e}"
            self.log(f"update to {v} failed: {err}")
            if (self.i.state().get("in_progress") or {}).get("to") == v:
                self.rollback_in_progress(err)
            else:
                st = self.i.state()
                st.setdefault("failed", {})[v] = err
                self.i.save_state(st)
                self.report(status="failed", step="before switching", error=err)
            return False

    def finish_success(self, v: str, h: dict | None) -> None:
        st = self.i.state()
        st.pop("in_progress", None)
        st.get("failed", {}).pop(v, None)
        st.get("needs_approval", {}).pop(v, None)
        st["last_success"] = {"version": v, "ts": time.time()}
        self.i.save_state(st)
        self.log(f"MOTH Cloud {v} is healthy (schema {h and h.get('schema_version')})")
        self.report(status="succeeded", step="done")
        self.prune()

    def rollback_in_progress(self, reason: str) -> None:
        st = self.i.state()
        ip = st.get("in_progress") or {}
        if ip.get("deployment_id"):
            self.deployment_id = ip["deployment_id"]
        to_dir = Path(ip["from_dir"]) if ip.get("from_dir") else None
        self.log(f"rolling back to {ip.get('from')}: {reason}")
        try:
            self.stop_server()
            if ip.get("backup") and ip.get("schema_before") is not None and to_dir:
                schema_now = self.schema_version(to_dir)
                if schema_now is None or schema_now != ip["schema_before"]:
                    self.restore_db(Path(ip["backup"]))  # the failed version changed the schema
            if to_dir and to_dir.exists():
                self.i.set_link("current", to_dir)
            self.start_server()
            if ip.get("from"):
                self.wait_healthy(ip["from"], {"model_version": ip.get("model_version")})
            st = self.i.state()
            st.pop("in_progress", None)
            st.setdefault("failed", {})[ip.get("to")] = reason
            self.i.save_state(st)
            self.report(status="rolled_back", step="restored previous version", error=reason)
        except Exception as e:  # noqa: BLE001
            msg = f"ROLLBACK FAILED: {e}. MOTH Cloud needs administrator attention: run `moth status` on the server."
            self.log(msg)
            st = self.i.state()
            st["needs_attention"] = msg
            self.i.save_state(st)
            self.report(status="failed", step="rollback failed", error=f"{reason}; {msg}")

    def schema_version(self, release_dir: Path) -> int | None:
        """The database's schema version, read with a release's own code (works for SQLite and PostgreSQL)."""
        try:
            return int(self.migration_plan(release_dir).get("current"))
        except (AgentError, ValueError, TypeError, OSError):
            return None

    def recover(self) -> None:
        """An update was in progress when the agent stopped (crash, restart, reboot): finish or undo it."""
        st = self.i.state()
        ip = st.get("in_progress")
        if not ip:
            return
        self.log(f"recovering an interrupted update to {ip['to']}")
        self.deployment_id = ip.get("deployment_id")
        if self.i.current_version != ip["to"]:
            st.pop("in_progress", None)  # never switched: nothing to undo
            self.i.save_state(st)
            self.report(status="failed", step="interrupted before switching", error="update was interrupted")
            return
        h = self.health()
        if not h or h.get("version") != ip["to"]:
            self.restart_server()  # the old code may still be running (crash between switch and restart)
        try:
            h = self.wait_healthy(ip["to"], {"model_version": ip.get("model_version")})
            self.finish_success(ip["to"], h)
        except AgentError as e:
            self.rollback_in_progress(f"after interruption: {e}")

    def manual_rollback(self) -> None:
        prev = self.i.link("previous")
        if not prev:
            raise AgentError("there is no previous MOTH Cloud version to roll back to")
        cur_v, prev_v = self.i.current_version, self.i.version_of(prev)
        self.deployment_id = None
        self.report(component="server", from_version=cur_v, to_version=prev_v, status="started",
                    step="Owner-requested rollback")
        backup = self.backup(f"pre-rollback-{prev_v}")
        st = self.i.state()
        before = self.health() or {}
        st["in_progress"] = {"to": prev_v, "from": cur_v, "from_dir": str(self.i.link("current")),
                             "backup": str(backup), "schema_before": before.get("schema_version"),
                             "model_version": before.get("model_version"), "started": time.time(),
                             "deployment_id": self.deployment_id}
        self.i.save_state(st)
        self.i.set_link("previous", self.i.link("current"))
        self.i.set_link("current", prev)
        try:
            self.restart_server()
            h = self.wait_healthy(prev_v, {"model_version": before.get("model_version")})
            st = self.i.state()
            st.pop("in_progress", None)
            st.setdefault("failed", {})[cur_v] = "rolled back by the Owner"
            self.i.save_state(st)
            self.log(f"rolled back to {prev_v}")
            self.report(status="succeeded", step="rolled back", log=None)
            _ = h
        except AgentError as e:
            self.rollback_in_progress(f"rollback to {prev_v} failed: {e}")

    def prune(self) -> None:
        keep = {self.i.link("current"), self.i.link("previous")}
        rels = sorted((p for p in (self.i.home / "releases").iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for p in rels[int(self.cfg["keep_releases"]):]:
            if p.resolve() not in keep:
                shutil.rmtree(p, ignore_errors=True)
        used = set()
        for p in (self.i.home / "releases").iterdir():
            if (p / "RUNTIME").exists():
                used.add(Path((p / "RUNTIME").read_text().strip()).name)
        for rt in (self.i.home / "runtime").iterdir():
            if rt.name not in used:
                shutil.rmtree(rt, ignore_errors=True)

    def self_update(self, rel_dir: Path) -> bool:
        new = rel_dir / "agent" / "moth_agent.py"
        if not new.exists() or new.read_bytes() == Path(__file__).read_bytes():
            return False
        target = self.i.home / "agent" / rel_dir.name
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(rel_dir / "agent", target)
        current = self.i.home / "agent" / "current"
        if current.is_symlink():
            tmp = self.i.home / "agent" / ".previous"
            os.symlink(current.resolve(), tmp)
            os.replace(tmp, self.i.home / "agent" / "previous")
        tmp = self.i.home / "agent" / ".current"
        os.symlink(target, tmp)
        os.replace(tmp, current)
        self.log(f"agent updated from the {rel_dir.name} release; restarting the agent")
        return True

    @contextlib.contextmanager
    def exclusive(self):
        """One update operation at a time (the background agent and an operator's `moth check`)."""
        with open(self.i.home / "run" / "agent.lock", "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    # ---- one cycle ------------------------------------------------------------------------------------------
    def check_once(self) -> str:
        with self.exclusive():
            return self._check_once()

    def _check_once(self) -> str:
        self.recover()
        control = self.api("GET", "/v1/agent/control") or {}
        acks: dict = {}
        if control.get("rollback_requested_at"):
            acks["ack_rollback"] = True
            try:
                self.manual_rollback()
            except AgentError as e:
                self.log(f"rollback not possible: {e}")
        if control.get("check_now_at"):
            acks["ack_check_now"] = True
        st = self.i.state()
        for v in control.get("retry", []):
            st.get("failed", {}).pop(v, None)
            st.get("needs_approval", {}).pop(v, None)
        if control.get("retry"):
            acks["ack_retry"] = control["retry"]
            self.i.save_state(st)
        try:
            rels = self.list_releases()
        except AgentError as e:
            self.log(f"could not check for releases: {e}")
            self.heartbeat("error", str(e), last_error=str(e), **acks)
            return "error"
        result = self._update_server(rels, control, acks)
        # Relaying desktop/worker files (large downloads) comes after the server's own update, so a slow
        # or failing download can never delay a server update or rollback.
        self.publish_to_server(rels)
        return result

    def _update_server(self, rels: list[dict], control: dict, acks: dict) -> str:
        channel = control.get("channel") or self.cfg["channel"]
        cur = self.i.current_version or "0.0.0"
        st = self.i.state()
        candidates = [r for r in rels if r["manifest"].get("components", {}).get("server")
                      and (r["manifest"].get("channel", "stable") == "stable" or channel != "stable")
                      and _vt(r["version"]) > _vt(cur) and r["version"] not in st.get("failed", {})]
        server_rels = {r["version"]: r for r in control.get("server_releases", [])}
        candidates = [r for r in candidates if server_rels.get(r["version"], {}).get("status") not in ("paused", "withdrawn")]
        if not candidates:
            self.heartbeat("idle", f"MOTH Cloud {cur} is up to date", **acks)
            return "up-to-date"
        target = candidates[0]
        if control.get("paused"):
            self.heartbeat("paused", f"update to {target['version']} is available; updates are paused", **acks)
            return "paused"
        min_from = target["manifest"].get("min_upgrade_from")
        if min_from and cur != "0.0.0" and _vt(cur) < _vt(min_from):
            msg = f"{target['version']} cannot be installed directly over {cur} (needs {min_from} first)"
            self.heartbeat("blocked", msg, **acks)
            return "blocked"
        self.heartbeat("updating", f"updating to {target['version']}", **acks)
        ok = self.update_to(target, control)
        self.heartbeat("idle" if ok else "error", f"MOTH Cloud {self.i.current_version}",
                       last_error=None if ok else self.i.state().get("failed", {}).get(target["version"]))
        if ok and self.self_update(self.i.link("current")):
            return "agent-updated"
        return "updated" if ok else "failed"

    def run_forever(self) -> None:
        (self.i.home / "run" / "agent.pid").write_text(str(os.getpid()))
        self.log(f"MOTH Cloud agent {AGENT_VERSION} started (supervisor: {self.cfg['supervisor']})")
        while True:
            try:
                if self.check_once() == "agent-updated":
                    sys.exit(0)  # the supervisor starts the new agent
            except Exception:  # noqa: BLE001 — the agent itself must keep running
                self.log("unexpected agent error:\n" + traceback.format_exc())
            deadline = time.time() + float(self.cfg["check_interval_s"])
            while time.time() < deadline:
                time.sleep(15)
                control = self.api("GET", "/v1/agent/control") or {}
                if control.get("check_now_at") or control.get("rollback_requested_at"):
                    break

    def supervise(self) -> None:
        """For installations without systemd (run from cron every minute and @reboot)."""
        slog = self.i.home / "logs" / "server.log"
        if slog.exists() and slog.stat().st_size > 50 * 1024 * 1024:
            os.replace(slog, slog.with_suffix(".log.1"))
        if not self.pid("server") and not self.maintenance_flag.exists():
            self.start_server()
        if not self.pid("agent"):
            logf = open(self.i.home / "logs" / "agent.log", "a")
            subprocess.Popen([str(self.i.home / "bin" / "moth-agent-run")], stdout=logf, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(self.i.home))

    def install_local(self, bundle: Path) -> str:
        """First installation (or adoption of an existing server) from an extracted release bundle."""
        bundle = bundle.resolve()
        v = (bundle / "VERSION").read_text().strip()
        dest = self.i.home / "releases" / v
        if dest.resolve() != bundle:
            shutil.rmtree(dest, ignore_errors=True)
            shutil.copytree(bundle, dest, ignore=shutil.ignore_patterns("__pycache__"))
        rt = self.runtime_for(dest)
        (dest / "RUNTIME").write_text(str(rt))
        run([self.server_python(dest), "-c", "import moth_server, moth"], env=self.release_env(dest), capture=True)
        url = self.i.db_url
        has_db = not url.startswith("sqlite") or Path(url.split("///", 1)[1]).exists()
        if has_db:
            self.backup(f"pre-install-{v}")
        plan = self.migration_plan(dest)
        blocked = [m for m in plan.get("pending", []) if m["destructive"]]
        if blocked:
            raise AgentError("the existing database needs a destructive migration; approve it with "
                             f"`moth server migrate --approve {blocked[0]['version']}` and run the installer again")
        out = run([self.server_python(dest), "-m", "moth_server.cli", "migrate"], env=self.release_env(dest),
                  capture=True)
        self.log(out.strip())
        cur = self.i.link("current")
        if cur and cur != dest.resolve():
            self.i.set_link("previous", cur)
        self.i.set_link("current", dest)
        (dest / ".installed").write_text(time.ctime())
        agent_dir = self.i.home / "agent" / v
        shutil.rmtree(agent_dir, ignore_errors=True)
        shutil.copytree(dest / "agent", agent_dir)
        tmp = self.i.home / "agent" / ".current"
        os.symlink(agent_dir, tmp)
        os.replace(tmp, self.i.home / "agent" / "current")
        return v

    def status(self) -> dict:
        st = self.i.state()
        return {"agent_version": AGENT_VERSION, "home": str(self.i.home), "current": self.i.current_version,
                "previous": self.i.version_of(self.i.link("previous")), "server_running": bool(self.pid("server")),
                "agent_running": bool(self.pid("agent")), "health": self.health(), "state": st,
                "supervisor": self.cfg["supervisor"], "source": self.cfg.get("source")}


def run(cmd: list[str], env: dict | None = None, capture: bool = False, timeout: float = 900, check: bool = True) -> str:
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise AgentError(f"{' '.join(cmd[:4])}… failed (exit {p.returncode}): {(p.stderr or p.stdout).strip()[-800:]}")
    return p.stdout if capture else ""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    home = Path(os.environ.get("MOTH_HOME") or HERE.parent.parent)
    cmd = argv[0] if argv else "status"
    agent = Agent(home)
    if cmd == "run":
        agent.run_forever()
    elif cmd == "check":
        print(agent.check_once())
    elif cmd == "status":
        print(json.dumps(agent.status(), indent=2, default=str))
    elif cmd == "rollback":
        with agent.exclusive():
            agent.manual_rollback()
    elif cmd == "backup":
        print(agent.backup("manual"))
    elif cmd == "restart":
        agent.restart_server()
    elif cmd == "supervise":
        agent.supervise()
    elif cmd == "install-local":
        with agent.exclusive():
            print(agent.install_local(Path(argv[1])))
    elif cmd == "logs":
        print((home / "logs" / "agent.log").read_text()[-20000:])
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AgentError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
