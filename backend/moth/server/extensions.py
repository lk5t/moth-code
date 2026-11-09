"""Registers routers for optional subsystems.

Each subsystem module exposes ``register(app, services, deps)``. A subsystem
that fails to import (for example PyTorch missing or a broken CUDA install) is
reported through ``/api/subsystems`` instead of crashing the whole backend.
"""

from __future__ import annotations

import importlib
import traceback

SUBSYSTEMS: list[str] = [
    "moth.server.routes_project_intelligence",
    "moth.server.routes_model",
    "moth.server.routes_training",
    "moth.server.routes_agent",
    "moth.server.routes_hybrid",
]
STATUS: dict[str, dict] = {}


def register_all(app, services, deps) -> None:
    for name in SUBSYSTEMS:
        try:
            module = importlib.import_module(name)
            module.register(app, services, deps)
            STATUS[name] = {"ok": True}
        except Exception as e:
            STATUS[name] = {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()}

    @app.get("/api/subsystems", dependencies=deps)
    def subsystems():
        return STATUS
