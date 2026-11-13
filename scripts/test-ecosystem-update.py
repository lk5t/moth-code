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
    # the code under test is BASE; V1..V4 are newer releases built from modified copies of it
    BASE = re.search(r'__version__ = "([^"]+)"', (ROOT / "server/moth_server/__init__.py").read_text())[1]
    SCHEMA = int(re.search(r"SCHEMA_VERSION = (\d+)", (ROOT / "server/moth_server/db.py").read_text())[1])
    major, minor, patch = (int(x) for x in BASE.split("."))
    V1, V2, V3, V4 = (f"{major}.{minor}.{patch + 90 + i}" for i in range(1, 5))
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
        build(ROOT, src / BASE, priv)
        bundle_dir = work / "bundle"
        bundle_dir.mkdir()
        with tarfile.open(src / BASE / f"moth-cloud-{BASE}.tar.gz") as t:
            t.extractall(bundle_dir, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(bundle_dir)
        out = sh(["bash", str(bundle_dir / f"moth-cloud-{BASE}/deploy/install-server.sh"), "--home", str(home),
                  "--supervisor", "cron", "--release-source", f"dir:{src}", "--pubkey", pub, "--adopt-data",
                  str(old_data), "--replace-running", "--port", str(port), "--environment", "staging",
                  "--use-system-packages"])
        print("\n".join("    " + line for line in out.strip().splitlines()[-12:]))
        h = api.wait(lambda h: h.get("version") == BASE, f"{BASE} after install")
        assert h["schema_version"] == SCHEMA
        assert list((home / "backups").glob(f"*pre-install-{BASE}")), "pre-install backup missing"
        cfg = json.loads((home / "config" / "agent.json").read_text())
        (home / "config" / "agent.json").write_text(json.dumps({**cfg, "health_timeout_s": 60}))  # faster failure tests
        ok(f"installed {BASE}; v0.2 database migrated to schema {SCHEMA} after a verified backup")

        # ---- 3. accounts preserved -------------------------------------------------------------------------
        step("3. existing Owner account and password preserved")
        api.login()
        ok("LK5T signed in with the password set under v0.2.1")
        api.call("PUT", "/v1/admin/config/flags", {"allow_cpu_workers": True, "training_enrollment_open": True},
                 expect=200)

        # ---- 4. a worker on 0.3.0 ------------------------------------------------------------------------
        step(f"4. MOTH Worker {BASE} enrolls and runs over HTTP")
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
            # the external worker under test, not MOTH Cloud's built-in worker (0.7.2), which runs the server's version
            if ws and any(w.get("version") == BASE and w.get("name") != "MOTH Cloud server"
                          for w in (ws.get("workers") if isinstance(ws, dict) else ws)):
                break
            time.sleep(1)
        else:
            raise SystemExit(f"FAILED: worker did not report version {BASE}")
        ok(f"worker connected and reports {BASE}")

        # ---- 5. server update 0.3.1 ------------------------------------------------------------------------
        step(f"5. release {V1} → automatic server update (migration {SCHEMA + 1}, new agent)")
        build(variant(work, V1, migration=SCHEMA + 1, agent_version=V1), src / V1, priv)
        res = sh([str(moth), "check"]).strip().splitlines()[-1]
        h = api.wait(lambda h: h.get("version") == V1, V1)
        assert h["schema_version"] == SCHEMA + 1, h
        assert res == "agent-updated", res
        assert (home / "agent" / "current").resolve().name == V1
        _, upd = api.call("GET", "/v1/admin/updates", expect=200)
        dep = upd["deployments"][0]
        assert dep["to_version"] == V1 and dep["status"] == "succeeded", dep
        assert "backup verified" in dep["log"]
        assert list((home / "backups").glob(f"*pre-{V1}"))
        api.login()
        ok(f"{V1} healthy, schema {SCHEMA + 1}, deployment recorded with log, backup verified, agent self-updated to {V1}")

        # ---- 6. worker update ------------------------------------------------------------------------------
        step(f"6. worker is offered {V1} and updates itself")
        api.call("POST", f"/v1/admin/updates/releases/worker/{V1}/promote", expect=200)
        for _ in range(120):
            _, ws = api.call("GET", "/v1/admin/workers", expect=200)
            ws = ws.get("workers") if isinstance(ws, dict) else ws
            if any(w.get("version") == V1 and w.get("name") != "MOTH Cloud server" for w in ws):
                break
            time.sleep(1)
        else:
            raise SystemExit("FAILED: worker did not update:\n" + (work / "worker.log").read_text()[-3000:])
        assert (whome / "current").resolve().name == V1
        assert worker.poll() is None, "worker process should still be running (it re-executed itself)"
        time.sleep(2)
        _, upd = api.call("GET", "/v1/admin/updates", expect=200)
        wrel = next(r for r in upd["releases"] if r["component"] == "worker" and r["version"] == V1)
        assert wrel["reports"]["succeeded"] >= 1, wrel
        ok(f"worker verified, installed, restarted into {V1}, reconnected and reported success")

        # ---- 7. broken release → rollback ----------------------------------------------------------------------
        step(f"7. broken release {V2} (migrates to schema {SCHEMA + 2}, then crashes) → automatic rollback")
        build(variant(work, V2, migration=SCHEMA + 2, crash=True), src / V2, priv)
        res = sh([str(moth), "check"]).strip().splitlines()[-1]
        assert res == "failed", res
        h = api.wait(lambda h: h.get("version") == V1, f"{V1} after rollback")
        assert h["schema_version"] == SCHEMA + 1, f"database should be restored to schema {SCHEMA + 1}: {h}"
        st = json.loads((home / "state" / "agent-state.json").read_text())
        assert V2 in st["failed"]
        api.login()
        _, upd = api.call("GET", "/v1/admin/updates", expect=200)
        assert upd["deployments"][0]["status"] == "rolled_back", upd["deployments"][0]
        ok(f"rolled back to {V1}, database restored to schema {SCHEMA + 1}, Owner notified, failure recorded")

        # ---- 8. tampered release ignored -------------------------------------------------------------------------
        step("8. tampered release is ignored")
        t = build(variant(work, V3), src / V3, priv)
        mf = t / f"moth-release-{V3}.json"
        mf.write_text(mf.read_text().replace('"stable"', '"stable" '))
        res = sh([str(moth), "check"]).strip().splitlines()[-1]
        assert res == "up-to-date" and api.health()["version"] == V1, res
        ok("manifest with an invalid signature was not installed")

        # ---- 9. crash in the middle of an update ---------------------------------------------------------------
        step(f"9. agent crashes right after switching to {V4} → recovered on the next run")
        build(variant(work, V4, migration=SCHEMA + 1), src / V4, priv)
        p = subprocess.run([str(moth), "check"], env={**os.environ, "MOTH_AGENT_TEST_CRASH": "after-switch"},
                           capture_output=True, text=True)
        assert p.returncode == 9, (p.returncode, p.stderr[-500:])
        assert json.loads((home / "state" / "agent-state.json").read_text()).get("in_progress", {}).get("to") == V4
        sh([str(moth), "check"])
        h = api.wait(lambda h: h.get("version") == V4, f"{V4} after recovery")
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
        try:
            h = api.wait(lambda h: h.get("version") == V4, "server after reboot", timeout=120)
        except SystemExit:
            print("run/:", {p.name: p.read_text()[:40] for p in (home / "run").iterdir()})
            print("server.log:", (home / "logs" / "server.log").read_text()[-3000:])
            print("agent.log:", (home / "logs" / "agent.log").read_text()[-3000:])
            raise
        ok(f"MOTH Cloud {V4} back after a simulated reboot")

        # ---- 11. Owner rollback --------------------------------------------------------------------------------------
        step("11. Owner-requested rollback from the dashboard")
        api.login()
        api.call("POST", "/v1/admin/updates/server/rollback", expect=200)
        sh([str(moth), "check"])
        h = api.wait(lambda h: h.get("version") == V1, f"rollback to {V1}")
        api.login()
        ok(f"rolled back to {V1} on request; accounts intact")

        step("12. signed official model release (MOTH 0.1) → agent imports it, server evaluates and deploys it")
        mdir = src / "model-0.1"
        mdir.mkdir(parents=True, exist_ok=True)
        make = (
            "import json, sys, torch\n"
            "from pathlib import Path\n"
            "from moth.model.config import preset\n"
            "from moth.model.registry import export_model\n"
            "from moth.model.tokenizer import train_bpe\n"
            "from moth.model.transformer import MothModel\n"
            "w = Path(sys.argv[1]); tok = train_bpe(['def add(a, b):\\n    return a + b\\n'] * 20, vocab_size=300)\n"
            "tok.save(w / 'tok.json'); torch.manual_seed(7); cfg = preset('moth-tiny', vocab_size=320)\n"
            "torch.save({'model': MothModel(cfg).state_dict(), 'model_config': cfg.to_dict(), 'tokenizer_path': str(w / 'tok.json'),\n"
            "            'tokenizer_fingerprint': tok.fingerprint(), 'step': 1}, w / 'ck.pt')\n"
            "i = export_model(w / 'ck.pt', w / 'pkg', 'moth-0.1', dtype='float32', extra={'model_version': '0.1',\n"
            "    'display_name': 'MOTH 0.1 — Foundation', 'family': 'MOTH', 'lineage_id': 'moth-e2e', 'method': 'foundation'})\n"
            "(w / 'ev.json').write_text(json.dumps({'criteria': {'passed': True, 'criteria': []}})); print(i['path'])\n")
        env = {**os.environ, "PYTHONPATH": str(ROOT / "backend")}
        pkg = sh([sys.executable, "-c", make, str(work)], env=env).strip().splitlines()[-1]
        sh([sys.executable, str(ROOT / "scripts/build-model-release.py"), "--package", pkg, "--evaluation",
            str(work / "ev.json"), "--version", "0.1", "--out", str(mdir)], env={**env, "MOTH_RELEASE_SIGNING_KEY": priv})
        sh([str(moth), "check"])
        api.login()

        def deployed_model():
            _, body = api.call("GET", "/v1/admin/models", expect=200)
            rel = next((r for r in body.get("releases", []) if r.get("version") == body.get("deployed")), None)
            return rel if rel and (rel.get("info") or {}).get("model_version") == "0.1" else None

        for _ in range(240):
            rel = deployed_model()
            if rel:
                break
            time.sleep(1)
        else:
            raise SystemExit("FAILED: MOTH 0.1 was not imported and deployed")
        sh([str(moth), "check"])  # a second check never imports the same model again
        _, body = api.call("GET", "/v1/admin/models", expect=200)
        assert sum((r.get("info") or {}).get("model_version") == "0.1" for r in body["releases"]) == 1
        ok(f"MOTH 0.1 imported (signature and SHA-256 re-verified), evaluated and deployed as release v{rel['version']}")
        print("\nPASS: installation, adoption, server/agent/worker updates, rollback, recovery, reboot and signed "
              "model delivery all verified")
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
