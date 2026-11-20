"""2.4.1: MOTH on the whole computer and the web, every step with the user's OK."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from moth.agent import pc_tools as P
from moth.agent.tools import AgentContext, execute_tool


class Broker:
    def __init__(self, answer=True):
        self.answer, self.asked = answer, []

    def request(self, kind, target, reason, risk="medium", context=None, timeout=600, cancel_event=None):
        self.asked.append((kind, str(target)))
        return self.answer


def ctx(answer=True):
    c = AgentContext(workspace=None, project_id=0, permissions=None, approvals=Broker(answer), memory=None, index=None,
                     cancel=threading.Event(), emit=lambda e: None, task_id="t")
    return c


def test_files_anywhere_ask_once_per_folder_and_every_write(tmp_path):
    (tmp_path / "notes.txt").write_text("hello\nworld\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("b")
    c = ctx()
    assert "notes.txt" in execute_tool(c, "pc_list", {"path": str(tmp_path)}).output
    assert "world" in execute_tool(c, "pc_read", {"path": str(tmp_path / "notes.txt")}).output
    assert execute_tool(c, "pc_read", {"path": str(tmp_path / "sub" / "b.txt")}).ok
    assert [k for k, _ in c.approvals.asked] == ["read"]  # one question for the folder and everything below it
    r = execute_tool(c, "pc_write", {"path": str(tmp_path / "out.txt"), "content": "made by MOTH"})
    assert r.ok and (tmp_path / "out.txt").read_text() == "made by MOTH" and c.approvals.asked[-1][0] == "write"
    no = ctx(answer=False)
    r = execute_tool(no, "pc_write", {"path": str(tmp_path / "nope.txt"), "content": "x"})
    assert not r.ok and r.data.get("denied") and not (tmp_path / "nope.txt").exists()


def test_secrets_are_never_touched(tmp_path):
    (tmp_path / ".env").write_text("TOKEN=secret")
    c = ctx()
    r = execute_tool(c, "pc_read", {"path": str(tmp_path / ".env")})
    assert not r.ok and "credentials" in r.output and c.approvals.asked == []
    assert not execute_tool(c, "pc_write", {"path": str(tmp_path / "id_rsa"), "content": "x"}).ok


def test_commands_anywhere_ask_and_run(tmp_path):
    c = ctx()
    r = execute_tool(c, "pc_run", {"command": "echo hi-from-moth", "cwd": str(tmp_path)})
    assert r.ok and "hi-from-moth" in r.output and c.approvals.asked[0][0] == "execute"
    assert not execute_tool(ctx(answer=False), "pc_run", {"command": "echo x", "cwd": str(tmp_path)}).ok


PAGE = b"""<html><head><title>Shop</title><script>var hidden=1</script></head><body>
<h1>Welcome</h1><p>Prices are low.</p><a href="/two">Next page</a>
<form action="/sent"><input name="q" placeholder="Search"><input type="password" name="pw"></form></body></html>"""


@pytest.fixture()
def site():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = PAGE if self.path in ("/", "/index") else f"<html><title>Got {self.path}</title><body>You are at {self.path}</body></html>".encode()
            self.send_response(200); self.send_header("content-type", "text/html"); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_web_read_turns_a_page_into_text_and_asks_once_per_site(site):
    c = ctx()
    r = execute_tool(c, "web_read", {"url": site + "/"})
    assert r.ok and "Welcome" in r.output and "Prices are low." in r.output and "hidden" not in r.output
    execute_tool(c, "web_read", {"url": site + "/two"})
    assert c.approvals.asked == [("network", "127.0.0.1")]
    assert not execute_tool(c, "web_read", {"url": "file:///etc/passwd"}).ok


CHROME = "/opt/pw-browsers/chromium-1243/chrome-linux64/chrome"


@pytest.mark.skipif(not Path(CHROME).exists() and not P.browser_exe(), reason="no Chromium-based browser on this machine")
def test_moth_browser_reads_clicks_and_types_but_never_passwords(site, monkeypatch, tmp_path):
    if Path(CHROME).exists():
        monkeypatch.setenv("MOTH_BROWSER", CHROME)
    monkeypatch.setenv("MOTH_BROWSER_HEADLESS", "1")
    monkeypatch.setattr(P, "_browser", P.Browser(tmp_path / "profile"))
    c = ctx()
    try:
        r = execute_tool(c, "browser_goto", {"url": site + "/"})
        assert r.ok and "Welcome" in r.output and '"Next page"' in r.output, r.output
        items = {line.split(":")[1].strip().split(" ")[0]: int(line.split(":")[0]) for line in r.output.split("into:\n")[1].splitlines()}
        pw = next(int(l.split(":")[0]) for l in r.output.splitlines() if "[password]" in l)
        assert "refused" in execute_tool(c, "browser_type", {"item": pw, "text": "hunter2"}).output
        search = next(int(l.split(":")[0]) for l in r.output.splitlines() if "[text]" in l)
        typed = execute_tool(c, "browser_type", {"item": search, "text": "moth wings", "submit": True})
        assert typed.ok and "/sent?q=moth+wings" in typed.output, typed.output
        assert ("browser_type", typed.output.split("\n")[1] if False else c.approvals.asked[-1][1]) == c.approvals.asked[-1]
        back = execute_tool(c, "browser_goto", {"url": site + "/"})
        link = next(int(l.split(":")[0]) for l in back.output.splitlines() if '"Next page"' in l)
        clicked = execute_tool(c, "browser_click", {"item": link})
        assert clicked.ok and "You are at /two" in clicked.output
        assert [k for k, _ in c.approvals.asked].count("network") == 1  # the site was allowed once
    finally:
        P._browser.close()


def test_this_computer_asks_for_everything_and_never_scans_home(tmp_path, monkeypatch):
    from test_server import H, client  # noqa: F401
    from moth.agent.engine import _whole_computer
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert _whole_computer(tmp_path) and not _whole_computer(tmp_path / "x")
    from moth.agent import tools as T
    c = ctx()
    c.workspace = type("W", (), {"root": tmp_path})()
    (tmp_path / "a.txt").write_text("a")
    r = T.execute_tool(c, "list_files", {})
    assert r.ok and "a.txt" in r.output and c.approvals.asked[0][0] == "read"
    assert not T.execute_tool(c, "search_code", {"query": "x"}).ok


def test_computer_endpoint(paths, monkeypatch, tmp_path):
    from test_server import H, client
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with client(paths) as c:
        r = c.post("/api/computer", headers=H()).json()
        assert r["name"] == "This computer" and r["computer"] and Path(r["path"]) == tmp_path.resolve()
        assert c.post("/api/computer", headers=H()).json()["id"] == r["id"]
