"""0.7.1: the cloud update agent asks GitHub conditionally and respects its rate limit."""
import http.server
import json
import threading

import pytest

from test_agent_download import A, agent  # noqa: F401 — the agent fixture

RELEASES = [{"tag_name": "server-v0.7.1", "assets": []}]


class GitHub(http.server.BaseHTTPRequestHandler):
    seen: list = []
    mode = "ok"

    def do_GET(self):  # noqa: N802
        type(self).seen.append(self.headers.get("If-None-Match"))
        if type(self).mode == "limited":
            self.send_response(403)
            self.send_header("X-RateLimit-Remaining", "0")
            self.send_header("X-RateLimit-Reset", "4102444800")
            self.end_headers()
            return
        if self.headers.get("If-None-Match") == '"v1"':
            self.send_response(304)
            self.end_headers()
            return
        body = json.dumps(RELEASES).encode()
        self.send_response(200)
        self.send_header("ETag", '"v1"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def github():
    GitHub.seen, GitHub.mode = [], "ok"
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), GitHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/repos/x/y/releases"
    srv.shutdown()


def test_unchanged_release_list_uses_conditional_request(github, agent):  # noqa: F811
    c = agent._gh_cache()
    assert agent._gh_releases(github, c) == RELEASES
    agent._gh_save(c)
    c2 = agent._gh_cache()  # a later check (cron starts a new agent process each time)
    assert agent._gh_releases(github, c2) == RELEASES
    assert GitHub.seen == [None, '"v1"']  # the second request was answered 304 Not Modified


def test_rate_limit_is_respected_not_retried(github, agent):  # noqa: F811
    c = agent._gh_cache()
    agent._gh_releases(github, c)
    agent._gh_save(c)
    GitHub.mode = "limited"
    c = agent._gh_cache()
    assert agent._gh_releases(github, c) == RELEASES  # the last known list is used
    assert len(GitHub.seen) == 2  # one refused request, no retries
    assert any("rate limit" in l for l in agent.lines)
    c = agent._gh_cache()
    assert c["wait_until"] > A.time.time()
    assert agent._gh_releases(github, c) == RELEASES and len(GitHub.seen) == 2  # waits: no request at all


def test_rate_limited_without_cache_reports_instead_of_hammering(github, agent):  # noqa: F811
    GitHub.mode = "limited"
    with pytest.raises(A.AgentError, match="refused|rate limit"):
        agent._gh_releases(github, agent._gh_cache())
    with pytest.raises(A.AgentError, match="rate limit"):
        agent._gh_releases(github, agent._gh_cache())
    assert len(GitHub.seen) == 1
