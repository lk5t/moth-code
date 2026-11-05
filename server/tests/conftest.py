import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "server"), str(ROOT / "backend")]

from moth_server.app import create_app  # noqa: E402
from moth_server.config import Settings  # noqa: E402

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
    with TestClient(create_app(settings)) as c:
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


@pytest.fixture
def tiny_model_dir(tmp_path):
    """An exported (untrained) moth-tiny model: real MOTH weights, created locally."""
    import torch

    from moth.model.config import preset
    from moth.model.registry import export_model
    from moth.model.tokenizer import train_bpe
    from moth.model.transformer import MothModel

    tok = train_bpe(["def add(a, b):\n    return a + b\n"] * 20, vocab_size=300)
    tok_path = tmp_path / "tok.json"
    tok.save(tok_path)
    torch.manual_seed(0)
    cfg = preset("moth-tiny", vocab_size=320)
    model = MothModel(cfg)
    ckpt = tmp_path / "ck.pt"
    torch.save({"model": model.state_dict(), "model_config": cfg.to_dict(), "tokenizer_path": str(tok_path),
                "tokenizer_fingerprint": tok.fingerprint(), "step": 1}, ckpt)
    info = export_model(ckpt, tmp_path / "models", "moth-cloud-test", dtype="float32")
    return tmp_path / "models" / info["id"]
