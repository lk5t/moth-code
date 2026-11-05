"""Password hashing (Argon2id), random tokens, and token hashing."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import unicodedata

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP-recommended Argon2id parameters (19 MiB, t=2, p=1) raised slightly for a server.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2, hash_len=32, salt_len=16)
# A real hash of a random password, used to equalise timing when a user does not exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))

USERNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{1,30})[A-Za-z0-9]$")
RESERVED_USERNAMES = {"lk5t", "admin", "administrator", "owner", "root", "system", "moth", "mothcode", "support",
                      "staff", "moderator", "security", "billing", "api", "null", "undefined"}
OWNER_USERNAME = "LK5T"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    """Constant-ish time: always runs one Argon2 verification."""
    try:
        return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)


def password_problem(password: str, username: str = "", email: str = "") -> str | None:
    if len(password) < 10:
        return "Password must be at least 10 characters."
    if len(password) > 256:
        return "Password is too long."
    low = password.lower()
    if username and username.lower() in low or email and email.split("@")[0].lower() in low:
        return "Password must not contain your username or email."
    if len(set(password)) < 5:
        return "Password is too repetitive."
    return None


def normalize_username(u: str) -> str:
    return unicodedata.normalize("NFKC", u).strip()


def username_problem(username: str) -> str | None:
    if not USERNAME_RE.match(username):
        return "Usernames are 3–32 characters: letters, digits, '.', '_' or '-', starting and ending with a letter or digit."
    return None


def normalize_email(email: str) -> str:
    """Canonical form used for uniqueness (case, +tags, Gmail dots)."""
    email = email.strip().lower()
    local, _, domain = email.partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}"


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def referral_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
    return "".join(secrets.choice(alphabet) for _ in range(8))
