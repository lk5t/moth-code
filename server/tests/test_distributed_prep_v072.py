"""0.7.2: workers tokenize dataset chunks; MOTH Cloud verifies, steals work and merges identically."""
import json
import threading
from pathlib import Path

import numpy as np
import pytest

from conftest import H, register_verified
from moth.datafactory import build as F
from moth.model.tokenizer import Tokenizer, train_bpe
from moth_server.db import training_jobs
from moth_server.intelligence import distributed_prep as DP


def _build(tmp_path: Path, n: int = 90) -> tuple[Path, Tokenizer, Path]:
    b = tmp_path / "build"
    (b / "domains").mkdir(parents=True)
    (b / "eval").mkdir()
    texts = [f"def f{i}(x):\n    return x * {i} + {i % 7}\n" for i in range(n)]
    texts += texts[:5]  # exact duplicates
    with open(b / "domains" / "code.jsonl", "w") as f:
        for t in texts:
            f.write(json.dumps({"text": t}) + "\n")
    with open(b / "eval" / "holdout_code.jsonl", "w") as f:
        for i in range(10):
            f.write(json.dumps({"text": f"def g{i}(y):\n    return y - {i}\n"}) + "\n")
    (b / "manifest.json").write_text(json.dumps({"content_sha256": "x" * 64, "sources": [
        {"id": "psf", "domain": "code", "license": "PSF-2.0"}]}))
    tok = train_bpe(iter(texts * 3), 300)
    tp = tmp_path / "tokenizer.json"
    tok.save(tp)
    return b, Tokenizer.load(tp), tp


def _worker(client, settings, tmp_path, name="prep"):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    user = register_verified(client, settings, name)["token"]
    e = client.post("/v1/training/enrollments", json={"name": name}, headers=H(user)).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": []}, "version": "0.7.2"}).json()
    r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / name, allow_cpu=True,
                     log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None)
    r.beat()
    return r, w


def test_workers_prepare_chunks_and_merge_is_identical(client, settings, owner, tmp_path, monkeypatch):
    ctx = client.app.state.ctx
    monkeypatch.setattr(DP, "CHUNK_RECORDS", 20)
    b, tok, tp = _build(tmp_path)
    runner, w = _worker(client, settings, tmp_path)
    done = []

    def work():  # the worker claims and prepares chunks while MOTH Cloud waits
        import time
        deadline = time.time() + 60
        while time.time() < deadline and len(done) < 3:
            job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"]))
            if job.status_code == 200:
                done.append(runner.run_job(job.json()))
            else:
                time.sleep(0.05)

    t = threading.Thread(target=work)
    t.start()
    chunks = DP.prepare(ctx, 1, b, tok, tp, lambda m: None, wait_seconds=60, poll=0.2, head_start=20)
    t.join()
    assert chunks and len(chunks["code"]) == 5  # 95 records in chunks of 20
    assert done and all(r.get("accepted") for r in done)  # the worker's chunks passed verification
    jobs = ctx.db.all(training_jobs.select().where(training_jobs.c.kind == "prep_tokenize"))
    assert sum(j["status"] == "completed" for j in jobs) == len(done)
    assert sum(j["status"] == "cancelled" for j in jobs) == 5 - len(done)  # the rest: MOTH Cloud (work stealing)
    # merged with deduplication — byte-identical to preparing everything on MOTH Cloud
    a = F.tokenize_build(b, tok, tp, out=tmp_path / "dist", log=lambda m: None, train_chunks=chunks)
    s = F.tokenize_build(b, tok, tp, out=tmp_path / "local", log=lambda m: None)
    for f in ("train.bin", "train.mask", "val.bin", "val.mask"):
        assert (tmp_path / "dist" / "code" / f).read_bytes() == (tmp_path / "local" / "code" / f).read_bytes()
    assert a["domains"]["code"]["duplicates_removed"] == s["domains"]["code"]["duplicates_removed"] == 5
    assert a["domains"]["code"]["prepared_by"] == "workers"


def test_wrong_tokenization_is_refused(tmp_path):
    b, tok, tp = _build(tmp_path, 30)
    chunk = F.split_records(b / "domains" / "code.jsonl", tmp_path / "c", 40)[0]
    good = F.encode_chunk(tok, chunk)
    assert DP.verify(tok, chunk, good) == []
    bad = {**good, "ids": good["ids"].copy()}
    bad["ids"][int(good["offsets"][1]) - 2] ^= 1  # one token altered in the first record
    assert DP.verify(tok, chunk, bad) == ["record 0 was not tokenized correctly"]
    short = {**good, "offsets": good["offsets"][:-1]}
    assert DP.verify(tok, chunk, short) == ["the result does not match the chunk's records"]
    forged = {**good, "hashes": np.zeros_like(good["hashes"])}
    assert DP.verify(tok, chunk, forged)  # a forged hash could hide or duplicate records


def test_no_workers_or_private_data_stays_on_cloud(client, tmp_path):
    ctx = client.app.state.ctx
    b, tok, tp = _build(tmp_path)
    assert DP.prepare(ctx, 1, b, tok, tp, lambda m: None) is None  # nobody online: prepared here as before
    assert DP.public_domains({"sources": [{"id": "feedback", "domain": "conversation", "license": "user-consented"},
                                          {"id": "psf", "domain": "code", "license": "PSF-2.0"}]}) == {"code"}
