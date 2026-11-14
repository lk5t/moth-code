"""1.0 connections: GitHub (clone, push, pull requests) with the user's own token (see workspace/github.py)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from moth.server.services import Services
from moth.workspace import github as GH


class CloneIn(BaseModel):
    full_name: str
    parent_dir: str


class PushIn(BaseModel):
    branch: str | None = None


class PrIn(BaseModel):
    title: str
    body: str = ""
    base: str | None = None


def register(app: FastAPI, svc: Services, deps) -> None:
    def run(fn):
        try:
            return fn()
        except GH.GitHubError as e:
            raise HTTPException(400, str(e)) from None

    @app.get("/api/github/user", dependencies=deps)
    def gh_user(x_github_token: str = Header(default="")):
        return run(lambda: GH.user(x_github_token))

    @app.get("/api/github/repos", dependencies=deps)
    def gh_repos(x_github_token: str = Header(default="")):
        return run(lambda: GH.repos(x_github_token))

    @app.post("/api/github/clone", dependencies=deps)
    def gh_clone(body: CloneIn, x_github_token: str = Header(default="")):
        parent = Path(body.parent_dir).expanduser()
        if not parent.is_dir():
            raise HTTPException(400, "Choose an existing folder to clone into.")
        dest = run(lambda: GH.clone(x_github_token, body.full_name, parent))
        return {"path": str(dest)}

    @app.post("/api/projects/{project_id}/github/push", dependencies=deps)
    def gh_push(project_id: int, body: PushIn, x_github_token: str = Header(default="")):
        root = svc.workspace(project_id).root
        out = run(lambda: GH.push(x_github_token, root, body.branch))
        svc.db.log_activity("git", f"Pushed {out['branch']} to GitHub ({out['repo']})", project_id)
        return out

    @app.post("/api/projects/{project_id}/github/pr", dependencies=deps)
    def gh_pr(project_id: int, body: PrIn, x_github_token: str = Header(default="")):
        root = svc.workspace(project_id).root
        out = run(lambda: GH.pull_request(x_github_token, root, body.title, body.body, body.base))
        svc.db.log_activity("git", f"Opened pull request #{out['number']} on GitHub", project_id)
        return out
