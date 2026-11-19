"""2.0 chat pentesting: request parsing, refusals, a real scan of local test servers, stop, stronger step, chat."""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from moth.security import scanner as SC
from test_server import H, client


def test_parse_requests_and_refusals():
    p = SC.parse_request("check 10.0.0.5:8080 for vulnerabilities")
    assert (p.target, p.ports, p.hosts) == ("10.0.0.5", [8080], ["10.0.0.5"])
    assert SC.parse_request("find vulnerabilities on 10.0.0.5 port 8080").ports == [8080]
    assert SC.parse_request("scan https://example.com").ports == [443]
    assert SC.parse_request("scan my lab 192.168.1.0/24 ports 22, 80 and 443").ports == [22, 80, 443]
    assert SC.parse_request("scan 10.1.2.3").default_ports and len(SC.parse_request("scan 10.1.2.3").ports) == len(SC.COMMON_PORTS)
    assert SC.parse_request("write a port scanner in python") is None  # no target
    assert SC.parse_request("explain how 10.0.0.5 routing works") is None  # no scan asked
    assert SC.parse_request("check the test in main.py") is None
    for bad, why in [("scan 8.8.8.0/24", "private"), ("scan 10.0.0.0/16", "/24"), ("scan 224.0.0.1", "multicast"),
                     ("scan 10.0.0.1 ports 1-5000", "1024"), ("scan 0.0.0.0", "not a single machine")]:
        with pytest.raises(SC.ScanRefused, match=why):
            SC.parse_request(bad)


def test_version_findings():
    titles = [f.title for f in SC.version_findings("Apache/2.4.49 (Unix)", 80)]
    assert any("2.4.49" in t for t in titles)
    assert SC.version_findings("SSH-2.0-OpenSSH_9.6p1 Ubuntu", 22)[0].ref == "CVE-2024-6387"
    assert SC.version_findings("SSH-2.0-OpenSSH_9.9", 22) == []
    assert SC.version_findings("220 (vsFTPd 2.3.4)", 21)[0].severity == "critical"
    assert SC.version_findings("nginx", 80) == []


