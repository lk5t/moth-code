"""2.1: security checks from chat — code, dependency and configuration audits, and the website test."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from moth.security import audit as A
from moth.security import scanner as SC
from test_server import H, client


def test_requests_are_recognised():
    assert A.parse_request("audit my code for security problems") == "code_audit"
    assert A.parse_request("can you look for hard-coded secrets in this project") == "code_audit"
    assert A.parse_request("check my dependencies for vulnerabilities") == "deps_audit"
    assert A.parse_request("is my nginx config secure?") == "config_audit"
    assert A.parse_request("write a sorting function") is None
    p = SC.parse_request("test my website https://shop.example.com/search?q=a for xss")
    assert p.kind == "web" and p.path == "/search?q=a" and p.ports == [443]
    assert SC.parse_request("scan 10.0.0.5").kind == "network"


def test_code_audit_finds_secrets_and_risky_code(tmp_path):
    (tmp_path / "app.py").write_text("import subprocess, pickle\nKEY = 'AKIAABCDEFGHIJKLMNOP'\n"
                                     "subprocess.run(cmd, shell=True)\ncur.execute(f\"SELECT * FROM u WHERE id={uid}\")\n"
                                     "data = pickle.loads(blob)\n")
    (tmp_path / "web.js").write_text("el.innerHTML = userInput;\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("eval(a)\n")  # dependencies are not the user's code
    r = A.code_audit(tmp_path)
    titles = [f["title"] for f in r["findings"]]
    assert r["findings"][0]["severity"] == "critical" and "Secret in the code" in r["findings"][0]["title"]
    assert "AKIAABCDEFGHIJKLMNOP" not in json.dumps(r)  # secrets are never shown in full
    for t in ("Shell command with shell=True", "SQL query built from strings", "Unpickling data (can run code)", "HTML injection sink"):
        assert t in titles
    assert not any("node_modules" in f["where"] for f in r["findings"])


def test_dependency_and_config_audits(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.25.0\nflask>=3.0\n")
    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"lodash": "^4.17.15", "react": "18.3.1"}}))
    r = A.deps_audit(tmp_path)
    assert {f["title"].split()[0] for f in r["findings"]} == {"requests", "lodash"} and "not exhaustive" in r["note"]
    c = A.config_audit([("sshd_config", "PermitRootLogin yes\nPasswordAuthentication yes\n"),
                        ("docker-compose.yml", "services:\n  db:\n    ports: ['5432:5432']\n    privileged: true\n"),
                        (".env", "SECRET=1\n"), (".env.example", "SECRET=\n")])
    titles = {f["title"] for f in c["findings"]}
    assert {"SSH allows root login", "SSH accepts passwords", "Container runs privileged",
            "Database port published to every network", ".env file with secrets"} <= titles
    assert sum(f["title"] == ".env file with secrets" for f in c["findings"]) == 1  # the example file is fine
    md = A.report_markdown(c)
    assert "Fix:" in md and "SSH allows root login" in md


def test_audit_api_saves_to_chat(paths, tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "a.py").write_text("x = eval(user)\n")
    with client(paths) as c:
        pid = c.post("/api/projects", headers=H(), json={"path": str(proj)}).json()["id"]
        assert c.post("/api/security/parse", headers=H(), json={"message": "audit my code for security"}).json()["tool"] == "code_audit"
        assert c.post("/api/security/audit", headers=H(), json={"message": "audit my code for security"}).status_code == 409
        r = c.post("/api/security/audit", headers=H(), json={"message": "audit my code for security", "project_id": pid}).json()
        assert r["report"]["findings"][0]["title"] == "eval/exec on dynamic input"
        msgs = c.get(f"/api/conversations/{r['conversation_id']}/messages", headers=H()).json()
        assert msgs[1]["meta"]["report"]["kind"] == "Code audit"
        cfg = c.post("/api/security/audit", headers=H(), json={"message": "check this sshd config for security",
                                                                 "files": [{"path": "sshd_config", "content": "PermitEmptyPasswords yes"}], "save": False}).json()
        assert cfg["report"]["findings"][0]["severity"] == "critical"


class _Vulnerable(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        if u.path == "/":
            body = ('<html><a href="/search?q=hello">search</a><a href="/item?id=1">item</a>'
                    '<a href="/login?next=/home">login</a><a href="https://other.example/x">out</a>'
                    '<form method="post" action="/buy"><input name="qty"></form></html>')
            return self._send(200, body)
        if u.path == "/search":
            return self._send(200, f"<p>Results for {q.get('q', '')}</p>")  # reflected unencoded
        if u.path == "/item":
            if "'" in q.get("id", ""):
                return self._send(500, "You have an error in your SQL syntax near ''")
            return self._send(200, "item")
        if u.path == "/login":
            self.send_response(302)
            self.send_header("Location", q.get("next", "/"))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        return self._send(404, "nope")

    def _send(self, code, body):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


def test_website_test_finds_xss_sqli_redirect_and_csrf(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Vulnerable)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    m = SC.ScanManager(tmp_path)
    plan = SC.parse_request(f"test my website http://127.0.0.1:{port}/ for vulnerabilities")
    assert plan.kind == "web"
    sid = m.start(plan, confirmed=True)["id"]
    end = time.time() + 60
    while m.get(sid)["status"] == "running" and time.time() < end:
        time.sleep(0.05)
    s = m.get(sid)
    titles = {f["title"] for f in s["findings"]}
    assert s["status"] == "done"
    assert {"Input shown back without encoding (possible XSS)", "Database error on a quote (possible SQL injection)",
            "Open redirect", "Form without a CSRF token"} <= titles
    assert not any(e.get("path", "").startswith("https://other") for e in s["log"])  # stays on the confirmed site
    assert "Website test of 127.0.0.1" in SC.summary_markdown(m.get(sid, with_log=False))
    srv.shutdown()
