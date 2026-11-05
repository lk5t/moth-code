"""Integration: Owner tools train, export and evaluate a model entirely through the HTTP API."""

import time

from fastapi.testclient import TestClient

from moth.server.app import create_app

H = {"Authorization": "Bearer t"}


def wait_job(c, job_id, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = next(j for j in c.get("/api/jobs", headers=H).json() if j["id"] == job_id)
        if job["status"] != "running":
            assert job["status"] == "completed", job
            return job
        time.sleep(0.3)
    raise TimeoutError(job_id)


def test_full_training_flow_and_chat(paths, corpus_dir):
    with TestClient(create_app(paths, token="t")) as c:
        assert c.get("/api/subsystems", headers=H).json()["moth.server.routes_training"]["ok"]
        src = [{"spec": f"dir:{corpus_dir}", "license": "MIT"}]
        # license is mandatory
        r = c.post("/api/tokenizers", json={"name": "tok", "sources": [{"spec": f"dir:{corpus_dir}"}]}, headers=H)
        assert r.status_code == 422

        job = c.post("/api/tokenizers", json={"name": "tok", "sources": src, "vocab_size": 400}, headers=H).json()
        wait_job(c, job["id"])
        assert c.get("/api/tokenizers", headers=H).json()[0]["vocab_size"] <= 400

        job = c.post("/api/datasets", json={"name": "ds", "tokenizer": "tok", "sources": src}, headers=H).json()
        wait_job(c, job["id"])
        assert c.get("/api/datasets", headers=H).json()[0]["tokens"]["train"] > 0

        run = c.post("/api/training/runs", json={"name": "api-run", "dataset": "ds", "preset": "moth-tiny", "config": {
            "seq_len": 64, "batch_size": 8, "grad_accum": 1, "max_steps": 40, "lr": 3e-3, "warmup_steps": 4,
            "eval_interval": 10, "eval_iters": 2, "log_interval": 5, "device": "cpu"}}, headers=H).json()
        # a second concurrent run is refused
        assert c.post("/api/training/runs", json={"name": "x", "dataset": "ds", "preset": "moth-tiny"},
                      headers=H).status_code == 409
        assert len(c.get("/api/training/runs", headers=H).json()) == 1  # refused run left nothing behind
        deadline = time.time() + 300
        while time.time() < deadline:
            runs = c.get("/api/training/runs", headers=H).json()
            if runs[0]["status"] not in ("running", "created"):
                break
            time.sleep(0.3)
        assert runs[0]["status"] == "completed", runs[0]
        metrics = c.get(f"/api/training/runs/{run['id']}/metrics", headers=H).json()
        train = [m["loss"] for m in metrics if m["split"] == "train"]
        assert train[-1] < train[0]

        info = c.post(f"/api/training/runs/{run['id']}/export", json={"name": "moth-api"}, headers=H).json()
        assert info["id"] == "moth-api"
        assert c.get("/api/models", headers=H).json()[0]["id"] == "moth-api"
        # evaluation job produces real measured numbers
        job = c.post("/api/models/moth-api/evaluate", json={"dataset": "ds"}, headers=H).json()
        wait_job(c, job["id"])
        ev = c.get("/api/models/moth-api/evaluation", headers=H).json()
        assert ev["val_loss"] > 0 and ev["code_total"] > 0
