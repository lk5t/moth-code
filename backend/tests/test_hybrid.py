import datetime as dt
import threading

import pytest
from fastapi.testclient import TestClient

from moth.inference.cloud import CloudUnavailable, MothCloudClient
from moth.inference.cloud_server import create_cloud_app
from moth.inference.local import LocalInference, NoModelLoaded
from moth.inference.router import InferenceRouter, InferenceSettings, RemoteConsentRequired
from moth.model.chat_format import Message
from moth.model.generation import GenerationParams


def make_router(local, settings, cloud_http=None):
    return InferenceRouter(local, lambda: settings,
                           client_factory=lambda s: MothCloudClient("", http=cloud_http) if cloud_http else MothCloudClient(s.cloud_url))


@pytest.fixture
def cloud(tiny_model):
    engine = LocalInference(tiny_model["models_dir"])
    engine.load("fx-model", "cpu")
    received = []
    app = create_cloud_app(engine)

    @app.middleware("http")
    async def capture(request, call_next):
        if request.url.path == "/v1/chat":
            received.append((await request.body()).decode())
        return await call_next(request)

    app.state.engine = engine
    return TestClient(app), received


def test_local_mode_requires_loaded_model(tmp_path):
    r = make_router(LocalInference(tmp_path), InferenceSettings(mode="local"))
    with pytest.raises(NoModelLoaded):
        r.select(project_data=False)


def test_cloud_not_configured_is_reported_honestly(tmp_path):
    r = make_router(LocalInference(tmp_path), InferenceSettings(mode="cloud"))
    with pytest.raises(CloudUnavailable, match="not available yet"):
        r.select(project_data=False)
    assert r.status()["cloud"] == {"configured": False}


def test_remote_requires_consent(tmp_path, cloud):
    http, _ = cloud
    s = InferenceSettings(mode="cloud", cloud_url="http://moth-cloud.test")
    r = make_router(LocalInference(tmp_path), s, http)
    with pytest.raises(RemoteConsentRequired):
        r.select(project_data=False)
    s.consent_remote_chat = True
    assert r.select(project_data=False) == "cloud"
    with pytest.raises(RemoteConsentRequired, match="project files"):
        r.select(project_data=True)
    s.consent_remote_project_data = True
    assert r.select(project_data=True) == "cloud"


def test_auto_prefers_local(tiny_model, cloud):
    local = LocalInference(tiny_model["models_dir"])
    s = InferenceSettings(mode="auto", cloud_url="http://x", consent_remote_chat=True)
    r = make_router(local, s, cloud[0])
    assert r.select(False) == "cloud"
    local.load("fx-model", "cpu")
    assert r.select(False) == "local"


def test_cloud_chat_streams_real_model_output_and_redacts_secrets(tmp_path, cloud):
    http, received = cloud
    s = InferenceSettings(mode="cloud", cloud_url="http://x", consent_remote_chat=True)
    r = make_router(LocalInference(tmp_path), s, http)
    parts = []
    via, stats = r.chat([Message("user", "my key is AKIAABCDEFGHIJKLMNOP, def add(")],
                        GenerationParams(max_new_tokens=8, temperature=0.0), parts.append, threading.Event())
    assert via == "cloud" and stats.generated_tokens == 8
    # Exactly what the same MOTH model produces locally (greedy decoding is deterministic).
    local_parts = []
    http.app.state.engine.chat([Message("user", "my key is [REDACTED:aws_access_key], def add(")],
                               GenerationParams(max_new_tokens=8, temperature=0.0), local_parts.append)
    assert "".join(parts) == "".join(local_parts)
    assert "AKIAABCDEFGHIJKLMNOP" not in received[0] and "REDACTED" in received[0]


def test_client_refuses_non_moth_servers():
    from fastapi import FastAPI

    fake = FastAPI()

    @fake.get("/v1/health")
    def h():
        return {"service": "moth-cloud", "protocol": 1, "models": [{"name": "gpt", "architecture": "other"}]}

    with pytest.raises(CloudUnavailable, match="non-MOTH"):
        MothCloudClient("", http=TestClient(fake)).health()

    other = FastAPI()

    @other.get("/v1/health")
    def h2():
        return {"service": "something-else"}

    with pytest.raises(CloudUnavailable, match="not a MOTH Cloud"):
        MothCloudClient("", http=TestClient(other)).health()


def test_inference_api_masks_key(paths):
    from moth.server.app import create_app

    H = {"Authorization": "Bearer t"}
    with TestClient(create_app(paths, token="t")) as c:
        d = c.put("/api/inference", json={"mode": "auto", "cloud_api_key": "secret-key"}, headers=H).json()
        assert d["settings"]["cloud_api_key"] == "********" and d["settings"]["mode"] == "auto"
        c.put("/api/inference", json={"cloud_api_key": "********"}, headers=H)  # unchanged
        assert c.app.state.services.db.get_setting("inference")["cloud_api_key"] == "secret-key"
        r = c.post("/api/chat", json={"message": "hi"}, headers=H)
        assert r.status_code == 409 and "MOTH Cloud" in r.json()["detail"]


def test_router_uses_signed_in_account_server(tmp_path):
    seen = {}

    def factory(s):
        seen["url"], seen["key"] = s.cloud_url, s.cloud_api_key
        return MothCloudClient(s.cloud_url, s.cloud_api_key)

    acct = {"server_url": "https://moth.example/", "token": "session-token"}
    r = InferenceRouter(LocalInference(tmp_path), lambda: InferenceSettings(mode="cloud", consent_remote_chat=True),
                        client_factory=factory, account=lambda: acct)
    r.cloud()
    assert seen == {"url": "https://moth.example/cloud", "key": "session-token"}
    # explicit endpoint settings take precedence over the account
    r2 = InferenceRouter(LocalInference(tmp_path), lambda: InferenceSettings(mode="cloud", cloud_url="https://self.host"),
                         client_factory=factory, account=lambda: acct)
    r2.cloud()
    assert seen["url"] == "https://self.host"


def test_cloud_client_surfaces_server_errors():
    from fastapi import FastAPI, HTTPException

    app = FastAPI()

    @app.get("/v1/health")
    def h():
        return {"service": "moth-cloud", "protocol": 1, "models": [{"name": "m", "architecture": "moth-decoder-v1"}]}

    @app.post("/v1/chat")
    def chat():
        raise HTTPException(402, "You've used your MOTH Cloud allowance for this period.")

    client = MothCloudClient("", http=TestClient(app))
    with pytest.raises(CloudUnavailable, match="allowance"):
        client.chat([Message("user", "hi")], GenerationParams(max_new_tokens=2), lambda t: None)
