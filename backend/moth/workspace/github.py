"""GitHub connection (1.0): clone, push and open pull requests with the user's own token.

The token is kept by the desktop app in the operating system's credential vault and sent to this local
backend only with each request (``X-GitHub-Token``). It is never written to disk, never put into a remote
URL (``.git/config`` keeps a clean ``https://github.com/…`` address) and never logged: git receives it as a
one-off ``http.extraHeader`` on the command line of that single command.
"""

from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path
from typing import Any

import httpx

from moth.workspace.git import Git, GitError, git_available

API = "https://api.github.com"
REPO = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")


class GitHubError(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    if not token or len(token) > 400:
        raise GitHubError("Connect GitHub first (Settings → Connections).")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "MOTH-Code"}


def _call(method: str, path: str, token: str, **kw) -> Any:
    try:
        r = httpx.request(method, API + path, headers=_headers(token), timeout=20, **kw)
    except httpx.HTTPError as e:
        raise GitHubError(f"GitHub could not be reached: {e}") from None
    if r.status_code == 401:
        raise GitHubError("GitHub did not accept the token. Connect GitHub again in Settings → Connections.")
    if r.status_code >= 400:
        try:
            msg = r.json().get("message") or r.text
        except ValueError:
            msg = r.text
        raise GitHubError(f"GitHub: {msg[:300]}")
    return r.json() if r.content else {}


def user(token: str) -> dict[str, Any]:
    u = _call("GET", "/user", token)
    return {"login": u.get("login"), "name": u.get("name"), "avatar_url": u.get("avatar_url")}


def repos(token: str) -> list[dict[str, Any]]:
    rows = _call("GET", "/user/repos?per_page=100&sort=updated", token)
    return [{"full_name": r["full_name"], "private": r["private"], "default_branch": r.get("default_branch"),
             "description": r.get("description"), "updated_at": r.get("updated_at")} for r in rows]


def _auth_args(token: str) -> list[str]:
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraHeader=Authorization: Basic {basic}"]


def _git(cwd: Path, token: str, *args: str) -> str:
    if not git_available():
        raise GitHubError("Git is not installed. Install Git for Windows to use GitHub.")
    kwargs = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.run(["git", *_auth_args(token), *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600,
                          env={**__import__("os").environ, "GIT_TERMINAL_PROMPT": "0"}, **kwargs)
    out = (proc.stderr or proc.stdout or "").replace(token, "***")
    if proc.returncode != 0:
        raise GitHubError(out.strip()[-500:] or "git failed")
    return out


def clone(token: str, full_name: str, parent: Path) -> Path:
    if not REPO.match(full_name):
        raise GitHubError("Not a GitHub repository name (owner/name).")
    dest = Path(parent) / full_name.split("/")[1]
    if dest.exists():
        raise GitHubError(f"{dest} already exists.")
    _git(Path(parent), token, "clone", f"https://github.com/{full_name}.git", str(dest))
    return dest


def repo_of(root: Path) -> str:
    url = Git(root)._run("remote", "get-url", "origin", check=False).strip()
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
    if not m:
        raise GitHubError("This project's 'origin' is not a GitHub repository.")
    return m.group(1)


def push(token: str, root: Path, branch: str | None = None) -> dict[str, Any]:
    g = Git(root)
    try:
        current = g.branch() or "main"
    except GitError as e:
        raise GitHubError(str(e)) from None
    target = branch or current
    _git(root, token, "push", "-u", "origin", f"HEAD:refs/heads/{target}")
    return {"repo": repo_of(root), "branch": target}


def pull_request(token: str, root: Path, title: str, body: str, base: str | None = None) -> dict[str, Any]:
    full = repo_of(root)
    head = Git(root).branch()
    if not head:
        raise GitHubError("Not on a branch.")
    if not base:
        base = _call("GET", f"/repos/{full}", token).get("default_branch") or "main"
    if head == base:
        raise GitHubError(f"You are on {base}; make a new branch for the pull request first.")
    pr = _call("POST", f"/repos/{full}/pulls", token, json={"title": title[:200], "body": body[:20000], "head": head,
                                                            "base": base})
    return {"number": pr.get("number"), "url": pr.get("html_url")}


USER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")


def invite(token: str, root: Path, username: str) -> dict[str, Any]:
    """1.0 shared projects: invite a friend to this project's GitHub repository (they can push)."""
    if not USER.match(username or ""):
        raise GitHubError("Not a GitHub username.")
    full = repo_of(root)
    _call("PUT", f"/repos/{full}/collaborators/{username}", token, json={"permission": "push"})
    return {"repo": full, "invited": username}


def pull(token: str, root: Path) -> dict[str, Any]:
    """Get your collaborators' latest changes (fast-forward only: never overwrites your own work)."""
    out = _git(root, token, "pull", "--ff-only")
    return {"repo": repo_of(root), "output": out.strip()[-500:]}
