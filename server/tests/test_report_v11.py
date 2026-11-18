"""1.1 Owner reports: candidates versus the live model, and the speed report."""
from types import SimpleNamespace

from conftest import H
from moth_server.evolution import report


def test_reports_are_owner_only_and_answer_with_no_history(client, owner):
    assert client.get("/v1/admin/evolution/candidates").status_code in (401, 403)
    c = client.get("/v1/admin/evolution/candidates", headers=H(owner["token"])).json()
    assert c["candidates"] == []
    s = client.get("/v1/admin/evolution/speed", headers=H(owner["token"])).json()
    assert s["experiments"] == [] and s["slowest"] is None


def test_speed_splits_wall_time(monkeypatch):
    exp = {"id": 4, "cycle_id": 1, "status": "rejected", "created_at": 110.0, "started_at": 130.0,
           "finished_at": 230.0, "metrics": {"training": {"step": 50}}}
    monkeypatch.setattr(report.MEM, "events", lambda ctx, n: [{"kind": "experiment.trained", "experiment_id": 4, "ts": 210.0}])
    monkeypatch.setattr(report.MEM, "experiments", lambda ctx, limit=200: [exp])
    monkeypatch.setattr(report.MEM, "cycle", lambda ctx, cid: {"started_at": 100.0})
    r = report.speed(SimpleNamespace())
    assert r["experiments"][0]["seconds"] == {"preparing": 10.0, "waiting": 20.0, "training": 80.0, "evaluating": 20.0}
    assert r["slowest"] == "training" and abs(sum(r["share"].values()) - 1) < 1e-3
