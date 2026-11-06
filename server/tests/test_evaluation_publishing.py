"""v0.3 model publishing: evaluation datasets, guided recovery, retries, resumable uploads.

These use real MOTH models (exported moth-tiny weights), real evaluation in a subprocess and,
for the migration test, a database built with the actual v0.2 schema from git history.
"""

import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text

from conftest import H, make_tiny_model
from moth_server import evalsets as E
from moth_server import models as M
from moth_server.app import create_app
from moth_server.db import model_releases

ROOT = Path(__file__).resolve().parents[2]
SYNC = {"synchronous_jobs": True, "disable_background": True}
LEGACY_ERROR = "ReleaseError: no evaluation set is configured (coordinator probe or data/eval/tokens.bin)"


def tar_bytes(model_dir, gz=True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz" if gz else "w") as tar:
        tar.add(model_dir, arcname=model_dir.name)
    return buf.getvalue()


def held_out_text() -> bytes:
    return ("\n".join(f"def function_{i}(value):\n    '''Return a transformed value.'''\n    total = value * {i} + 7\n"
                      f"    return total if total > {i} else -total\n" for i in range(200))).encode()


def login_owner(client, settings, monkeypatch):
    from moth_server import cli

    monkeypatch.setenv("MOTH_SERVER_DATA_DIR", str(settings.data_dir))
    if settings.database_url:
        monkeypatch.setenv("MOTH_SERVER_DATABASE_URL", settings.database_url)
    monkeypatch.setattr(sys, "stdin", io.StringIO("crimson wings 2026!\n"))
    assert cli.main(["init-owner", "--email", "owner@moth.test", "--password-stdin"]) == 0
    r = client.post("/v1/auth/login", json={"username": "lk5t", "password": "crimson wings 2026!"})
    return H(r.json()["token"])


# ---- the reported failure, reproduced on a real v0.2 database --------------------------------------
def v02_metadata():
    src = subprocess.run(["git", "-C", str(ROOT), "show", "599aa26:server/moth_server/db.py"], capture_output=True,
                         text=True, check=True).stdout
    spec = importlib.util.spec_from_loader("moth_v02_db", loader=None)
    mod = importlib.util.module_from_spec(spec)
    exec(compile(src, "v0.2/db.py", "exec"), mod.__dict__)  # noqa: S102 — our own file from git history
    return mod


def test_v02_rejected_model_is_recovered_without_reupload(settings, tmp_path, monkeypatch):
    """moth-50m-v0.1-step5000 situation: rejected by v0.2 with 'no evaluation set is configured'."""
    if settings.database_url:
        pytest.skip("builds a SQLite v0.2 database")
    settings.ensure_dirs()
    old = v02_metadata()
    eng = create_engine(settings.db_url)
    old.metadata.create_all(eng)
    pkg = make_tiny_model(tmp_path, 7, "moth-50m-v0.1-step5000")
    stored = settings.storage_dir / "models" / "v00001"
    shutil.copytree(pkg, stored)
    manifest = json.loads((pkg / "manifest.json").read_text())
    with eng.begin() as c:
        c.execute(text("CREATE TABLE schema_version (version INTEGER NOT NULL)"))
        c.execute(text("INSERT INTO schema_version VALUES (1)"))
        c.execute(old.model_releases.insert().values(
            version=1, name="moth-50m-v0.1-step5000", channel="stable", status="rejected", sha256=manifest["sha256"],
            size=(stored / "model.pt").stat().st_size, path=str(stored),
            info=json.dumps({"architecture": "moth-decoder-v1", "params": manifest["params"],
                             "tokenizer_fingerprint": manifest["tokenizer_fingerprint"], "source": {"type": "upload"}}),
            evaluation=json.dumps({"ts": 1, "checks": {"loads_and_checksum": True, "generates": True},
                                   "error": LEGACY_ERROR, "passed": False}), created_at=1.0))
    eng.dispose()
    with TestClient(create_app(settings, extras=SYNC)) as client:
        ctx = client.app.state.ctx
        from moth_server.db import SCHEMA_VERSION

        assert ctx.db.schema_version() == SCHEMA_VERSION
        rel = M.release(ctx, 1)
        assert rel["status"] == "failed"  # v0.2 'rejected' migrated, record preserved
        assert rel["path"] == str(stored) and rel["sha256"] == manifest["sha256"]
        o = login_owner(client, settings, monkeypatch)
        listing = client.get("/v1/admin/models", headers=o).json()
        assert listing["eval_ready"] and any(d["source"] == "builtin" and d["valid"] for d in listing["eval_datasets"])
        # the pipeline (runs every two minutes on a server) re-evaluates it automatically
        assert M.retry_candidates(ctx) == [1]
        result = M.auto_pipeline(ctx)
        assert result["evaluated"] == [1] and result["passed"] == [1]
        rel = M.release(ctx, 1)
        assert rel["status"] == "published" and rel["evaluation"]["passed"]
        assert rel["evaluation"]["dataset"]["source"] == "builtin"
        assert rel["evaluation"]["score"]["metric"] == "bits_per_byte" and rel["evaluation"]["score"]["value"] > 0
        assert rel["path"] == str(stored)  # same verified files, no re-upload
        assert client.post("/v1/admin/models/1/deploy", headers=o).json()["status"] == "deployed"


# ---- missing evaluation data: clear error, Owner upload, automatic continuation ----------------------
def test_missing_eval_data_guided_recovery(client, settings, owner, tmp_path, monkeypatch):
    ctx = client.app.state.ctx
    o = H(owner["token"])
    monkeypatch.setattr(E, "builtin", lambda ctx: None)  # a server without the Python stdlib sample
    files = {"file": ("m.tar.gz", tar_bytes(make_tiny_model(tmp_path, 11)), "application/gzip")}
    v = client.post("/v1/admin/models/upload", data={"name": "needs-data"}, files=files, headers=o).json()["version"]
    rel = M.release(ctx, v)
    assert rel["status"] == "failed" and rel["evaluation"]["reason"] == "no_eval_dataset"
    assert "Evaluation data" in rel["error"] and "automatically" in rel["error"]
    assert client.get("/v1/admin/models", headers=o).json()["eval_ready"] is False
    assert client.post(f"/v1/admin/models/{v}/deploy", headers=o).status_code == 409  # never deploy untested

    def add(data: bytes, **form):
        return client.post("/v1/admin/eval-datasets", data={"name": "held-out", **form},
                           files={"file": ("eval.txt", data, "text/plain")}, headers=o)

    # invalid datasets are rejected with specific reasons
    assert "too short" in add(b"def x(): pass\n").json()["detail"]
    assert "binary" in add(b"\x00" * 8192).json()["detail"]
    assert "not valid UTF-8" in add(b"\xff\xfe" + b"a" * 8192).json()["detail"]
    assert "tokenizer fingerprint" in add(b"\x00" * 16384, kind="tokens").json()["detail"]
    assert "multiple of 4" in add(b"\x01" * 16385, kind="tokens", tokenizer_fingerprint="ab" * 8).json()["detail"]
    # a valid held-out text dataset: the waiting release continues automatically (no re-upload)
    r = add(held_out_text(), license="CC0-1.0")
    assert r.status_code == 200, r.text
    assert r.json()["kind"] == "text" and r.json()["valid"]
    rel = M.release(ctx, v)
    assert rel["status"] == "published", rel["error"]
    assert rel["evaluation"]["dataset"]["source"] == "uploaded"
    assert rel["evaluation"]["attempts"] == 2
    assert "already uploaded" in add(held_out_text()).json()["detail"]  # duplicate dataset
    # owner can pin and remove datasets; tampered files are reported invalid
    did = r.json()["id"]
    pinned = client.put("/v1/admin/eval-datasets/pinned", json={"id": did}, headers=o).json()
    assert [d["id"] for d in pinned if d["pinned"]] == [did]
    (E.root(ctx) / did / "text.txt").write_text("tampered " * 1000)
    bad = next(d for d in client.get("/v1/admin/eval-datasets", headers=o).json() if d["id"] == did)
    assert bad["valid"] is False and "checksum" in bad["problems"][0]
    assert client.delete(f"/v1/admin/eval-datasets/{did}", headers=o).status_code == 200


def test_token_datasets_require_matching_tokenizer(client, settings, owner, tmp_path):
    ctx = client.app.state.ctx
    o = H(owner["token"])
    pkg = make_tiny_model(tmp_path, 12)
    from moth.model.tokenizer import Tokenizer

    tok = Tokenizer.load(pkg / "tokenizer.json")
    import numpy as np

    ids = np.array(tok.encode(held_out_text().decode()) * 3, dtype=np.uint32)
    r = client.post("/v1/admin/eval-datasets", data={"name": "tokens", "kind": "tokens",
                                                     "tokenizer_fingerprint": "0" * 16},
                    files={"file": ("t.bin", ids.tobytes(), "application/octet-stream")}, headers=o)
    assert r.status_code == 200, r.text
    client.put("/v1/admin/eval-datasets/pinned", json={"id": r.json()["id"]}, headers=o)
    chosen, skipped = E.select_for(ctx, tok.fingerprint())
    assert chosen["source"] == "builtin"  # pinned token set is skipped: different tokenizer
    assert "different tokenizer" in skipped[0]["reason"]
    r2 = client.post("/v1/admin/eval-datasets", data={"name": "tokens-ok", "kind": "tokens",
                                                      "tokenizer_fingerprint": tok.fingerprint()},
                     files={"file": ("t.bin", ids.tobytes() + b"\x00\x00\x00\x00", "application/octet-stream")},
                     headers=o)
    client.put("/v1/admin/eval-datasets/pinned", json={"id": r2.json()["id"]}, headers=o)
    assert E.select_for(ctx, tok.fingerprint())[0]["id"] == r2.json()["id"]
    files = {"file": ("m.tar.gz", tar_bytes(pkg), "application/gzip")}
    v = client.post("/v1/admin/models/upload", data={"name": "tok"}, files=files, headers=o).json()["version"]
    ev = M.release(ctx, v)["evaluation"]
    assert ev["passed"] and ev["score"]["metric"] == "token_loss"


# ---- resumable chunked upload ------------------------------------------------------------------------------
def test_chunked_upload_resumes_after_interruption(client, settings, owner, tmp_path):
    ctx = client.app.state.ctx
    o = H(owner["token"])
    pkg = make_tiny_model(tmp_path, 21, "chunked")
    data = tar_bytes(pkg, gz=False)
    sha = hashlib.sha256(data).hexdigest()
    manifest = json.loads((pkg / "manifest.json").read_text())
    start = {"name": "chunked", "size": len(data), "sha256": sha, "manifest": manifest, "chunk_size": 256 * 1024}
    bad = client.post("/v1/admin/models/uploads", json={**start, "manifest": {**manifest, "architecture": "gpt"}},
                      headers=o)
    assert bad.status_code == 422 and "only MOTH models" in bad.json()["detail"]
    up = client.post("/v1/admin/models/uploads", json=start, headers=o).json()["upload"]
    n, cs = up["chunks"], up["chunk_size"]
    assert n >= 3
    version = up and M.release(ctx, client.get(f"/v1/admin/models/uploads/{up['id']}", headers=o)
                                .json()["release_version"])["version"]
    assert M.release(ctx, version)["status"] == "uploading"

    def send(i, body=None):
        chunk = data[i * cs:(i + 1) * cs]
        return client.put(f"/v1/admin/models/uploads/{up['id']}/chunks/{i}", content=body or chunk,
                          headers={**o, "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest()})

    assert send(0).status_code == 200
    assert send(1, body=b"corrupted" * 10).status_code == 422  # damaged in transit → resend
    # interruption: the client stops; completing now reports what is missing
    r = client.post(f"/v1/admin/models/uploads/{up['id']}/complete", headers=o)
    assert r.status_code == 409 and "missing" in r.json()["detail"]
    # restarting the same upload resumes it
    again = client.post("/v1/admin/models/uploads", json=start, headers=o).json()
    assert again["resumed"] and again["upload"]["id"] == up["id"] and again["upload"]["received"] == [0]
    for i in again["upload"]["missing"]:
        assert send(i).status_code == 200
    assert send(0).status_code == 200  # re-sending a chunk is harmless
    done = client.post(f"/v1/admin/models/uploads/{up['id']}/complete", headers=o)
    assert done.status_code == 200, done.text
    rel = M.release(ctx, done.json()["release"]["version"])
    assert rel["version"] == version and rel["status"] == "published" and rel["evaluation"]["passed"]
    assert not (settings.storage_dir / "uploads" / up["id"]).exists()  # temporary chunks cleaned up
    # the same weights again are recognised before any upload
    dup = client.post("/v1/admin/models/uploads", json={**start, "sha256": "f" * 64}, headers=o).json()
    assert dup["duplicate"] and dup["release"]["version"] == version


def test_stale_uploads_expire_and_interrupted_work_recovers(client, settings, owner, tmp_path):
    from moth_server.routes import uploads as U

    ctx = client.app.state.ctx
    o = H(owner["token"])
    pkg = make_tiny_model(tmp_path, 31, "stale")
    data = tar_bytes(pkg, gz=False)
    start = {"name": "stale", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
             "manifest": json.loads((pkg / "manifest.json").read_text())}
    up = client.post("/v1/admin/models/uploads", json=start, headers=o).json()["upload"]
    assert U.expire_stale(ctx, max_age=-1) == [up["id"]]
    rel = M.release(ctx, up["release_version"])
    assert rel["status"] == "failed" and "expired" in rel["error"]
    # a server restart in the middle of evaluation/deployment never leaves a release stuck
    with ctx.db.tx() as c:
        c.execute(model_releases.update().where(model_releases.c.version == rel["version"])
                  .values(status="evaluating", path=str(pkg)))
    assert M.recover_interrupted(ctx) == [rel["version"]]
    r = M.release(ctx, rel["version"])
    assert r["status"] == "failed" and r["evaluation"]["reason"] == "interrupted"
    assert rel["version"] in M.retry_candidates(ctx)
    # explicit retry from the dashboard works without re-uploading
    assert client.post(f"/v1/admin/models/{rel['version']}/evaluate?wait=true", headers=o).json()["status"] == "published"
    assert select is not None


def test_upload_completion_survives_a_transient_server_error(client, settings, owner, tmp_path, monkeypatch):
    """Found in live testing: a server-side error while completing must not destroy the upload."""
    ctx = client.app.state.ctx
    o = H(owner["token"])
    pkg = make_tiny_model(tmp_path, 51, "transient")
    data = tar_bytes(pkg, gz=False)
    start = {"name": "transient", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
             "manifest": json.loads((pkg / "manifest.json").read_text())}
    up = client.post("/v1/admin/models/uploads", json=start, headers=o).json()["upload"]
    cs = up["chunk_size"]
    for i in range(up["chunks"]):
        chunk = data[i * cs:(i + 1) * cs]
        client.put(f"/v1/admin/models/uploads/{up['id']}/chunks/{i}", content=chunk,
                   headers={**o, "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest()})
    real = M.register_upload
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ModuleNotFoundError("No module named 'moth'")
        return real(*a, **kw)

    monkeypatch.setattr(M, "register_upload", flaky)
    r = client.post(f"/v1/admin/models/uploads/{up['id']}/complete", headers=o)
    assert r.status_code == 503 and "retried" in r.json()["detail"]
    assert "retried automatically" in M.release(ctx, up["release_version"])["error"]
    r = client.post(f"/v1/admin/models/uploads/{up['id']}/complete", headers=o)
    assert r.status_code == 200, r.text
    assert M.release(ctx, up["release_version"])["status"] == "published"
