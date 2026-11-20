"""2.4: a worker pauses while a full-screen game or app runs (Windows), unless its owner turned that off;
MOTH Cloud keeps the GPU readings and the pause so Network can show them."""
from moth_worker import runner as R


class FakeClient:
    def __init__(self, limits):
        self.limits = limits

    def heartbeat(self, *a, **k):
        return {"paused": False, "revoked": False, "limits": self.limits}


def _runner(tmp_path, limits):
    r = R.WorkerRunner(FakeClient(limits), tmp_path, log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None)
    r.hardware = lambda: {}
    return r


def test_pauses_while_a_fullscreen_app_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "fullscreen_app_running", lambda: True)
    r = _runner(tmp_path / "a", {})
    r.beat()
    assert r.paused and r.gaming
    off = _runner(tmp_path / "b", {"pause_fullscreen": False})
    off.beat()
    assert not off.paused and not off.gaming


def test_no_fullscreen_check_outside_windows(monkeypatch):
    monkeypatch.setattr(R.os, "name", "posix")
    assert R.fullscreen_app_running() is False


def test_cloud_keeps_gpu_readings_and_the_pause():
    from moth_server.training import _clean_hw
    hw = _clean_hw({"compute": "gpu", "utilization": {"cpu": 0.2, "memory": 0.5, "gpu": 0.97, "gpu_memory": 0.6,
                                                     "gpu_temp_c": 71, "paused_for_fullscreen": True, "evil": "x"}})
    assert hw["utilization"] == {"cpu": 0.2, "memory": 0.5, "gpu": 0.97, "gpu_memory": 0.6, "gpu_temp_c": 71.0,
                                 "paused_for_fullscreen": True}
