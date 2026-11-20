"""Minimal branded web pages opened from emails (verify email, reset password).

Verification uses a confirm button (POST) so link scanners that prefetch URLs cannot
consume one-time tokens.
"""

from __future__ import annotations

import html

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from moth_server.context import Ctx, get_ctx
from moth_server.routes import auth as auth_routes

router = APIRouter(include_in_schema=False)

STYLE = """
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#080808;color:#f2f2f2;
font-family:"Segoe UI",Inter,system-ui,sans-serif}
.card{width:380px;max-width:92vw;background:#141414;border:1px solid #262626;border-radius:14px;padding:32px;
box-shadow:0 0 0 1px rgba(193,18,31,.25),0 0 40px rgba(193,18,31,.12)}
h1{font-size:18px;margin:12px 0 6px;letter-spacing:.02em} p{color:#9a9a9a;font-size:14px;line-height:1.5}
.mark{font-weight:700;letter-spacing:.32em;font-size:13px}.mark span{color:#9a9a9a;font-weight:300;letter-spacing:.2em}
input{width:100%;box-sizing:border-box;margin:6px 0 12px;padding:10px 12px;background:#080808;border:1px solid #333;
border-radius:8px;color:#fff;font-size:14px} input:focus{outline:none;border-color:#C1121F}
button{width:100%;padding:11px;border:0;border-radius:8px;background:#C1121F;color:#fff;font-weight:600;font-size:14px;
cursor:pointer} button:hover{background:#d81e2c;box-shadow:0 0 18px rgba(193,18,31,.45)}
.ok{color:#3fb27f}.err{color:#ff6b75}
"""


def page(title: str, body: str) -> HTMLResponse:
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><meta name="referrer" content="no-referrer"><title>{html.escape(title)} · MOTH Code</title>
<style>{STYLE}</style></head><body><div class="card"><div class="mark">MOTH <span>CODE</span></div>{body}</div></body></html>""",
                        headers={"X-Frame-Options": "DENY", "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'"})


@router.get("/verify")
def verify_page(token: str = ""):
    t = html.escape(token)
    return page("Verify email", f"""<h1>Confirm your email</h1><p>Activate your MOTH Code account.</p>
<form method="post" action="/verify"><input type="hidden" name="token" value="{t}"><button>Verify email</button></form>""")


@router.post("/verify")
def verify_submit(request: Request, token: str = Form(...), ctx: Ctx = Depends(get_ctx)):
    try:
        auth_routes.verify_email(auth_routes.TokenIn(token=token), request, ctx)
    except HTTPException as e:
        return page("Verify email", f'<h1>Verification failed</h1><p class="err">{html.escape(str(e.detail))}</p>')
    return page("Verified", '<h1 class="ok">Email verified</h1><p>You can now sign in to MOTH Code.</p>')


@router.get("/reset")
def reset_page(token: str = ""):
    t = html.escape(token)
    return page("Reset password", f"""<h1>Choose a new password</h1><p>At least 10 characters.</p>
<form method="post" action="/reset"><input type="hidden" name="token" value="{t}">
<input type="password" name="password" placeholder="New password" autocomplete="new-password" required minlength="10">
<button>Set password</button></form>""")


@router.post("/reset")
def reset_submit(request: Request, token: str = Form(...), password: str = Form(...), ctx: Ctx = Depends(get_ctx)):
    try:
        auth_routes.reset_password(auth_routes.ResetIn(token=token, new_password=password), request, ctx)
    except HTTPException as e:
        return page("Reset password", f'<h1>Could not reset</h1><p class="err">{html.escape(str(e.detail))}</p>')
    return page("Password updated", '<h1 class="ok">Password updated</h1><p>Sign in to MOTH Code with your new password.</p>')


@router.get("/status")
def status_page(ctx: Ctx = Depends(get_ctx)):
    """2.4: MOTH at a glance, made for a phone: what is serving, whether it is learning, how many computers help.
    Public on purpose and limited to that: no names, no accounts, no data. Refreshes itself every 30 seconds."""
    import time as _t

    from sqlalchemy import select as _select

    from moth_server import __version__, models as M
    from moth_server.db import workers as W
    from moth_server.evolution import memory as MEM, settings as ES

    cur = M.deployed(ctx)
    info = (cur or {}).get("info") or {}
    cyc = next(iter(MEM.cycles(ctx, 1)), None)
    s = ES.get(ctx)
    t = _t.time()
    online = sum(1 for w in ctx.db.all(_select(W.c.last_heartbeat_at, W.c.revoked_at, W.c.hardware))
                 if w["revoked_at"] is None and (w["last_heartbeat_at"] or 0) >= t - 180)
    running = bool(cyc and cyc["status"] in ("training", "evaluating", "deploying", "monitoring", "planning", "preparing"))
    state = "Paused" if s.get("paused") else "Learning now" if running else "Resting" if s.get("enabled") else "Off"
    last = next((r for r in M.list_releases(ctx) if r.get("deployed_at")), None)

    def ago(ts):
        if not ts:
            return "never"
        m = int((t - ts) // 60)
        return f"{m} min ago" if m < 120 else f"{m // 60} h ago" if m < 2880 else f"{m // 1440} days ago"
    name = html.escape(str(info.get("display_name") or (f"MOTH {info.get('model_version')}" if info.get("model_version") else "No model yet")))
    params = info.get("params")
    rows = [("Model", name), ("Size", f"{params:,} parameters" if isinstance(params, int) else "—"),
            ("Training", f'<span class="{"ok" if running else ""}">{state}</span>' + (f" · {html.escape(cyc['status'].replace('_', ' '))}" if cyc and running else "")),
            ("Computers helping", str(online)), ("Last upgrade", ago((last or {}).get("deployed_at"))), ("MOTH Cloud", html.escape(__version__))]
    body = "<h1>MOTH status</h1><table style='width:100%;font-size:14px;border-collapse:collapse'>" + "".join(
        f"<tr><td style='color:#9a9a9a;padding:6px 0'>{k}</td><td style='text-align:right;padding:6px 0'>{v}</td></tr>" for k, v in rows) + \
        "</table><p style='font-size:12px'>Updates every 30 seconds.</p>"
    r = page("Status", body)
    r.headers["Refresh"] = "30"
    r.headers["Cache-Control"] = "no-store"
    return r
