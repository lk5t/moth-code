#!/usr/bin/env python3
"""End-to-end test of MOTH Cloud installation and automatic updates, with real processes.

    python scripts/test-ecosystem-update.py [--keep]

Nothing is mocked: real v0.2.1 server code (from git history) creates the "existing VPS"; the
real installer adopts it; real signed release bundles are built with a throw-away test key; the
real update agent installs, migrates, restarts, verifies, rolls back and recovers; a real worker
process connects over HTTP and updates itself. Steps:

 1. a v0.2.1 MOTH Server with an Owner account is running (the situation on the VPS today)
 2. install-server.sh adopts it in place (verified backup, migration, supervision)
 3. accounts survive; the Owner can sign in with the old password
 4. a worker (0.3.0) enrolls and runs over HTTP
 5. release 0.3.1 (with a new additive migration and a new agent) is published → the agent detects,
    downloads, verifies, backs up, migrates, restarts, health-checks; the agent updates itself
 6. the worker is offered 0.3.1, installs it between jobs, restarts into it and reconnects
 7. broken release 0.3.2 (crashes after migrating) → automatic rollback incl. database restore
 8. a tampered release is ignored
 9. release 0.3.4 with the agent "crashing" right after switching → recovered on the next run
10. "reboot": every MOTH process is killed; the supervisor brings MOTH Cloud back
11. Owner-requested rollback from the dashboard API
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "crimson wings 2026!"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def step(msg: str) -> None:
    print(f"\n=== {msg}", flush=True)


def ok(msg: str) -> None:
    print(f"  ✓ {msg}", flush=True)


def sh(cmd, **kw) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise SystemExit(f"FAILED: {' '.join(map(str, cmd))}\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return r.stdout


class Api:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.token = None

    def call(self, method, path, body=None, client="desktop/0.3.0", expect=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json", "X-Moth-Client": client,
                                              **({"Authorization": f"Bearer {self.token}"} if self.token else {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
                status = r.status
        except urllib.error.HTTPError as e:
            data, status = e.read(), e.code
        if expect and status != expect:
            raise SystemExit(f"FAILED: {method} {path} → {status} {data[:500]!r}")
        return status, (json.loads(data) if data else None)

    def health(self):
        try:
            with urllib.request.urlopen(self.base + "/v1/health", timeout=5) as r:
                return json.loads(r.read())
        except (urllib.error.URLError, OSError, ValueError):
            return None

    def wait(self, pred, what, timeout=180):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = self.health()
            if last and pred(last):
                return last
            time.sleep(1)
        raise SystemExit(f"FAILED: timed out waiting for {what} (last health: {last})")

    def login(self):
        st, body = self.call("POST", "/v1/auth/login", {"username": "LK5T", "password": PASSWORD}, expect=200)
        self.token = body["token"]
        return body


def make_test_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    sk = Ed25519PrivateKey.generate()
    pub = base64.b64encode(sk.public_key().public_bytes(serialization.Encoding.Raw,
                                                        serialization.PublicFormat.Raw)).decode()
    priv = base64.b64encode(sk.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                             serialization.NoEncryption())).decode()
    return pub, priv


def variant(work: Path, version: str, *, migration: int | None = None, crash: bool = False,
            agent_version: str | None = None) -> Path:
    """A copy of this repository at ``version``, optionally with an extra additive migration, a server
    that crashes at startup after migrating, or a different agent."""
    dst = work / f"repo-{version}"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(".git", "node_modules", "target", "__pycache__", "dist",
                                                             "*.egg-info", ".pytest_cache", "app"))
    for f in ("server/moth_server/__init__.py", "backend/moth/__init__.py", "worker/moth_worker/__init__.py"):
        p = dst / f
        p.write_text(re.sub(r'__version__ = "[^"]+"', f'__version__ = "{version}"', p.read_text()))
    if migration:
        p = dst / "server/moth_server/db.py"
        s = p.read_text()
        s = re.sub(r"SCHEMA_VERSION = \d+", f"SCHEMA_VERSION = {migration}", s)
        s = s.replace("MIGRATIONS: list[tuple[int, str, bool, Any]] = [", f'''def _m{migration}_probe(c: Connection) -> None:
    c.execute(text("CREATE TABLE IF NOT EXISTS upgrade_probe_{migration} (id INTEGER PRIMARY KEY)"))


MIGRATIONS: list[tuple[int, str, bool, Any]] = [''')
        prev = s.split("MIGRATIONS: list[tuple[int, str, bool, Any]] = [", 1)
        s = prev[0] + "MIGRATIONS: list[tuple[int, str, bool, Any]] = [" + prev[1].replace(
            "\n]\n", f'\n    ({migration}, "test probe table", False, _m{migration}_probe),\n]\n', 1)
        p.write_text(s)
    if crash:
        p = dst / "server/moth_server/app.py"
        p.write_text(p.read_text().replace("    db.migrate()  # additive", "    db.migrate()\n    raise RuntimeError('broken release')  # additive", 1))
    if agent_version:
        p = dst / "deploy/agent/moth_agent.py"
        p.write_text(re.sub(r'AGENT_VERSION = "[^"]+"', f'AGENT_VERSION = "{agent_version}"', p.read_text()))
    return dst


def build(repo: Path, out: Path, priv: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "MOTH_RELEASE_SIGNING_KEY": priv}
    sh([sys.executable, str(repo / "scripts/build-release.py"), "--out", str(out)], env=env, cwd=repo)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()
    base = os.environ.get("MOTH_E2E_DIR")
    if base:
        Path(base).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="moth-e2e-", dir=base or None))
    port = free_port()
    api = Api(port)
    procs: list[subprocess.Popen] = []
    home = work / "home"
    moth = home / "bin" / "moth"
    print(f"work dir {work}, port {port}")
    pub, priv = make_test_key()
    src = work / "releases"
    try:
        # ---- 1. today's VPS: a v0.2.1 server started by hand -------------------------------------------
        step("1. existing v0.2.1 MOTH Server (code from git history)")
        old = work / "v021"
        sh(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(old), "599aa26"])
        old_data = work / "old-data"
        old_env = {**os.environ, "PYTHONPATH": f"{old / 'server'}:{old / 'backend'}", "MOTH_SERVER_DATA_DIR": str(old_data)}
        p = subprocess.run([sys.executable, "-m", "moth_server.cli", "init-owner", "--email", "owner@moth.test",
                            "--password-stdin"], input=PASSWORD + "\n", text=True, env=old_env, capture_output=True,
                           cwd=work)
        assert p.returncode == 0, p.stderr
        legacy = subprocess.Popen([sys.executable, "-m", "moth_server.cli", "serve", "--port", str(port)], env=old_env,
                                  cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        procs.append(legacy)
        h = api.wait(lambda h: h.get("status") == "ok", "v0.2.1 server")
        ok(f"v0.2.1 server running (reports {h['version']}), no schema_version/api_version in health: "
           f"{'api_version' not in h}")

        # ---- 2. install 0.3.0 adopting it -----------------------------------------------------------------
        step("2. one-time installation adopting the running server")
        build(ROOT, src / "0.3.0", priv)
        bundle_dir = work / "bundle"
        bundle_dir.mkdir()
        with tarfile.open(src / "0.3.0" / "moth-cloud-0.3.0.tar.gz") as t:
            t.extractall(bundle_dir, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(bundle_dir)
        out = sh(["bash", str(bundle_dir / "moth-cloud-0.3.0/deploy/install-server.sh"), "--home", str(home),
                  "--supervisor", "cron", "--release-source", f"dir:{src}", "--pubkey", pub, "--adopt-data",
                  str(old_data), "--replace-running", "--port", str(port), "--environment", "staging",
                  "--use-system-packages"])
        print("\n".join("    " + line for line in out.strip().splitlines()[-12:]))
        h = api.wait(lambda h: h.get("version") == "0.3.0", "0.3.0 after install")
        assert h["schema_version"] == 2
        assert list((home / "backups").glob("*pre-install-0.3.0")), "pre-install backup missing"
        cfg = json.loads((home / "config" / "agent.json").read_text())
        (home / "config" / "agent.json").write_text(json.dumps({**cfg, "health_timeout_s": 60}))  # faster failure tests
        ok("installed 0.3.0; v0.2 database migrated to schema 2 after a verified backup")

        # ---- 3. accounts preserved -------------------------------------------------------------------------
        step("3. existing Owner account and password preserved")
        api.login()
        ok("LK5T signed in with the password set under v0.2.1")
        api.call("PUT", "/v1/admin/config/flags", {"allow_cpu_workers": True, "training_enrollment_open": True},
                 expect=200)

        # ---- 4. a worker on 0.3.0 ------------------------------------------------------------------------
        step("4. MOTH Worker 0.3.0 enrolls and runs over HTTP")
        _, e = api.call("POST", "/v1/training/enrollments", {"name": "e2e-worker"}, expect=200)
        whome = work / "worker-home"
        wenv = {**os.environ, "PYTHONPATH": f"{ROOT / 'worker'}:{ROOT / 'backend'}", "MOTH_RELEASE_PUBKEY": pub,
                "MOTH_WORKER_UPDATE_CHECK_SECONDS": "3"}
        sh([sys.executable, "-m", "moth_worker.cli", "--home", str(whome), "enroll", "--server", api.base,
            "--token", e["token"], "--allow-cpu"], env=wenv)
        wlog = open(work / "worker.log", "w")
        worker = subprocess.Popen([sys.executable, "-m", "moth_worker.cli", "--home", str(whome), "run"], env=wenv,
                                  stdout=wlog, stderr=subprocess.STDOUT, start_new_session=True)
        procs.append(worker)
        for _ in range(60):
            _, ws = api.call("GET", "/v1/admin/workers", expect=200)
            if ws and any(w.get("version") == "0.3.0" for w in (ws.get("workers") if isinstance(ws, dict) else ws)):
                break
            time.sleep(1)
        else:
            raise SystemExit("FAILED: worker did not report version 0.3.0")
        ok("worker connected and reports 0.3.0")

        # ---- 5. server update 0.3.1 ------------------------------------------------------------------------
        step("5. release 0.3.1 → automatic server update (migration 3, new agent)")
        build(variant(work, "0.3.1", migration=3, agent_version="0.3.1"), src / "0.3.1", priv)
        res = sh([str(moth), "check"]).strip().splitlines()[-1]
        h = api.wait(lambda h: h.get("version") == "0.3.1", "0.3.1")
        assert h["schema_version"] == 3, h
        assert res == "agent-updated", res
        assert (home / "agent" / "current").resolve().name == "0.3.1"
        _, upd = api.call("GET", "/v1/admin/updates", expect=200)
        dep = upd["deployments"][0]
        assert dep["to_version"] == "0.3.1" and dep["status"] == "succeeded", dep
        assert "backup verified" in dep["log"]
        assert list((home / "backups").glob("*pre-0.3.1"))
        api.login()
        ok("0.3.1 healthy, schema 3, deployment recorded with log, backup verified, agent self-updated to 0.3.1")

        # ---- 6. worker update ------------------------------------------------------------------------------
        step("6. worker is offered 0.3.1 and updates itself")
        api.call("POST", "/v1/admin/updates/releases/worker/0.3.1/promote", expect=200)
        for _ in range(120):
            _, ws = api.call("GET", "/v1/admin/workers", expect=200)
            ws = ws.get("workers") if isinstance(ws, dict) else ws
            if any(w.get("version") == "0.3.1" for w in ws):
                break
            time.sleep(1)
        else:
            raise SystemExit("FAILED: worker did not update:\n" + (work / "worker.log").read_text()[-3000:])
        assert (whome / "current").resolve().name == "0.3.1"
        assert worker.poll() is None, "worker process should still be running (it re-executed itself)"
        time.sleep(2)
        _, upd = api.call("GET", "/v1/admin/updates", expect=200)
        wrel = next(r for r in upd["releases"] if r["component"] == "worker" and r["version"] == "0.3.1")
        assert wrel["reports"]["succeeded"] >= 1, wrel
        ok("worker verified, installed, restarted into 0.3.1, reconnected and reported success")

        # ---- 7. broken release → rollback ----------------------------------------------------------------------
        step("7. broken release 0.3.2 (migrates to schema 4, then crashes) → automatic rollback")
        build(variant(work, "0.3.2", migration=4, crash=True), src / "0.3.2", priv)
        res = sh([str(moth), "check"]).strip().splitlines()[-1]
        assert res == "failed", res
        h = api.wait(lambda h: h.get("version") == "0.3.1", "0.3.1 after rollback")
        assert h["schema_version"] == 3, f"database should be restored to schema 3: {h}"
        st = json.loads((home / "state" / "agent-state.json").read_text())
        assert "0.3.2" in st["failed"]
        api.login()
        _, upd = api.call("GET", "/v1/admin/updates", expect=200)
        assert upd["deployments"][0]["status"] == "rolled_back", upd["deployments"][0]
        ok("rolled back to 0.3.1, database restored to schema 3, Owner notified, failure recorded")

        # ---- 8. tampered release ignored -------------------------------------------------------------------------
        step("8. tampered release is ignored")
        t = build(variant(work, "0.3.3"), src / "0.3.3", priv)
        mf = t / "moth-release-0.3.3.json"
        mf.write_text(mf.read_text().replace('"stable"', '"stable" '))
        res = sh([str(moth), "check"]).strip().splitlines()[-1]
        assert res == "up-to-date" and api.health()["version"] == "0.3.1", res
        ok("manifest with an invalid signature was not installed")

        # ---- 9. crash in the middle of an update ---------------------------------------------------------------
        step("9. agent crashes right after switching to 0.3.4 → recovered on the next run")
        build(variant(work, "0.3.4", migration=3), src / "0.3.4", priv)
        p = subprocess.run([str(moth), "check"], env={**os.environ, "MOTH_AGENT_TEST_CRASH": "after-switch"},
                           capture_output=True, text=True)
        assert p.returncode == 9, (p.returncode, p.stderr[-500:])
        assert json.loads((home / "state" / "agent-state.json").read_text()).get("in_progress", {}).get("to") == "0.3.4"
        sh([str(moth), "check"])
        h = api.wait(lambda h: h.get("version") == "0.3.4", "0.3.4 after recovery")
        assert "in_progress" not in json.loads((home / "state" / "agent-state.json").read_text())
        ok("interrupted update finished and verified on the next agent run")

        # ---- 10. reboot -------------------------------------------------------------------------------------------
        step("10. reboot: all MOTH Cloud processes killed, supervisor restores them")
        for name in ("server", "agent"):
            pf = home / "run" / f"{name}.pid"
            if pf.exists():
                try:
                    os.kill(int(pf.read_text()), signal.SIGKILL)
                except (ProcessLookupError, ValueError):
                    pass
        time.sleep(1)
        assert api.health() is None
        sh([str(moth), "supervise"])  # what @reboot and the per-minute cron run
        h = api.wait(lambda h: h.get("version") == "0.3.4", "server after reboot")
        ok("MOTH Cloud 0.3.4 back after a simulated reboot")

        # ---- 11. Owner rollback --------------------------------------------------------------------------------------
        step("11. Owner-requested rollback from the dashboard")
        api.login()
        api.call("POST", "/v1/admin/updates/server/rollback", expect=200)
        sh([str(moth), "check"])
        h = api.wait(lambda h: h.get("version") == "0.3.1", "rollback to 0.3.1")
        api.login()
        ok("rolled back to 0.3.1 on request; accounts intact")
        print("\nPASS: installation, adoption, server/agent/worker updates, rollback, recovery and reboot all verified")
    finally:
        for name in ("server", "agent"):
            pf = home / "run" / f"{name}.pid"
            try:
                os.kill(int(pf.read_text()), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(work / "v021")],
                       capture_output=True)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
        else:
            print(f"kept {work}")


if __name__ == "__main__":
    main()
