"""Graceful handling of unavailable hardware and bad inputs."""

import pytest
import torch
from fastapi.testclient import TestClient

from moth.server.app import create_app, hardware_info
from moth.training.trainer import pick_device

H = {"Authorization": "Bearer t"}


def test_device_selection_falls_back_to_cpu(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    assert pick_device("auto") == "cpu"
    with pytest.raises(RuntimeError, match="no working CUDA device"):
        pick_device("cuda")


def test_broken_cuda_driver_falls_back(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)

    def broken(*a, **k):
        raise RuntimeError("CUDA driver version is insufficient")

    monkeypatch.setattr(torch, "zeros", broken)
    assert pick_device("auto") == "cpu"


def test_hardware_info_never_raises(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: (_ for _ in ()).throw(RuntimeError("driver crash")))
    info = hardware_info()
    assert info["cuda"] is False and "torch_error" in info


def test_loading_missing_or_corrupt_model_is_reported(paths):
    with TestClient(create_app(paths, token="t")) as c:
        assert c.post("/api/models/load", json={"id": "nope"}, headers=H).status_code in (400, 404)
        d = paths.models / "broken"
        d.mkdir()
        (d / "manifest.json").write_text("{not json")
        r = c.post("/api/models/load", json={"id": "broken"}, headers=H)
        assert r.status_code == 400 and "could not load model" in r.json()["detail"]
        assert c.get("/api/models", headers=H).json() == []  # corrupt entries are skipped, not fatal


def test_training_failure_is_recorded_not_crashing(paths, tiny_pipeline):
    """A run with an impossible configuration fails cleanly with its error recorded."""
    import shutil
    import time

    shutil.copytree(tiny_pipeline["dataset"], paths.datasets / "ds")
    with TestClient(create_app(paths, token="t")) as c:
        r = c.post("/api/training/runs", json={"name": "bad", "dataset": "ds", "preset": "moth-tiny",
                                               "config": {"seq_len": 100000, "device": "cpu"}}, headers=H)
        assert r.status_code == 200
        for _ in range(100):
            run = c.get("/api/training/runs", headers=H).json()[0]
            if run["status"] not in ("running", "created"):
                break
            time.sleep(0.3)
        assert run["status"] == "failed" and "exceeds the model context window" in run["error"]
        assert c.get("/api/health").status_code == 200


def test_unknown_subsystem_failure_is_isolated(paths, monkeypatch):
    from moth.server import extensions

    monkeypatch.setattr(extensions, "SUBSYSTEMS", [*extensions.SUBSYSTEMS, "moth.server.does_not_exist"])
    with TestClient(create_app(paths, token="t")) as c:
        status = c.get("/api/subsystems", headers=H).json()
        assert status["moth.server.does_not_exist"]["ok"] is False
        assert status["moth.server.routes_model"]["ok"] is True
