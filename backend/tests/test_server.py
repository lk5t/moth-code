import sys
import time

from fastapi.testclient import TestClient

from moth.server.app import create_app

PY = f'"{sys.executable}"'


def client(paths, token="secret"):
    return TestClient(create_app(paths, token=token))


def H(token="secret"):
    return {"Authorization": f"Bearer {token}"}


def test_auth_required(paths):
    with client(paths) as c:
        assert c.get("/api/health").status_code == 200
        assert c.get("/api/projects").status_code == 401
        assert c.get("/api/projects", headers=H()).status_code == 200


def test_project_file_flow(paths, project):
    with client(paths) as c:
        p = c.post("/api/projects", json={"path": str(project)}, headers=H()).json()
        pid = p["id"]
        tree = c.get(f"/api/projects/{pid}/tree", headers=H()).json()
        assert any(e["path"] == "demo/math_utils.py" for e in tree)
        r = c.put(f"/api/projects/{pid}/file", json={"path": "hello.py", "content": "print(1)\n"}, headers=H())
        assert r.status_code == 200
        assert c.get(f"/api/projects/{pid}/file", params={"path": "hello.py"}, headers=H()).json()["content"] == "print(1)\n"
        assert c.get(f"/api/projects/{pid}/file", params={"path": "../x"}, headers=H()).status_code == 403
        assert c.get(f"/api/projects/{pid}/file", params={"path": "nope.py"}, headers=H()).status_code == 404
        scan = c.get(f"/api/projects/{pid}/scan", headers=H()).json()
        assert "Python" in scan["languages"]
        acts = c.get("/api/activity", headers=H()).json()
        assert any("Saved hello.py" in a["message"] for a in acts)


def test_settings_roundtrip(paths):
    with client(paths) as c:
        c.put("/api/settings", json={"theme": "moth", "permissions": {"auto_write": False}}, headers=H())
        s = c.get("/api/settings", headers=H()).json()
        assert s["theme"] == "moth" and s["permissions"]["auto_write"] is False


def test_terminal_over_websocket(paths, project):
    with client(paths) as c:
        pid = c.post("/api/projects", json={"path": str(project)}, headers=H()).json()["id"]
        sid = c.post("/api/terminals", json={"project_id": pid}, headers=H()).json()["id"]
        with c.websocket_connect("/ws/events?token=secret") as ws:
            assert ws.receive_json()["topic"] == "hello"
            r = c.post(f"/api/terminals/{sid}/run", json={"command": f'{PY} -c "print(42*2)"'}, headers=H())
            assert r.status_code == 200
            output, code = "", None
            deadline = time.time() + 20
            while time.time() < deadline:
                ev = ws.receive_json()
                if ev["topic"] != "terminal":
                    continue
                if ev["kind"] == "output":
                    output += ev["data"]
                elif ev["kind"] == "exit":
                    code = ev["code"]
                    break
            assert "84" in output and code == 0


def test_websocket_rejects_bad_token(paths):
    import pytest
    from starlette.websockets import WebSocketDisconnect

    with client(paths) as c:
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/events?token=wrong") as ws:
                ws.receive_json()
