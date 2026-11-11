"""Cloud-only inference: routing through the signed-in account, consent, redaction, outages."""

import threading

import pytest
from fastapi.testclient import TestClient

from moth.inference.cloud import CloudUnavailable, MothCloudClient
from moth.inference.cloud_server import create_cloud_app
from moth.inference.local import LocalInference
from moth.inference.router import InferenceRouter, InferenceSettings, NotSignedIn, WorkspaceConsentRequired
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams

ACCOUNT = {"server_url": "https://moth.example", "token": "session-token"}


@pytest.fixture
def cloud(tiny_model):
    engine = LocalInference(tiny_model["models_dir"])
    engine.load("fx-model", "cpu")
    received = []
    app = create_cloud_app(engine)

    @app.middleware("http")
    async def capture(request, call_next):
        if request.url.path == "/v1/chat":
            received.append(((await request.body()).decode(), request.headers.get("authorization")))
        return await call_next(request)

    return TestClient(app), received


def make_router(account=ACCOUNT, http=None, consent=lambda pid: False, settings=None):
    seen = {}

    def factory(url, key):
        seen["url"], seen["key"] = url, key
        return MothCloudClient("", key, http=http) if http else MothCloudClient(url, key)

    r = InferenceRouter(lambda: settings or InferenceSettings(), account=lambda: account, consent=consent,
                        client_factory=factory)
    return r, seen


def test_requires_sign_in():
    r, _ = make_router(account=None)
    with pytest.raises(NotSignedIn):
        r.endpoint()
    assert r.status()["available"] is False and "Sign in" in r.status()["error"]


def test_uses_account_server_cloud_endpoint_with_session_token():
    r, seen = make_router()
    r.cloud()
    assert seen == {"url": "https://moth.example/cloud", "key": "session-token"}
    dev, seen2 = make_router(settings=InferenceSettings(cloud_url="http://self.host"))
    dev.cloud()
    assert seen2["url"] == "http://self.host"  # developer override


def test_chat_streams_from_cloud_and_redacts_secrets(cloud):
    http, received = cloud
    r, _ = make_router(http=http)
    parts = []
    stats = r.chat([Message("user", "key AKIAABCDEFGHIJKLMNOP def add(")], GenerationParams(max_new_tokens=6, temperature=0),
                   parts.append, threading.Event())
    assert stats.generated_tokens == 6
    body, auth = received[0]
    assert "AKIAABCDEFGHIJKLMNOP" not in body and "REDACTED" in body and auth == "Bearer session-token"


def test_agent_needs_per_workspace_consent(cloud):
    http, _ = cloud
    granted = {7}
    r, _ = make_router(http=http, consent=lambda pid: pid in granted)
    with pytest.raises(WorkspaceConsentRequired):
        r.agent_llm(3)
    llm = r.agent_llm(7)
    assert llm.name.endswith("(MOTH Cloud)")
    with pytest.raises(WorkspaceConsentRequired):
        r.chat([Message("user", "x")], GenerationParams(max_new_tokens=1), lambda t: None, project_id=3, project_data=True)


def test_cloud_outage_is_reported_not_raised_as_crash():
    r, _ = make_router(account={"server_url": "http://127.0.0.1:9", "token": "t"})
    st = r.status()
    assert st["available"] is False and "unreachable" in st["error"]
    with pytest.raises(CloudUnavailable):
        r.chat([Message("user", "hi")], GenerationParams(max_new_tokens=2), lambda t: None)


def test_client_refuses_non_moth_servers():
    from fastapi import FastAPI

    fake = FastAPI()

    @fake.get("/v1/health")
    def h():
        return {"service": "moth-cloud", "protocol": 1, "models": [{"name": "gpt", "architecture": "other"}]}

    with pytest.raises(CloudUnavailable, match="non-MOTH"):
        MothCloudClient("", http=TestClient(fake)).health()


def test_cloud_client_surfaces_server_errors():
    from fastapi import FastAPI, HTTPException

    app = FastAPI()

    @app.get("/v1/health")
    def h():
        return {"service": "moth-cloud", "protocol": 1, "models": [{"name": "m", "architecture": "moth-decoder-v1"}]}

    @app.post("/v1/chat")
    def chat():
        raise HTTPException(402, "You've used your MOTH Cloud allowance for this period.")

    with pytest.raises(CloudUnavailable, match="allowance"):
        MothCloudClient("", http=TestClient(app)).chat([Message("user", "hi")], GenerationParams(max_new_tokens=2),
                                                        lambda t: None)


