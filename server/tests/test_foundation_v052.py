"""0.5.2 FOUNDATION: signed official model releases, import with re-verification, automatic deployment
after evaluation, MOTH model identity, and the package download MOTH Code uses for on-computer inference."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import torch

from conftest import H, register_verified
from moth_server import models as M
from test_updates import signed  # noqa: F401  (fixture)

ROOT = Path(__file__).resolve().parents[2]


def official_package(tmp_path, version="0.1", seed=0):
    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import Tokenizer, train_bpe
    from moth.model.transformer import MothModel

    tok_path = tmp_path / "tok.json"
    if not tok_path.exists():
        train_bpe(["def add(a, b):\n    return a + b\n"] * 20, vocab_size=300).save(tok_path)
    tok = Tokenizer.load(tok_path)
    torch.manual_seed(seed)
    cfg = preset("moth-tiny", vocab_size=320)
    ck = tmp_path / f"ck{seed}.pt"
    torch.save({"model": MothModel(cfg).state_dict(), "model_config": cfg.to_dict(), "tokenizer_path": str(tok_path),
                "tokenizer_fingerprint": tok.fingerprint(), "step": 1}, ck)
    info = export_model(ck, tmp_path / "pkgs", f"moth-{version}-{seed}", dtype="float32",
                        extra={"model_version": version, "display_name": f"MOTH {version} — Foundation",
                               "family": "MOTH", "lineage_id": "moth-test", "method": "foundation"})
    return Path(info["path"])


def build_release(tmp_path, key, pkg, version="0.1", passed=True):
    ev = tmp_path / f"ev-{version}.json"
    ev.write_text(json.dumps({"criteria": {"passed": passed, "criteria": []}}))
    out = tmp_path / f"dist-{version}"
    env = {**os.environ, "MOTH_RELEASE_SIGNING_KEY": key.private_b64}
    return subprocess.run([sys.executable, str(ROOT / "scripts/build-model-release.py"), "--package", str(pkg),
                           "--evaluation", str(ev), "--version", version, "--out", str(out)],
                          capture_output=True, text=True, env=env), out


def agent_import(client, s, out, version="0.1"):
    raw = (out / f"moth-release-model-{version}.json").read_bytes()
    sig = (out / f"moth-release-model-{version}.json.sig").read_text().strip()
    incoming = s["ctx"].settings.releases_dir / "incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    dst = incoming / f"moth-model-{version}.tar.gz"
    dst.write_bytes((out / f"moth-model-{version}.tar.gz").read_bytes())
    return client.post("/v1/agent/models", json={"manifest": base64.b64encode(raw).decode(), "signature": sig,
                                                  "path": str(dst)}, headers=s["agent"])


def test_release_needs_passed_criteria_and_verifies(tmp_path, signed):
    s = signed
    pkg = official_package(tmp_path)
    r, _ = build_release(tmp_path, s["key"], pkg, passed=False)
    assert r.returncode != 0 and "release criteria" in r.stderr  # a failing model is never published
    r, out = build_release(tmp_path, s["key"], pkg)
    assert r.returncode == 0, r.stderr
    pub = tmp_path / "pub"
    pub.write_text(s["key"].public_b64)
    v = subprocess.run([sys.executable, str(ROOT / "scripts/verify-release.py"), str(out), "--pubkey-file", str(pub)],
                       capture_output=True, text=True)
    assert v.returncode == 0 and "weights match the package manifest" in v.stdout, v.stdout


def test_signed_model_import_evaluate_deploy_and_download(client, settings, signed, tmp_path):
    s = signed
    ctx = s["ctx"]
    pkg = official_package(tmp_path)
    r, out = build_release(tmp_path, s["key"], pkg)
    assert r.returncode == 0, r.stderr
    # a tampered archive is refused (its SHA-256 no longer matches the signed manifest)
    good = (out / "moth-model-0.1.tar.gz").read_bytes()
    (out / "moth-model-0.1.tar.gz").write_bytes(good[:-10] + b"0" * 10)
    bad = agent_import(client, s, out)
    assert bad.status_code == 422 and "SHA-256" in bad.text
    (out / "moth-model-0.1.tar.gz").write_bytes(good)
    # a wrong signature is refused
    raw = (out / "moth-release-model-0.1.json").read_bytes()
    incoming = ctx.settings.releases_dir / "incoming"
    (incoming / "x.tar.gz").write_bytes(good)
    r2 = client.post("/v1/agent/models", json={"manifest": base64.b64encode(raw).decode(),
                                                "signature": s["key"].sign(b"something else"),
                                                "path": str(incoming / "x.tar.gz")}, headers=s["agent"])
    assert r2.status_code == 422
    ok = agent_import(client, s, out)
    assert ok.status_code == 200, ok.text
    v = ok.json()["version"]
    rel = M.release(ctx, v)
    assert rel["info"]["model_version"] == "0.1" and rel["name"] == "MOTH 0.1 — Foundation"
    assert (agent_import(client, s, out).json()["version"]) == v  # imported once, never twice
    # it was evaluated and, having passed, deployed automatically (auto_deploy_official_models)
    assert M.release(ctx, v)["status"] == "deployed" and ctx.extras["deployed_version"] == v
    from moth_server.evolution import memory as MEM

    assert MEM.lineage(ctx)[-1]["method"] == "foundation"
    # MOTH Code downloads the deployed model to run it on the computer, verifiably
    t = register_verified(client, settings, "localuser")["token"]
    info = client.get("/v1/models/deployed/package-info", headers=H(t)).json()
    assert info["model_version"] == "0.1" and info["release_manifest"] and info["release_signature"]
    from moth_server.ed25519_verify import verify_b64

    assert verify_b64(s["key"].public_b64, base64.b64decode(info["release_manifest"]), info["release_signature"])
    dl = client.get("/v1/models/deployed/package", headers=H(t))
    assert dl.status_code == 200 and hashlib.sha256(dl.content).hexdigest() == info["package_sha256"]
    assert client.get("/v1/models/deployed/package-info").status_code == 401


def test_moth_code_downloads_and_runs_the_deployed_model(client, settings, signed, tmp_path):
    """MOTH Code's on-computer mode: the signed release verifies with the release key, the package matches
    its SHA-256, the model loads and generates locally; a wrong key is refused; nothing downloads twice."""
    from moth.inference.ondevice import OnDevice, OnDeviceError
    from moth.model.chat_format import Message
    from moth.model.generation import GenerationParams

    s = signed
    r, out = build_release(tmp_path, s["key"], official_package(tmp_path))
    assert r.returncode == 0 and agent_import(client, s, out).status_code == 200
    t = register_verified(client, settings, "offline")["token"]

    class Http:  # the TestClient, kept open across downloads
        def __enter__(self):
            return client

        def __exit__(self, *a):
            return False

    acct = lambda: {"server_url": "http://testserver", "token": t}  # noqa: E731
    events = []
    wrong = OnDevice(tmp_path / "m1", acct, lambda k, e: events.append(e), http_factory=Http,
                     pubkey="JMITaZ0m8unDwq44iP45h7i7kjbZmgTg8izA3KNk+jQ=")  # the real MOTH key: test key differs
    with pytest.raises(OnDeviceError, match="signature"):
        wrong.download()
    od = OnDevice(tmp_path / "m2", acct, lambda k, e: events.append(e), http_factory=Http, pubkey=s["key"].public_b64)
    inst = od.download()
    assert inst["official"] and inst["model_version"] == "0.1" and od.installed()["dir"] == inst["dir"]
    eng = od.ensure_loaded()
    out_text = []
    st = eng.chat([Message("user", "hello")], GenerationParams(max_new_tokens=4, temperature=0), out_text.append)
    assert st.generated_tokens >= 1  # generated on this computer
    assert od.download()["installed_at"] == inst["installed_at"]  # already installed: not downloaded again
    od.remove()
    assert od.installed() is None
