from fastapi.testclient import TestClient

from moth.server.app import create_app

H = {"Authorization": "Bearer t"}


def test_task_requires_sign_in(paths, project):
    with TestClient(create_app(paths, token="t")) as c:
        pid = c.post("/api/projects", json={"path": str(project)}, headers=H).json()["id"]
        r = c.post("/api/tasks", json={"project_id": pid, "goal": "do it"}, headers=H)
        assert r.status_code == 401 and "Sign in" in r.json()["detail"]


def test_memory_and_search_api(paths, project):
    with TestClient(create_app(paths, token="t")) as c:
        pid = c.post("/api/projects", json={"path": str(project)}, headers=H).json()["id"]
        mid = c.post("/api/memory", json={"project_id": pid, "kind": "preference", "title": "Style",
                                          "content": "Use type hints"}, headers=H).json()["id"]
        assert c.get(f"/api/memory?project_id={pid}", headers=H).json()[0]["id"] == mid
        assert c.post("/api/memory", json={"kind": "bogus", "title": "x", "content": "y"}, headers=H).status_code == 422
        c.patch(f"/api/memory/{mid}", json={"content": "Always use type hints"}, headers=H)
        assert c.get(f"/api/memory?project_id={pid}&q=hints", headers=H).json()[0]["content"] == "Always use type hints"
        c.post(f"/api/projects/{pid}/index", headers=H)
        assert c.get(f"/api/projects/{pid}/search?q=add", headers=H).json()[0]["path"] == "demo/math_utils.py"
        c.delete(f"/api/memory/{mid}", headers=H)
        assert c.get(f"/api/memory?project_id={pid}", headers=H).json() == []
