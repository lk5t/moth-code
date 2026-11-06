#!/usr/bin/env python3
"""Upgrade test from the MOTH Cloud release the VPS runs today (server-v0.3.2) to the code under test.

Real processes, real installer, real update agent, real signed release bundles (throw-away test key):

1. install the exact ``server-v0.3.2`` code (git history) with its own ``install-server.sh``, adopting a
   data directory with the Owner account;
2. on 0.3.2: upload a model, evaluate it, deploy it, enable MOTH Cloud inference, serve a chat request;
3. publish the release under test → the 0.3.2 agent verifies it, backs up, migrates, switches, and
   updates itself;
4. after the upgrade: same Owner password, same deployed model (same SHA-256) serving chat, schema
   migrated, the model's lineage recorded, the Evolution API working, and evolution behaving safely
   without a GPU (training data approved → the cycle waits for compute and says why; nothing trains);
5. Owner-requested rollback to 0.3.2 → the code switches back after a pre-rollback backup; the data is
   kept (0.3.2 runs on the additively migrated schema), so nothing created after the upgrade is lost, and
   the Owner and the model are intact. (A *failed* update is rolled back with a database restore; that
   path is covered by test-ecosystem-update.py.)

    python scripts/test-upgrade-from-installed.py
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from importlib import import_module  # noqa: E402

E = import_module("test-ecosystem-update")
ROOT = E.ROOT
INSTALLED = "5808bc6"  # the commit tagged server-v0.3.2 (what the VPS runs)


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, (name, data) in files.items():
        out.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\n"
                  f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


def upload(api, path: str, fields: dict, files: dict, expect=200) -> dict:
    body, ctype = multipart(fields, files)
    req = urllib.request.Request(api.base + path, data=body, method="POST",
                                 headers={"Content-Type": ctype, "Authorization": f"Bearer {api.token}",
                                          "X-Moth-Client": "desktop/0.4.0"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            status, data = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, data = e.code, e.read()
    if status != expect:
        raise SystemExit(f"FAILED: upload {path} → {status} {data[:400]!r}")
    return json.loads(data)


def tiny_model_tarball(work: Path) -> bytes:
    sys.path[:0] = [str(ROOT / "backend")]
    import torch

    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import train_bpe
    from moth.model.transformer import MothModel

    tok = train_bpe(["def add(a, b):\n    return a + b\n"] * 20, vocab_size=300)
    tok.save(work / "tok.json")
    torch.manual_seed(7)
    cfg = preset("moth-tiny", vocab_size=320)
    torch.save({"model": MothModel(cfg).state_dict(), "model_config": cfg.to_dict(),
                "tokenizer_path": str(work / "tok.json"), "tokenizer_fingerprint": tok.fingerprint(), "step": 1},
               work / "ck.pt")
    info = export_model(work / "ck.pt", work / "models", "moth-vps-model", dtype="float32")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(info["path"], arcname="model")
    return buf.getvalue()


def chat(api) -> int:
    """A real MOTH Cloud chat request (streamed NDJSON). Returns the HTTP status; asserts tokens were made."""
    _, h = api.call("GET", "/cloud/v1/health", expect=200)
    body = json.dumps({"model": h["models"][0]["name"], "messages": [{"role": "user", "content": "def add("}],
                       "params": {"max_new_tokens": 4, "temperature": 0}}).encode()
    req = urllib.request.Request(api.base + "/cloud/v1/chat", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {api.token}",
                                          "X-Moth-Client": "desktop/0.4.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        lines = [json.loads(line) for line in r.read().decode().splitlines() if line.strip()]
        assert lines[-1].get("done") and lines[-1]["stats"]["generated_tokens"] > 0, lines
        return r.status


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="moth-upgrade-"))
    port = E.free_port()
    api = E.Api(port)
    home = work / "home"
    moth = home / "bin" / "moth"
    pub, priv = E.make_test_key()
    src = work / "releases"
    target = re.search(r'__version__ = "([^"]+)"', (ROOT / "server/moth_server/__init__.py").read_text())[1]
    schema = int(re.search(r"SCHEMA_VERSION = (\d+)", (ROOT / "server/moth_server/db.py").read_text())[1])
    print(f"work dir {work}, port {port}; upgrading 0.3.2 → {target}")
    old = work / "v032"
    try:
        E.step("1. install server-v0.3.2 (the release the VPS runs) with its own installer")
        E.sh(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(old), INSTALLED])
        data = work / "data"
        env = {**os.environ, "PYTHONPATH": f"{old / 'server'}:{old / 'backend'}", "MOTH_SERVER_DATA_DIR": str(data)}
        p = subprocess.run([sys.executable, "-m", "moth_server.cli", "init-owner", "--email", "owner@moth.test",
                            "--password-stdin"], input=E.PASSWORD + "\n", text=True, env=env, capture_output=True,
                           cwd=work)
        assert p.returncode == 0, p.stderr
        E.build(old, src / "0.3.2", priv)
        bundle = work / "bundle"
        bundle.mkdir()
        with tarfile.open(src / "0.3.2" / "moth-cloud-0.3.2.tar.gz") as t:
            t.extractall(bundle, filter="data") if hasattr(tarfile, "data_filter") else t.extractall(bundle)
        E.sh(["bash", str(bundle / "moth-cloud-0.3.2/deploy/install-server.sh"), "--home", str(home), "--supervisor",
              "cron", "--release-source", f"dir:{src}", "--pubkey", pub, "--adopt-data", str(data), "--port", str(port),
              "--environment", "staging", "--use-system-packages"])
        h = api.wait(lambda h: h.get("version") == "0.3.2", "0.3.2 after install")
        assert h["schema_version"] == 2
        cfg = json.loads((home / "config" / "agent.json").read_text())
        (home / "config" / "agent.json").write_text(json.dumps({**cfg, "health_timeout_s": 90}))
        E.ok("MOTH Cloud 0.3.2 installed by its own installer (schema 2)")

        E.step("2. on 0.3.2: a deployed model serving chat")
        api.login()
        rel = upload(api, "/v1/admin/models/upload", {"name": "moth-vps-model"},
                     {"file": ("model.tar.gz", tiny_model_tarball(work))})
        v = rel["version"]
        api.call("POST", f"/v1/admin/models/{v}/evaluate", expect=200)
        for _ in range(120):
            _, models = api.call("GET", "/v1/admin/models", expect=200)
            r = next(x for x in models["releases"] if x["version"] == v)
            if r["status"] in ("published", "failed", "evaluated"):
                break
            time.sleep(1)
        assert r["status"] == "published", r
        api.call("POST", f"/v1/admin/models/{v}/deploy", expect=200)
        api.call("PUT", "/v1/admin/config/flags", {"cloud_inference_enabled": True}, expect=200)
        sha_before = r["sha256"]
        assert chat(api) == 200
        E.ok(f"model v{v} deployed on 0.3.2 and serving chat (sha {sha_before[:12]})")

        E.step(f"3. release {target} published → the 0.3.2 agent installs it")
        E.build(ROOT, src / target, priv)
        E.sh([str(moth), "check"])
        h = api.wait(lambda h: h.get("version") == target, f"{target} after the update", timeout=300)
        assert h["schema_version"] == schema, h
        assert list((home / "backups").glob("*")), "no pre-update backup"
        E.sh([str(moth), "supervise"])  # the restarted (self-updated) agent
        E.ok(f"updated to {target}: verified bundle, backup, migration to schema {schema}")

        E.step("4. after the upgrade: accounts, model and service preserved; evolution safe without a GPU")
        api.login()
        _, models = api.call("GET", "/v1/admin/models", expect=200)
        r = next(x for x in models["releases"] if x["version"] == v)
        assert r["status"] == "deployed" and r["sha256"] == sha_before, r
        api.wait(lambda h: h.get("model_version") == v, "the model to be restored after the restart", timeout=120)
        assert chat(api) == 200
        E.ok(f"Owner signs in with the same password; model v{v} (same SHA-256) is deployed and serving chat")
        _, st = api.call("GET", "/v1/admin/evolution/status", expect=200)
        assert st["active_model"]["version"] == v and st["active_model"]["method"] == "upload", st["active_model"]
        _, res = api.call("GET", "/v1/admin/evolution/resources", expect=200)
        gpus = res["local"]["gpus"]
        E.ok(f"Evolution API works; lineage of v{v} recorded as 'upload'; server GPUs: {len(gpus)}")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for i in range(80):
                z.writestr(f"m{i}.py", f"def f_{i}(x):\n    return x * {i} + {i}\n\n" * 40)
        d = upload(api, "/v1/admin/evolution/datasets", {"name": "e2e code", "license": "MIT", "tags": "code"},
                   {"file": ("code.zip", buf.getvalue())})
        api.call("PUT", "/v1/admin/evolution/settings", {"changes": {"min_dataset_tokens": 1000, "backends": {
            "local_cpu": False, "local_gpu": True, "workers": True}}}, expect=200)
        api.call("POST", f"/v1/admin/evolution/datasets/{d['id']}/approve", {}, expect=200)
        for _ in range(90):
            _, st = api.call("GET", "/v1/admin/evolution/status", expect=200)
            if st["cycle"] and st["cycle"]["status"] == "waiting_for_compute":
                break
            time.sleep(1)
        assert st["cycle"]["status"] == "waiting_for_compute", st["cycle"]
        assert st["cycle"]["experiments"] and all(e["status"] in ("waiting", "planned") for e in st["cycle"]["experiments"])
        assert st["cycle"]["experiments"][0]["status"] == "waiting"  # tried, and waits: nothing is running
        reason = st["cycle"]["result"]["waiting_reason"]
        assert chat(api) == 200
        E.ok(f"approved data → cycle planned and waiting for compute (\"{reason}\"); nothing trains; chat still works")

        E.step("5. Owner-requested rollback to 0.3.2")
        api.call("POST", "/v1/admin/updates/server/rollback", expect=200)
        E.sh([str(moth), "check"])
        h = api.wait(lambda h: h.get("version") == "0.3.2", "rollback to 0.3.2", timeout=300)
        assert h["schema_version"] == schema, h  # data kept: 0.3.2 runs on the additive schema
        assert list((home / "backups").glob("*pre-rollback-0.3.2*")), "no pre-rollback backup"
        api.login()
        _, models = api.call("GET", "/v1/admin/models", expect=200)
        r = next(x for x in models["releases"] if x["version"] == v)
        assert r["status"] == "deployed" and r["sha256"] == sha_before
        api.wait(lambda h: h.get("model_version") == v, "the model after rollback", timeout=120)
        assert chat(api) == 200
        db = next((home / "data").glob("**/moth-server.db"), None) or next(data.glob("**/moth-server.db"))
        import sqlite3

        con = sqlite3.connect(db)
        kept = con.execute("SELECT name, status FROM training_datasets").fetchall()
        con.close()
        assert kept and kept[0][1] == "approved", kept
        E.ok(f"back on 0.3.2 after a pre-rollback backup: Owner, model v{v} and data intact (schema {schema} kept, "
             f"the evolution data created on {target} too: {kept[0][0]!r})")
        print(f"\nPASS: 0.3.2 → {target} upgrade, preservation, safe evolution without GPU, and rollback verified")
    finally:
        import signal

        for name in ("server", "agent"):
            try:
                os.kill(int((home / "run" / f"{name}.pid").read_text()), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(old)], capture_output=True)


if __name__ == "__main__":
    main()
