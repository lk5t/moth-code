"""Client/server compatibility.

Every MOTH client declares itself with ``X-Moth-Client: <kind>/<version>`` (``desktop/0.3.0``,
``worker/0.3.0``). The server refuses clients older than the minimum version for their kind with
``426 Upgrade Required`` (``X-Moth-Reason: client_outdated``) *before* the request reaches any
handler, so an outdated client can never write data in a format the server no longer expects.
Clients that send no header are v0.2 desktops; they are treated as ``desktop/0.2.0``.

``API_VERSION`` changes only when the HTTP API changes incompatibly.
"""

from __future__ import annotations

import re
from typing import Any

API_VERSION = 3
# Oldest client of each kind this server still serves. The Owner can raise these (never lower
# them below the built-in floor) from the dashboard once a release has rolled out.
FLOOR = {"desktop": "0.2.0", "worker": "0.2.0"}
LEGACY_CLIENT = ("desktop", "0.2.0")
# Paths an outdated client must still reach so that it can update itself.
EXEMPT_PREFIXES = ("/v1/health", "/v1/updates/", "/v1/worker/update", "/downloads/", "/verify", "/reset", "/r/")

_VER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


def parse_version(v: str) -> tuple[int, int, int]:
    m = _VER.match((v or "").strip())
    if not m:
        raise ValueError(f"not a version: {v!r}")
    return int(m[1]), int(m[2]), int(m[3])


def newer(a: str, b: str) -> bool:
    """True if version a is newer than b."""
    return parse_version(a) > parse_version(b)


def parse_client(header: str | None) -> tuple[str, str] | None:
    if not header:
        return None
    kind, _, version = header.strip().partition("/")
    kind = kind.lower()
    try:
        parse_version(version)
    except ValueError:
        return None
    return (kind, version) if kind in FLOOR else None


def min_versions(ctx: Any) -> dict[str, str]:
    configured = ctx.db.get_config("min_client_versions", {}) or {}
    out = dict(FLOOR)
    for kind, v in configured.items():
        if kind in out:
            try:
                if newer(v, out[kind]):
                    out[kind] = v
            except ValueError:
                pass
    return out


def outdated(ctx: Any, client: tuple[str, str] | None) -> str | None:
    """The minimum version if this client is too old, else None."""
    kind, version = client or LEGACY_CLIENT
    need = min_versions(ctx).get(kind)
    try:
        return need if need and parse_version(version) < parse_version(need) else None
    except ValueError:
        return need
