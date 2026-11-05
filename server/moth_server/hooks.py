"""In-process hooks so components (e.g. referrals) can react to account events without coupling."""

from __future__ import annotations

from typing import Any, Callable

from moth_server.context import Ctx

HookFn = Callable[..., None]


def register_hook(ctx: Ctx, name: str, fn: HookFn) -> None:
    ctx.extras.setdefault("hooks", {}).setdefault(name, []).append(fn)


def run_hook(ctx: Ctx, name: str, **kwargs: Any) -> None:
    for fn in ctx.extras.get("hooks", {}).get(name, []):
        fn(ctx, **kwargs)
