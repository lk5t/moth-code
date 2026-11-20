"""2.4.1: MOTH works on the whole computer, not only inside an opened project — always with the user's OK.

* **Files anywhere:** ``pc_list`` / ``pc_read`` ask once per folder per task; ``pc_write`` shows the change and
  asks every time. Files that look like credentials (keys, .env, cloud credentials) are never read or written.
* **Commands anywhere:** ``pc_run`` asks every time and shows the command and folder.
* **The web:** ``web_read`` reads a page as text and ``open_in_browser`` opens a page in the user's own browser;
  each asks once per site per task.
* **MOTH's own browser:** ``browser_goto``/``browser_read``/``browser_click``/``browser_type`` drive a separate
  Edge or Chrome window with its own profile (it never sees the user's logins or cookies) through the browser's
  DevTools protocol on 127.0.0.1. Visiting a new site asks; typing asks every time and shows the text; typing
  into a password field is refused.
"""

from __future__ import annotations

import html as _html
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from moth.security.permissions import Decision, classify_command, is_secret_path

MAX_READ = 200_000
MAX_LIST = 400


class Refused(Exception):
    pass


# ---- approvals --------------------------------------------------------------------------------------------
def _grants(ctx) -> set[str]:
    g = getattr(ctx, "grants", None)
    if g is None:
        g = set()
        try:
            ctx.grants = g
        except AttributeError:
            pass
    return g


def _ask(ctx, kind: str, target: str, reason: str, risk: str = "medium", extra: dict | None = None) -> None:
    from moth.agent.tools import PermissionDenied

    ctx.emit({"kind": "approval_wait", "action": kind, "target": target})
    ok = ctx.approvals.request(kind, target, reason, risk, {"task_id": ctx.task_id, **(extra or {})}, cancel_event=ctx.cancel)
    ctx.emit({"kind": "approval_result", "action": kind, "target": target, "approved": ok})
    if not ok:
        raise PermissionDenied(f"the user did not approve: {kind} {target}")


def _path(raw: str) -> Path:
    p = Path(os.path.expandvars(raw.strip().strip('"'))).expanduser()
    if not p.is_absolute():
        p = Path.home() / p
    p = p.resolve()
    if is_secret_path(p):
        raise Refused(f"{p} looks like a credentials file; MOTH never reads or changes those")
    return p


def _folder_ok(ctx, folder: Path) -> None:
    """Reading in a folder (or below one) the user allowed during this task needs no new question."""
    g = _grants(ctx)
    for allowed in (x[5:] for x in g if x.startswith("read:")):
        if folder == Path(allowed) or Path(allowed) in folder.parents:
            return
    _ask(ctx, "read", str(folder), "MOTH wants to read files in this folder (outside the open project)", "medium")
    g.add(f"read:{folder}")


def _site_ok(ctx, url: str, what: str) -> str:
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise Refused("only http:// and https:// addresses can be opened")
    host = u.hostname.lower()
    if f"site:{host}" not in _grants(ctx):
        _ask(ctx, "network", host, f"MOTH wants to {what} {host}", "medium", {"detail": url})
        _grants(ctx).add(f"site:{host}")
    return host


# ---- files and commands -------------------------------------------------------------------------------------
def pc_list(ctx, a: dict):
    from moth.agent.tools import ToolResult
    p = _path(a.get("path") or str(Path.home()))
    if not p.is_dir():
        return ToolResult(False, f"{p} is not a folder")
    _folder_ok(ctx, p)
    rows = []
    for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:MAX_LIST]:
        try:
            rows.append(e.name + ("/" if e.is_dir() else f"  ({e.stat().st_size:,} bytes)"))
        except OSError:
            continue
    return ToolResult(True, f"{p}\n" + ("\n".join(rows) or "(empty)"))


def pc_read(ctx, a: dict):
    from moth.agent.tools import ToolResult
    p = _path(a["path"])
    if not p.is_file():
        return ToolResult(False, f"{p} is not a file")
    _folder_ok(ctx, p.parent)
    raw = p.read_bytes()[:MAX_READ]
    if b"\x00" in raw[:8192]:
        return ToolResult(False, f"{p} is not a text file")
    lines = raw.decode("utf-8", errors="replace").splitlines()
    start = max(1, int(a.get("start_line", 1)))
    end = min(len(lines), int(a.get("end_line", start + 299)))
    body = "\n".join(f"{i:5d}  {lines[i - 1]}" for i in range(start, end + 1)) if lines else "(empty file)"
    return ToolResult(True, f"{p}\n{body}" + (f"\n[lines {start}-{end} of {len(lines)}]" if end < len(lines) or start > 1 else ""))


