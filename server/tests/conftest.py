import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "backend")]

from moth_server.app import create_app  # noqa: E402
from moth_server.config import Settings  # noqa: E402
from moth_server.db import Database  # noqa: E402


@pytest.fixture(autouse=True)
def _close_database_pools():
    yield
    Database.dispose_all()

PASSWORD = "correct horse battery"


@pytest.fixture
def settings(tmp_path):
    """SQLite by default; set MOTH_TEST_DATABASE_URL (e.g. postgresql+psycopg://…) to run against PostgreSQL."""
    import os

    url = os.environ.get("MOTH_TEST_DATABASE_URL", "")
    if url:
        from sqlalchemy import create_engine, text

        from moth_server.db import metadata

        eng = create_engine(url)
        metadata.drop_all(eng)
        with eng.begin() as c:
            c.execute(text("DROP TABLE IF EXISTS schema_version"))
        eng.dispose()
    return Settings(data_dir=tmp_path / "server-data", public_url="https://moth.test", database_url=url)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings, extras={"synchronous_jobs": True, "disable_background": True})) as c:
        yield c


def outbox(settings) -> list[str]:
    """Decoded email bodies (subject + text), oldest first."""
    from email import message_from_bytes, policy

    out = []
    for p in sorted(settings.outbox_dir.glob("*.eml")):
        msg = message_from_bytes(p.read_bytes(), policy=policy.default)
        out.append(f"Subject: {msg['Subject']}\nTo: {msg['To']}\n\n{msg.get_content()}")
    return out


def last_token(settings, kind: str) -> str:
    for msg in reversed(outbox(settings)):
        m = re.search(rf"/{kind}\?token=([A-Za-z0-9_\-]+)", msg)
        if m:
            return m.group(1)
    raise AssertionError(f"no {kind} email")


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def register_verified(client, settings, username="alice", email=None, password=PASSWORD, referral_code=None) -> dict:
    email = email or f"{username}@example.com"
    r = client.post("/v1/auth/register", json={"username": username, "email": email, "password": password,
                                               "referral_code": referral_code})
    assert r.status_code == 202, r.text
    assert client.post("/v1/auth/verify-email", json={"token": last_token(settings, "verify")}).status_code == 200
    r = client.post("/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def owner(client, settings, monkeypatch):
    """Create the LK5T owner through the real one-time CLI path and sign in."""
    import io

    from moth_server import cli

    monkeypatch.setenv("MOTH_SERVER_DATA_DIR", str(settings.data_dir))
    if settings.database_url:
        monkeypatch.setenv("MOTH_SERVER_DATABASE_URL", settings.database_url)
    monkeypatch.setattr(sys, "stdin", io.StringIO("crimson wings 2026!\n"))
    assert cli.main(["init-owner", "--email", "owner@moth.test", "--password-stdin"]) == 0
    r = client.post("/v1/auth/login", json={"username": "lk5t", "password": "crimson wings 2026!"})
    assert r.status_code == 200, r.text
    return r.json()


def sign_webhook(payload: bytes, secret: str, ts: int | None = None) -> str:
    import hashlib
    import hmac
    import time

    ts = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def make_tiny_model(tmp_path, seed: int = 0, name: str = "moth-cloud-test"):
    """An exported (untrained) moth-tiny model: real MOTH weights, created locally. Different seeds
    give different weights (distinct releases)."""
    import torch

    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import train_bpe
    from moth.model.transformer import MothModel

    tok_path = tmp_path / "tok.json"
    if not tok_path.exists():
        train_bpe(["def add(a, b):\n    return a + b\n"] * 20, vocab_size=300).save(tok_path)
    from moth.model.tokenizer import Tokenizer

    tok = Tokenizer.load(tok_path)
    torch.manual_seed(seed)
    cfg = preset("moth-tiny", vocab_size=320)
    model = MothModel(cfg)
    ckpt = tmp_path / f"ck-{seed}.pt"
    torch.save({"model": model.state_dict(), "model_config": cfg.to_dict(), "tokenizer_path": str(tok_path),
                "tokenizer_fingerprint": tok.fingerprint(), "step": 1}, ckpt)
    info = export_model(ckpt, tmp_path / "models", name if seed == 0 else f"{name}-{seed}", dtype="float32")
    return tmp_path / "models" / info["id"]


@pytest.fixture
def tiny_model_dir(tmp_path):
    return make_tiny_model(tmp_path)
sys.path.insert(0, str(ROOT / "worker"))


@pytest.fixture
def training_world(client, settings, owner, tmp_path):
    """Initialised coordinator (tiny real model + licensed synthetic dataset) and CPU workers allowed."""
    import torch

    from moth.community.coordinator import init_coordinator
    from moth.community.protocol import TrainSpec
    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import train_bpe
    from moth.model.transformer import MothModel
    from moth.training.data import prepare_dataset

    corpus = tmp_path / "corpus"
    corpus.mkdir()
    for i in range(30):
        (corpus / f"f{i}.py").write_text("def add(a, b):\n    return a + b\n\nclass Point:\n    x = 1\n" * (1 + i % 3))
    src = {"spec": f"dir:{corpus}", "license": "MIT"}
    tok = train_bpe([(corpus / f"f{i}.py").read_text() for i in range(30)], vocab_size=300)
    tok.save(tmp_path / "tok.json")
    prepare_dataset([src], tok, tmp_path / "tok.json", tmp_path / "ds", val_fraction=0.1)
    torch.manual_seed(0)
    cfg = preset("moth-tiny", vocab_size=320)
    torch.save({"model": MothModel(cfg).state_dict(), "model_config": cfg.to_dict(), "tokenizer_path": str(tmp_path / "tok.json"),
                "tokenizer_fingerprint": tok.fingerprint(), "step": 0}, tmp_path / "base.pt")
    info = export_model(tmp_path / "base.pt", tmp_path / "models", "moth-base", dtype="float32")
    init_coordinator(settings.data_dir / "coordinator", Path(info["path"]), tmp_path / "ds", shards=4,
                     train=TrainSpec(steps=6, lr=1e-3, batch_size=4, seq_len=32), min_contributions=2)
    client.put("/v1/admin/config/flags", json={"allow_cpu_workers": True}, headers=H(owner["token"]))
    return {"owner": owner, "base_model": Path(info["path"]), "tokenizer": tmp_path / "tok.json", "dataset": tmp_path / "ds"}