class _Web(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/.git/HEAD":
            body, code = b"ref: refs/heads/main\n", 200
        elif self.path == "/":
            body, code = b"<html><title>Index of /</title></html>", 200
        else:
            body, code = b"nope", 404
        self.send_response(code)
        self.send_header("Server", "Apache/2.4.49 (Unix)")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _redis_like():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            try:
                c.settimeout(2)
                if c.recv(64).startswith(b"PING"):
                    c.sendall(b"+PONG\r\n")
            except OSError:
                pass
            c.close()
    threading.Thread(target=loop, daemon=True).start()
    return srv


def _wait(m, sid, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        s = m.get(sid)
        if s["status"] != "running":
            return s
        time.sleep(0.05)
    raise AssertionError("scan did not finish")


def test_real_scan_of_local_servers(tmp_path):
    web = ThreadingHTTPServer(("127.0.0.1", 0), _Web)
    threading.Thread(target=web.serve_forever, daemon=True).start()
    redis = _redis_like()
    wport, rport = web.server_address[1], redis.getsockname()[1]
    closed = socket.socket(); closed.bind(("127.0.0.1", 0)); cport = closed.getsockname()[1]; closed.close()
    real = socket.create_connection

    def connect(addr, timeout=None):  # the Redis check talks to port 6379; map it to the test server
        host, port = addr
        return real((host, rport if port == 6379 else port), timeout=timeout)

    events = []
    m = SC.ScanManager(tmp_path, events.append, connect=connect)
    with pytest.raises(SC.ScanRefused, match="Yes"):
        m.start(SC.parse_request(f"scan localhost port {wport}"), confirmed=False)
    plan = SC.parse_request(f"scan 127.0.0.1 ports {wport}, {cport}, 6379")
    s = _wait(m, m.start(plan, confirmed=True)["id"])
    assert s["status"] == "done" and s["progress"] == 1.0
    assert sorted(o["port"] for o in s["open_ports"]) == sorted([wport, 6379])
    titles = {f["title"] for f in s["findings"]}
    assert "Apache 2.4.49 path traversal and remote code execution" in titles
    assert "Git repository is downloadable (/.git/)" in titles
    assert "Directory listing is turned on" in titles
    assert "Redis answers without a password" in titles
    assert s["findings"][0]["severity"] == "critical"  # most severe first
    actions = [e["action"] for e in s["log"]]
    assert actions[0] == "confirmed" and "open" in actions and actions[-1] == "finished"
    assert {e["kind"] for e in events} >= {"started", "port", "finding", "finished"}
    md = SC.summary_markdown(m.get(s["id"], with_log=False))
    assert "CRITICAL" in md and "Fix:" in md
    # survives a restart
    assert SC.ScanManager(tmp_path).get(s["id"])["findings"] == s["findings"]
    web.shutdown(); redis.close()


def test_stop_button_and_limits(tmp_path):
    def slow(addr, timeout=None):
        time.sleep(0.2)
        raise OSError("closed")
    m = SC.ScanManager(tmp_path, connect=slow)
    plan = SC.parse_request("scan 10.9.9.9 ports 1-300")
    a = m.start(plan, True)["id"]
    m.start(plan, True)
    with pytest.raises(SC.ScanRefused, match="already running"):
        m.start(plan, True)
    time.sleep(0.3)
    assert m.stop() == 2
    s = _wait(m, a)
    assert s["status"] == "stopped" and s["progress"] < 1


def test_stronger_step_needs_its_own_yes(tmp_path):
    m = SC.ScanManager(tmp_path, connect=lambda addr, timeout=None: (_ for _ in ()).throw(OSError("closed")))
    s = _wait(m, m.start(SC.parse_request("scan 10.9.9.8 port 21"), True)["id"])
    scan = m._scans[s["id"]]
    scan.open_ports.append({"host": "10.9.9.8", "port": 21, "service": "ftp", "banner": ""})
    m._offer_stronger(scan)
    step = scan.stronger[0]
    assert step["check"] == "ftp_anonymous" and step["status"] == "offered"
    with pytest.raises(SC.ScanRefused):
        m.run_stronger(s["id"], step["id"], confirmed=False)
    assert scan.stronger[0]["status"] == "offered"


def test_scan_api_and_chat(paths):
    with client(paths) as c:
        r = c.post("/api/scans/parse", headers=H(), json={"message": "find vulnerabilities on 10.0.0.5 port 8080"}).json()
        assert r["plan"]["describe"] == "10.0.0.5 port 8080"
        assert c.post("/api/scans/parse", headers=H(), json={"message": "hello there"}).json()["plan"] is None
        assert "private" in c.post("/api/scans/parse", headers=H(), json={"message": "scan 1.2.3.0/24"}).json()["refused"]
        assert c.post("/api/scans", headers=H(), json={"message": "scan 127.0.0.1 port 9", "confirmed": False}).status_code == 400
        sid = c.post("/api/scans", headers=H(), json={"message": "scan 127.0.0.1 port 9", "confirmed": True}).json()["id"]
        for _ in range(200):
            if c.get(f"/api/scans/{sid}", headers=H()).json()["status"] != "running":
                break
            time.sleep(0.05)
        assert c.get("/api/scans", headers=H()).json()[0]["id"] == sid
        out = c.post(f"/api/scans/{sid}/to-chat", headers=H(), json={"question": "scan 127.0.0.1 port 9"}).json()
        msgs = c.get(f"/api/conversations/{out['conversation_id']}/messages", headers=H()).json()
        assert [m["role"] for m in msgs] == ["user", "assistant"] and "Scan of 127.0.0.1" in msgs[1]["content"]
        assert c.get("/api/scans/nope", headers=H()).status_code == 404