def pc_write(ctx, a: dict):
    from moth.agent.tools import ToolResult, _review
    p = _path(a["path"])
    before = p.read_text("utf-8", errors="replace") if p.is_file() else None
    _ask(ctx, "write", str(p), "MOTH wants to " + ("change this file" if before is not None else "create this file"),
         "high" if before is not None else "medium",
         {"detail": a["content"][:2000], "change": _review({"path": str(p), "before": before, "after": a["content"]})})
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(a["content"], "utf-8")
    return ToolResult(True, f"{'updated' if before is not None else 'created'} {p} ({len(a['content'].encode()):,} bytes)",
                      change={"type": "modify" if before is not None else "create", "path": str(p), "before": before, "after": a["content"]})


def pc_run(ctx, a: dict):
    from moth.agent.tools import ToolResult
    from moth.workspace.terminal import run_command
    cwd = _path(a.get("cwd") or str(Path.home()))
    if not cwd.is_dir():
        return ToolResult(False, f"{cwd} is not a folder")
    r = classify_command(a["command"])
    if r.decision == Decision.DENY:
        return ToolResult(False, f"refused: {r.reason}")
    _ask(ctx, "execute", a["command"], f"MOTH wants to run a command in {cwd}" + (f" ({r.reason})" if r.decision != Decision.ALLOW else ""),
         r.risk if r.decision != Decision.ALLOW else "medium", {"detail": f"folder: {cwd}"})
    res = run_command(a["command"], cwd, timeout=float(a.get("timeout", 120)), cancel_event=ctx.cancel,
                      on_output=lambda s: ctx.emit({"kind": "output", "text": s}))
    return ToolResult(res.exit_code == 0, f"exit code {res.exit_code}\n{res.output}")


# ---- the web --------------------------------------------------------------------------------------------------
class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.links: list[str] = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        if tag == "title":
            self._in_title = True
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith("http") and len(self.links) < 40:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skip and data.strip():
            self.out.append(data.strip() + " ")


def page_text(markup: str) -> dict[str, Any]:
    p = _Text()
    p.feed(markup)
    text = "\n".join(line.strip() for line in "".join(p.out).splitlines() if line.strip())
    return {"title": _html.unescape(p.title.strip()), "text": text, "links": p.links}


def web_read(ctx, a: dict):
    from moth.agent.tools import ToolResult
    _site_ok(ctx, a["url"], "read a page on")
    try:
        r = httpx.get(a["url"], timeout=20, follow_redirects=True, headers={"User-Agent": "MOTH-Code"})
    except httpx.HTTPError as e:
        return ToolResult(False, f"could not load the page: {e}")
    if "html" not in r.headers.get("content-type", "html"):
        return ToolResult(True, r.text[:20_000])
    t = page_text(r.text[:2_000_000])
    links = "\n".join(t["links"][:20])
    return ToolResult(r.status_code < 400, f"{t['title']}\n{r.url}\n\n{t['text'][:20_000]}" + (f"\n\nLinks:\n{links}" if links else ""))


def open_in_browser(ctx, a: dict):
    import webbrowser

    from moth.agent.tools import ToolResult
    _site_ok(ctx, a["url"], "open your browser at")
    webbrowser.open(a["url"])
    return ToolResult(True, f"opened {a['url']} in your browser")


