"""0.7.1: MOTH Cloud announces a newer worker in the heartbeat; workers install it between jobs at once,
and a failed install backs off instead of retrying in a loop."""
import pytest

from conftest import H, register_verified
from release_helpers import TestKey, release, worker_bundle
from test_updates import NEWER, register, signed  # noqa: F401 — fixture


def _worker(client, s, tmp_path, check=900.0):
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    user = register_verified(client, s["ctx"].settings, "upd_friend")["token"]
    e = client.post("/v1/training/enrollments", json={"name": "w"}, headers=H(user)).json()
    w = client.post("/v1/worker/enroll", json={"token": e["token"], "hardware": {"gpus": []}}).json()
    r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / "wh", allow_cpu=True,
                     log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=check)
    return r, w


def test_heartbeat_announces_update_and_worker_installs_immediately(client, signed, tmp_path, monkeypatch):  # noqa: F811
    s = signed
    monkeypatch.setenv("MOTH_RELEASE_PUBKEY", s["key"].public_b64)
    r, w = _worker(client, s, tmp_path)
    r.beat()
    assert r.maybe_update() is False  # nothing newer yet; the next scheduled check is 15 minutes away
    assert r._next_update_check > __import__("time").time() + 800
    bundle = worker_bundle(tmp_path, NEWER)
    # default build rollout for workers (0.7.1): every worker at once
    raw, sig = release(tmp_path, s["key"], NEWER, worker=bundle, rollout={"worker": {"stages": [100]}})
    register(client, s, raw, sig, [("worker", bundle)])
    hb = client.post("/v1/worker/heartbeat", json={"version": "0.6.4"}, headers=H(w["worker_token"])).json()
    assert hb["update"] == NEWER
    r.beat()  # the announcement makes the next loop check now instead of in 15 minutes
    assert r.maybe_update() and r.updated_to == NEWER


def test_failed_install_backs_off_and_ignores_announcements(client, signed, tmp_path, monkeypatch):  # noqa: F811
    import time

    from moth_worker import updater

    s = signed
    monkeypatch.setenv("MOTH_RELEASE_PUBKEY", s["key"].public_b64)
    r, _ = _worker(client, s, tmp_path)
    bundle = worker_bundle(tmp_path, NEWER)
    raw, sig = release(tmp_path, s["key"], NEWER, worker=bundle, rollout={"worker": {"stages": [100]}})
    register(client, s, raw, sig, [("worker", bundle)])
    calls = []

    def broken(*a, **k):
        calls.append(1)
        raise updater.UpdateError("disk full")

    monkeypatch.setattr(updater, "apply", broken)
    r.beat()
    assert r.maybe_update() is False and len(calls) == 1
    assert r._update_retry_after >= time.time() + 290  # 5 minutes, then 10, 20 … at most 6 hours
    r.beat()  # still announced, but the backoff holds
    assert r.maybe_update() is False and len(calls) == 1
