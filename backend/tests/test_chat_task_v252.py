"""2.5.2: one chat, like Claude — a request to act starts a task inside the conversation."""
import json

from fastapi.testclient import TestClient

from moth.server.app import create_app
from test_agent import ScriptedLLM, call

H = {"Authorization": "Bearer t"}


def test_chat_task_needs_sign_in_and_saves_nothing(paths, project):
    with TestClient(create_app(paths, token="t")) as c:
        pid = c.post("/api/projects", json={"path": str(project)}, headers=H).json()["id"]
        r = c.post("/api/chat/task", json={"goal": "add a README", "project_id": pid}, headers=H)
        assert r.status_code == 401
        assert c.get("/api/conversations", headers=H).json() == [] or all(
            not x.get("title", "").startswith("add a README") for x in c.get("/api/conversations", headers=H).json())


def test_chat_task_starts_a_task_and_records_it_in_the_conversation(paths, project, monkeypatch):
    app = create_app(paths, token="t")
    with TestClient(app) as c:
        router = app.state.services.extras["inference_router"]
        llm = ScriptedLLM([call("finish", summary="Nothing to change.")])
        monkeypatch.setattr(router, "agent_llm", lambda pid: llm)
        pid = c.post("/api/projects", json={"path": str(project)}, headers=H).json()["id"]
        r = c.post("/api/chat/task", json={"goal": "check the project builds", "project_id": pid}, headers=H)
        assert r.status_code == 200, r.text
        out = r.json()
        msgs = c.get(f"/api/conversations/{out['conversation_id']}/messages", headers=H).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert msgs[0]["content"] == "check the project builds"
        assert msgs[1]["meta"]["task_id"] == out["task"]["id"]
        import time
        for _ in range(100):  # one task at a time per workspace: let the first one finish
            if c.get(f"/api/tasks/{out['task']['id']}", headers=H).json()["status"] not in ("queued", "running"):
                break
            time.sleep(0.1)
        llm.outputs.append(call("finish", summary="Listed."))
        # a follow-up request goes into the same conversation
        r2 = c.post("/api/chat/task", json={"goal": "and list the files", "project_id": pid,
                                            "conversation_id": out["conversation_id"]}, headers=H).json()
        assert r2["conversation_id"] == out["conversation_id"]
        assert len(c.get(f"/api/conversations/{out['conversation_id']}/messages", headers=H).json()) == 4
        json.dumps(out)