def test_desktop_api_cloud_only(paths, project):
    from moth.server.app import create_app

    H = {"Authorization": "Bearer t"}
    with TestClient(create_app(paths, token="t")) as c:
        # no local load endpoint and no local/auto inference modes
        assert c.post("/api/models/load", json={"id": "x"}, headers=H).status_code in (404, 405)
        assert c.get("/api/inference", headers=H).status_code == 404
        r = c.post("/api/chat", json={"message": "hi"}, headers=H)
        assert r.status_code == 401 and "Sign in" in r.json()["detail"]
        pid = c.post("/api/projects", json={"path": str(project)}, headers=H).json()["id"]
        c.put("/api/account/session", json={"server_url": "http://127.0.0.1:9", "token": "tok"}, headers=H)
        r = c.post("/api/tasks", json={"project_id": pid, "goal": "do it"}, headers=H)
        assert r.status_code == 412 and r.headers["x-moth-reason"] == "workspace_consent_required"
        assert c.put(f"/api/projects/{pid}/cloud-consent", json={"granted": True}, headers=H).json()["granted"]
        r = c.post("/api/tasks", json={"project_id": pid, "goal": "do it"}, headers=H)
        assert r.status_code == 503  # consent given, but the cloud is unreachable: reported clearly
        st = c.get("/api/cloud/status", headers=H).json()
        assert st["signed_in"] and st["available"] is False
        assert c.get("/api/policy", headers=H).status_code == 404  # policy lives on the MOTH Server


def test_cloud_status_explains_why_nothing_is_served():
    import httpx

    from moth.inference.cloud import MothCloudClient, CloudUnavailable

    def server(health):
        return httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=health)))

    new = {"service": "moth-cloud", "protocol": 1, "models": [], "status": "inference_disabled",
           "message": "A model is deployed, but MOTH Cloud inference is turned off."}
    try:
        MothCloudClient("https://moth.test", http=server(new)).health()
        raise AssertionError("expected CloudUnavailable")
    except CloudUnavailable as e:
        assert e.reason == "inference_disabled" and "turned off" in str(e)
    old = {"service": "moth-cloud", "protocol": 1, "models": []}  # a v0.3.0 server sends no reason
    try:
        MothCloudClient("https://moth.test", http=server(old)).health()
        raise AssertionError("expected CloudUnavailable")
    except CloudUnavailable as e:
        assert e.reason == "no_model_deployed" and "creates a model in Intelligence" in str(e)
    tunnel_down = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(530, text="<html>")))
    try:
        MothCloudClient("https://x.trycloudflare.com", http=tunnel_down).health()
        raise AssertionError("expected CloudUnavailable")
    except CloudUnavailable as e:
        assert e.reason == "unreachable" and "tunnel" in str(e)


def test_local_genesis_reset_deletes_only_native_ai_data(tmp_path):
    """This computer's part of Genesis Reset: MOTH Code's own model/training folders and training tables
    go; projects, conversations, settings and unrelated files stay. The exact phrase is required."""
    from fastapi.testclient import TestClient

    from moth.config import get_paths
    from moth.server.app import create_app

    paths = get_paths(tmp_path / "home")
    with TestClient(create_app(paths, token="t")) as c:
        h = {"Authorization": "Bearer t"}
        svc = c.app.state.services
        for d in (paths.models / "pkg", paths.runs / "r1" / "checkpoints", paths.datasets / "d1", paths.tokenizers,
                  paths.home / "participant" / "jobs"):
            d.mkdir(parents=True, exist_ok=True)
            (d / "x.bin").write_bytes(b"native" * 10)
        keep = paths.home / "notes.txt"
        keep.write_text("mine")
        svc.db.execute("INSERT INTO training_runs(id, name, status, step, config, out_dir, created_at, updated_at) VALUES "
                       "('r1','run','completed',3,'{}','x',1,1)")
        svc.db.execute("INSERT INTO conversations(project_id, title, created_at) VALUES (NULL,'keep me',1)")
        svc.db.set_setting("permissions", {"auto_write": False})
        inv = c.get("/api/native-ai", headers=h).json()
        assert inv["files"] == 5 and inv["training_runs"] == 1 and inv["confirmation"] == "RESET GENESIS"
        assert c.post("/api/native-ai/reset", headers=h, json={"confirmation": "reset"}).status_code == 422
        assert (paths.models / "pkg" / "x.bin").exists()
        r = c.post("/api/native-ai/reset", headers=h, json={"confirmation": "RESET GENESIS"})
        assert r.status_code == 200 and r.json() == {"deleted_files": 5, "deleted_bytes": 300, "remaining_files": 0}
        assert c.get("/api/native-ai", headers=h).json()["training_runs"] == 0
        assert keep.read_text() == "mine" and paths.models.is_dir()
        assert svc.db.one("SELECT title FROM conversations")["title"] == "keep me"
        assert svc.db.get_setting("permissions") == {"auto_write": False}
