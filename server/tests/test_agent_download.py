"""The update agent's downloads: interrupted transfers are detected and resumed, never accepted short.

Regression test for the desktop 0.3.1 relay failure: GitHub's download connection dropped part-way
through the 129 MB installer, ``urllib`` returned the partial body without an error, and the agent
(correctly) rejected the file for not matching the SHA-256 in the signed manifest — every 15 minutes.
"""

import hashlib
import http.server
import base64
import json
import sys
import threading
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy" / "agent"))
import moth_agent as A  # noqa: E402

DATA = bytes(range(256)) * 8192  # 2 MiB


class Flaky(http.server.BaseHTTPRequestHandler):
    """Serves DATA; the first ``drops`` responses announce the full length but close part-way."""

    drops = 0
    ranges: list = []
    honour_range = True

    def do_GET(self):  # noqa: N802
        start = 0
        rng = self.headers.get("Range")
        type(self).ranges.append(rng)
        if rng and type(self).honour_range:
            start = int(rng.split("=")[1].rstrip("-"))
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{len(DATA) - 1}/{len(DATA)}")
        else:
            self.send_response(200)
        body = DATA[start:]
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if type(self).drops > 0:
            type(self).drops -= 1
            self.wfile.write(body[: len(body) // 3])
            self.wfile.flush()
            self.connection.shutdown(2)  # the connection drops: no error reaches urllib
            return
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    Flaky.drops, Flaky.ranges, Flaky.honour_range = 0, [], True
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/MOTH.Code_0.3.1_x64-setup.exe"
    srv.shutdown()


@pytest.fixture
def agent(tmp_path, monkeypatch):
    monkeypatch.setattr(A.time, "sleep", lambda s: None)
    a = object.__new__(A.Agent)
    (tmp_path / "downloads").mkdir()
    a.i = types.SimpleNamespace(home=tmp_path, data_dir=tmp_path / "data", agent_token="t")
    a.cfg = {}
    a.deployment_id, a.log_buffer = None, []
    a.lines = []
    a.log = a.lines.append
    return a


def entry(data=DATA):
    return {"file": "MOTH.Code_0.3.1_x64-setup.exe", "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def rel_for(agent, url):
    return {"fetch": lambda name, size=None: agent._http_get(url, dest=agent.i.home / "downloads" / name, size=size)}


def test_interrupted_download_is_resumed_and_verified(server, agent):
    Flaky.drops = 2
    p = agent.fetch_verified(rel_for(agent, server), entry())
    assert p.read_bytes() == DATA
    assert Flaky.ranges[0] is None and all(r and r.startswith("bytes=") for r in Flaky.ranges[1:])
    assert any("interrupted" in l for l in agent.lines) and any("resumed at byte" in l for l in agent.lines)
    assert not list((agent.i.home / "downloads").glob("*.part"))


def test_server_without_range_support_restarts_the_download(server, agent):
    Flaky.drops, Flaky.honour_range = 1, False
    assert agent.fetch_verified(rel_for(agent, server), entry()).read_bytes() == DATA


def test_a_download_that_never_completes_is_refused(server, agent):
    Flaky.drops = 100
    with pytest.raises(A.AgentError, match="connection closed after"):
        agent.fetch_verified(rel_for(agent, server), entry())
    assert not list((agent.i.home / "downloads").iterdir())  # nothing partial is left behind


def test_complete_but_different_bytes_are_still_rejected(server, agent):
    """Completeness checks never replace the signed SHA-256: a full-length file with other bytes is refused."""
    other = bytes(reversed(DATA))
    with pytest.raises(A.AgentError, match="does not match the SHA-256 in the signed manifest") as e:
        agent.fetch_verified(rel_for(agent, server), entry(other))
    assert f"received {len(DATA)} bytes" in str(e.value)
    assert not (agent.i.home / "downloads" / "MOTH.Code_0.3.1_x64-setup.exe").exists()


def test_wrong_size_is_refused_before_hashing(server, agent):
    e = entry()
    e["size"] = len(DATA) + 10
    with pytest.raises(A.AgentError, match="the signed manifest says"):
        agent.fetch_verified(rel_for(agent, server), e)


def github_fixture(agent, monkeypatch, tmp_path, *, token=False, broken_old=False, tamper=False):
    """GitHub-style local transport: REST asset calls are rate-limited, public downloads work.

    Uses genuine Ed25519 manifests and SHA-256 payloads; only the network service is simulated.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    import urllib.error

    key = Ed25519PrivateKey.generate()
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    agent.cfg.update(source='github:lk5t/moth-code', pubkey=base64.b64encode(pub).decode())
    if token:
        token_file = tmp_path / 'test-token'
        token_file.write_text('isolated-test-credential')
        agent.cfg['github_token_file'] = str(token_file)
    payload = entry()
    manifest = json.dumps({'version': '0.5.8', 'kind': 'server', 'components': {'server': payload}}).encode()
    signature = base64.b64encode(key.sign(manifest))
    names = {'moth-release-0.5.8.json': manifest, 'moth-release-0.5.8.json.sig': signature,
             payload['file']: DATA}
    if tamper:
        names['moth-release-0.5.8.json'] = manifest + b' '
    assets = [{'name': name, 'url': f'https://api.github.com/repos/lk5t/moth-code/releases/assets/{i}',
               'browser_download_url': f'https://github.com/lk5t/moth-code/releases/download/server-v0.5.8/{name}'}
              for i, name in enumerate(names)]
    releases = [{'draft': False, 'assets': assets}]
    if broken_old:
        releases.append({'draft': False, 'assets': [
            {'name': name, 'url': 'https://api.github.com/old/' + name,
             'browser_download_url': 'https://github.com/old/' + name}
            for name in ('moth-release-desktop-0.3.1.json', 'moth-release-desktop-0.3.1.json.sig')]})
    calls = []
    from io import BytesIO
    class Response(BytesIO):
        status = 200
        def __init__(self, body):
            super().__init__(body)
            self.headers = {'Content-Length': str(len(body))}
    def urlopen(req, timeout=None):
        url = req.full_url
        calls.append((url, req.get_header('Authorization')))
        if url.endswith('/releases?per_page=20'):
            return Response(json.dumps(releases).encode())
        if '/old/' in url or ('api.github.com' in url and not token):
            raise urllib.error.HTTPError(url, 403, 'rate limit exceeded', {}, None)
        if 'api.github.com' in url:
            assert req.get_header('Authorization') == 'Bearer isolated-test-credential'
            name = assets[int(url.rsplit('/', 1)[1])]['name']
        else:
            assert req.get_header('Authorization') is None
            name = url.rsplit('/', 1)[1]
        return Response(names[name])
    monkeypatch.setattr(A.urllib.request, 'urlopen', urlopen)
    return calls, payload


def test_public_release_checks_do_not_spend_rest_quota_on_assets(agent, monkeypatch, tmp_path):
    calls, payload = github_fixture(agent, monkeypatch, tmp_path)
    for _ in range(4):  # the existing four checks per hour
        releases = agent.list_releases()
        assert releases[0]['version'] == '0.5.8'
        assert agent.fetch_verified(releases[0], payload).read_bytes() == DATA
    assert sum('api.github.com' in url for url, _ in calls) == 4
    assert not any('/releases/assets/' in url for url, _ in calls)


def test_private_releases_keep_authenticated_asset_api(agent, monkeypatch, tmp_path):
    calls, payload = github_fixture(agent, monkeypatch, tmp_path, token=True)
    releases = agent.list_releases()
    assert agent.fetch_verified(releases[0], payload).read_bytes() == DATA
    assert all(auth == 'Bearer isolated-test-credential' for _, auth in calls)
    assert any('/releases/assets/' in url for url, _ in calls)


def test_unreadable_historical_release_does_not_block_verified_new_release(agent, monkeypatch, tmp_path):
    _, payload = github_fixture(agent, monkeypatch, tmp_path, broken_old=True)
    releases = agent.list_releases()
    assert [r['version'] for r in releases] == ['0.5.8']
    assert agent.fetch_verified(releases[0], payload).read_bytes() == DATA
    assert any('rate limit exceeded' in line for line in agent.lines)


def test_public_download_transport_still_rejects_tampered_signature(agent, monkeypatch, tmp_path):
    github_fixture(agent, monkeypatch, tmp_path, tamper=True)
    assert agent.list_releases() == []
    assert any('signature does not verify' in line for line in agent.lines)


def test_all_unavailable_manifests_remain_an_error(agent, monkeypatch, tmp_path):
    github_fixture(agent, monkeypatch, tmp_path)
    import urllib.error
    original = A.urllib.request.urlopen
    def unavailable(req, timeout=None):
        if req.full_url.endswith('/releases?per_page=20'):
            return original(req, timeout=timeout)
        raise urllib.error.HTTPError(req.full_url, 403, 'rate limit exceeded', {}, None)
    monkeypatch.setattr(A.urllib.request, 'urlopen', unavailable)
    with pytest.raises(A.AgentError, match='no GitHub release manifests could be read'):
        agent.list_releases()