# ---- MOTH's own browser (DevTools protocol) -------------------------------------------------------------------
def browser_exe() -> str | None:
    if os.environ.get("MOTH_BROWSER") and Path(os.environ["MOTH_BROWSER"]).is_file():
        return os.environ["MOTH_BROWSER"]
    cands = []
    if sys.platform == "win32":
        for base in (os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"), os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("LOCALAPPDATA", "")):
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    elif sys.platform == "darwin":
        cands += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                  Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
    for c in cands:
        if c.is_file():
            return str(c)
    for name in ("microsoft-edge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    return None


_READ_JS = r"""(() => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  document.querySelectorAll('[data-moth-n]').forEach(e => e.removeAttribute('data-moth-n'));
  const items = []; let n = 0;
  for (const e of document.querySelectorAll('a[href], button, input, textarea, select, [role=button], [role=link], [contenteditable=true]')) {
    if (!vis(e) || n >= 80) continue;
    n++; e.setAttribute('data-moth-n', n);
    const label = (e.innerText || e.value || e.getAttribute('aria-label') || e.placeholder || e.name || e.title || '').trim().slice(0, 80);
    items.push(n + ': ' + e.tagName.toLowerCase() + (e.type ? '[' + e.type + ']' : '') + ' ' + JSON.stringify(label));
  }
  return JSON.stringify({ title: document.title, url: location.href,
    text: (document.body ? document.body.innerText : '').replace(/\n{3,}/g, '\n\n').slice(0, 12000), items });
})()"""


class Browser:
    """One MOTH browser window, started on first use and reused."""

    def __init__(self, profile: Path):
        self.profile = profile
        self.proc: subprocess.Popen | None = None
        self.port = 0
        self._id = 0
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        if self.proc and self.proc.poll() is None:
            return
        exe = browser_exe()
        if not exe:
            raise Refused("no Edge or Chrome found on this computer; install one to let MOTH use a browser")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.profile.mkdir(parents=True, exist_ok=True)
        self.proc = subprocess.Popen([exe, f"--remote-debugging-port={self.port}", "--remote-debugging-address=127.0.0.1",
                                      f"--user-data-dir={self.profile}", "--no-first-run", "--no-default-browser-check",
                                      *(["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]
                                        if os.environ.get("MOTH_BROWSER_HEADLESS") else []),
                                      "--new-window", "about:blank"], stdout=subprocess.DEVNULL,
                                     stderr=open(self.profile / "browser.log", "wb"))  # noqa: SIM115 — closed with the process
        end = time.time() + 45  # a first start (new profile) can take a while on a slow computer
        while time.time() < end:
            if self.proc.poll() is not None:
                err = (self.profile / "browser.log").read_text("utf-8", errors="replace").strip().splitlines()
                raise Refused("MOTH's browser closed while starting" + (f": {err[-1][:200]}" if err else ""))
            try:
                httpx.get(f"http://127.0.0.1:{self.port}/json/version", timeout=1)
                return
            except httpx.HTTPError:
                time.sleep(0.25)
        self.proc.terminate()
        raise Refused("MOTH's browser did not start within 45 seconds")

    def _page_ws(self) -> str:
        pages = [t for t in httpx.get(f"http://127.0.0.1:{self.port}/json", timeout=5).json() if t.get("type") == "page"]
        if not pages:
            pages = [httpx.put(f"http://127.0.0.1:{self.port}/json/new?about:blank", timeout=5).json()]
        return pages[0]["webSocketDebuggerUrl"]

    def call(self, method: str, params: dict | None = None, timeout: float = 30) -> dict:
        from websockets.sync.client import connect

        with self._lock:
            self._ensure()
            with connect(self._page_ws(), max_size=20_000_000, open_timeout=10) as ws:
                self._id += 1
                ws.send(json.dumps({"id": self._id, "method": method, "params": params or {}}))
                end = time.time() + timeout
                while time.time() < end:
                    msg = json.loads(ws.recv(timeout=max(0.1, end - time.time())))
                    if msg.get("id") == self._id:
                        if "error" in msg:
                            raise Refused(f"browser: {msg['error'].get('message')}")
                        return msg.get("result") or {}
        raise Refused("the browser did not answer")

    def eval(self, js: str) -> Any:
        r = self.call("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": True})
        return (r.get("result") or {}).get("value")

    def settle(self, seconds: float = 15) -> None:
        end = time.time() + seconds
        while time.time() < end:
            try:
                if self.eval("document.readyState") == "complete":
                    return
            except Refused:
                pass
            time.sleep(0.3)

    def read(self) -> dict:
        return json.loads(self.eval(_READ_JS) or "{}")

    def close(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


_browser: Browser | None = None


def browser(ctx) -> Browser:
    global _browser
    if _browser is None:
        home = Path(os.environ.get("MOTH_HOME") or Path.home() / ".moth")
        _browser = Browser(home / "browser-profile")
    return _browser


def _shown(page: dict) -> str:
    return f"{page.get('title', '')}\n{page.get('url', '')}\n\n{page.get('text', '')}\n\nThings you can click or type into:\n" + "\n".join(page.get("items", []))


def browser_goto(ctx, a: dict):
    from moth.agent.tools import ToolResult
    _site_ok(ctx, a["url"], "visit")
    b = browser(ctx)
    b.call("Page.navigate", {"url": a["url"]})
    b.settle()
    return ToolResult(True, _shown(b.read()))


def browser_read(ctx, a: dict):
    from moth.agent.tools import ToolResult
    return ToolResult(True, _shown(browser(ctx).read()))


def browser_click(ctx, a: dict):
    from moth.agent.tools import ToolResult
    b = browser(ctx)
    n = int(a["item"])
    href = b.eval(f"(() => {{ const e = document.querySelector('[data-moth-n=\"{n}\"]'); return e && e.href ? e.href : ''; }})()")
    if href:
        _site_ok(ctx, href, "visit")
    ok = b.eval(f"(() => {{ const e = document.querySelector('[data-moth-n=\"{n}\"]'); if (!e) return false; e.scrollIntoView(); e.click(); return true; }})()")
    if not ok:
        return ToolResult(False, f"there is no item {n} on the page; read the page again")
    time.sleep(0.5)
    b.settle()
    return ToolResult(True, _shown(b.read()))


def browser_type(ctx, a: dict):
    from moth.agent.tools import ToolResult
    b = browser(ctx)
    n, text = int(a["item"]), a["text"]
    kind = b.eval(f"(() => {{ const e = document.querySelector('[data-moth-n=\"{n}\"]'); return e ? (e.type || e.tagName).toLowerCase() : ''; }})()")
    if not kind:
        return ToolResult(False, f"there is no item {n} on the page; read the page again")
    if kind == "password":
        return ToolResult(False, "refused: MOTH never types into password fields")
    page = b.read()
    _ask(ctx, "browser_type", page.get("url", ""), f"MOTH wants to type into item {n} on this page" + (" and submit it" if a.get("submit") else ""),
         "high" if a.get("submit") else "medium", {"detail": text[:1000]})
    js = (f"(() => {{ const e = document.querySelector('[data-moth-n=\"{n}\"]'); e.focus();"
          " const proto = e.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
          " const set = Object.getOwnPropertyDescriptor(proto, 'value');"
          f" if (e.isContentEditable) e.innerText = {json.dumps(text)}; else if (set) set.set.call(e, {json.dumps(text)}); else e.value = {json.dumps(text)};"
          " e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));"
          + (" if (e.form) { e.form.requestSubmit ? e.form.requestSubmit() : e.form.submit(); }" if a.get("submit") else "") +
          " return true; })()")
    b.eval(js)
    time.sleep(0.5)
    b.settle()
    return ToolResult(True, _shown(b.read()))


def tools():
    from moth.agent.tools import Tool
    return [
        Tool("pc_list", "list a folder anywhere on this computer (asks once per folder)", {"path": "?string: folder, e.g. ~/Documents"}, pc_list),
        Tool("pc_read", "read a text file anywhere on this computer (asks once per folder)",
             {"path": "string", "start_line": "?integer", "end_line": "?integer"}, pc_read),
        Tool("pc_write", "create or change a file anywhere on this computer (shows the change and asks)", {"path": "string", "content": "string"}, pc_write),
        Tool("pc_run", "run a command in any folder on this computer (asks)", {"command": "string", "cwd": "?string", "timeout": "?integer"}, pc_run),
        Tool("web_read", "read a web page as text (asks once per site)", {"url": "string"}, web_read),
        Tool("open_in_browser", "open a page in the user's own browser (asks once per site)", {"url": "string"}, open_in_browser),
        Tool("browser_goto", "open a page in MOTH's browser and read it (asks once per site)", {"url": "string"}, browser_goto),
        Tool("browser_read", "read the page open in MOTH's browser, with numbered items", {}, browser_read),
        Tool("browser_click", "click a numbered item in MOTH's browser", {"item": "integer"}, browser_click),
        Tool("browser_type", "type into a numbered field in MOTH's browser (asks; never passwords)",
             {"item": "integer", "text": "string", "submit": "?boolean"}, browser_type),
    ]
