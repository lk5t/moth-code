"""Two-factor sign-in (1.0): time-based one-time codes (RFC 6238, 30 s, 6 digits, SHA-1) from any
authenticator app. The shared secret is stored server-side only (server_config ``totp:<user id>``)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Any
from urllib.parse import quote

KEY = "totp:{}"
STEP = 30


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def code(secret: str, at: float | None = None) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // STEP)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = digest[-1] & 0x0F
    return f"{(struct.unpack('>I', digest[o:o + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def verify(secret: str, given: str, window: int = 1) -> bool:
    given = "".join(ch for ch in str(given or "") if ch.isdigit())
    if len(given) != 6:
        return False
    now = time.time()
    return any(hmac.compare_digest(code(secret, now + k * STEP), given) for k in range(-window, window + 1))


def uri(secret: str, account: str) -> str:
    return f"otpauth://totp/MOTH:{quote(account)}?secret={secret}&issuer=MOTH&digits=6&period={STEP}"


def state(db, user_id: int) -> dict[str, Any]:
    return db.get_config(KEY.format(user_id), None) or {}


def enabled(db, user_id: int) -> bool:
    return bool(state(db, user_id).get("enabled"))
