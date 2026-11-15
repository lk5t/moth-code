"""1.0.9: fixed remote actions for workers (restart, update, self-check, logs, clear cache): never shell."""
from conftest import H
from test_network_v063 import _enroll


def test_action_reaches_the_worker_and_its_result_comes_back(client, owner):
    w = _enroll(client, owner)
    wid = w["worker_id"]
    assert client.post(f"/v1/training/workers/{wid}/command", json={"action": "rm -rf /"},
                       headers=H(owner["token"])).status_code == 422  # only the fixed actions exist
    st = client.post(f"/v1/training/workers/{wid}/command", json={"action": "logs"}, headers=H(owner["token"])).json()
    assert st["pending"] and st["command"]["action"] == "logs"
    hb = client.post("/v1/worker/heartbeat", json={"version": "1.0.9"}, headers=H(w["worker_token"])).json()
    cid = hb["command"]["id"]
    assert hb["command"]["action"] == "logs"
    client.post("/v1/worker/command-result", json={"id": cid, "ok": True, "output": "hello"},
                headers=H(w["worker_token"]))
    st = client.get(f"/v1/training/workers/{wid}/command", headers=H(owner["token"])).json()
    assert not st["pending"] and st["result"]["output"] == "hello"
    hb = client.post("/v1/worker/heartbeat", json={"version": "1.0.9"}, headers=H(w["worker_token"])).json()
    assert "command" not in hb  # delivered once


def test_runner_reports_logs_and_selfcheck(tmp_path):
    from moth_worker.runner import WorkerRunner

    sent = []

    class C:
        def command_result(self, cid, ok, out):
            sent.append((cid, ok, out))

    r = WorkerRunner(C(), tmp_path, log=lambda m: None)
    r.log("hello from the worker")
    r.handle_command({"id": 1, "action": "logs"})
    r.handle_command({"id": 1, "action": "logs"})  # the same command is handled once
    r.handle_command({"id": 2, "action": "selfcheck"})
    r.handle_command({"id": 3, "action": "restart"})
    assert len(sent) == 3 and "hello from the worker" in sent[0][2] and "worker_version" in sent[1][2]
    assert r.restart_requested and r.stop_event.is_set()
