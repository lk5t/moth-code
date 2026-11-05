"""Server configuration from environment variables (see ``deploy/moth-server.env.example``).

Secrets (SMTP password, Stripe keys, webhook secret) are read from the environment
or from ``*_FILE`` paths and are never stored in the repository or sent to clients.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str = "") -> str:
    file_var = os.environ.get(name + "_FILE")
    if file_var and Path(file_var).exists():
        return Path(file_var).read_text().strip()
    return os.environ.get(name, default)


def _bool(name: str, default: bool) -> bool:
    v = _env(name, "")
    return default if v == "" else v.lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    data_dir: Path = Path("./data")
    database_url: str = ""
    public_url: str = "http://127.0.0.1:8900"  # used in emails, referral links and install commands
    cors_origins: list[str] = field(default_factory=lambda: [
        "tauri://localhost", "http://tauri.localhost", "https://tauri.localhost",
        "http://localhost:1420", "http://127.0.0.1:1420"])
    # email
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "MOTH Code <no-reply@localhost>"
    smtp_starttls: bool = True
    # sessions
    session_days_remember: int = 30
    session_hours_short: int = 12
    reauth_minutes: int = 10
    # payments (Stripe-compatible). Checkout stays disabled until configured.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_api_base: str = "https://api.stripe.com"
    # model releases
    signing_key_file: str = ""
    # misc
    trust_proxy_headers: bool = False  # honour X-Forwarded-For only behind your own reverse proxy
    worker_release_manifest: str = ""  # path to the signed worker release manifest (JSON)
    # v0.3 operations
    dev_mode: bool = False  # enables /docs and development conveniences; never in production
    environment: str = "production"  # production | staging | development (shown in health/dashboard)
    agent_token_file: str = ""  # shared secret file of the local update agent (0600)
    release_pubkey: str = ""  # ed25519 public key (base64) that signs MOTH software releases
    max_upload_chunk: int = 16 * 1024 * 1024

    @property
    def db_url(self) -> str:
        return self.database_url or f"sqlite:///{(self.data_dir / 'moth-server.db').resolve()}"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    @property
    def storage_dir(self) -> Path:
        return self.data_dir / "storage"

    @property
    def releases_dir(self) -> Path:
        """Verified software release files (desktop updates, worker bundles) served to clients."""
        return self.data_dir / "storage" / "software"

    @property
    def payments_configured(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_webhook_secret)

    @classmethod
    def from_env(cls) -> "Settings":
        s = cls(
            data_dir=Path(_env("MOTH_SERVER_DATA_DIR", "./data")),
            database_url=_env("MOTH_SERVER_DATABASE_URL"),
            public_url=_env("MOTH_SERVER_PUBLIC_URL", "http://127.0.0.1:8900").rstrip("/"),
            smtp_host=_env("MOTH_SMTP_HOST"),
            smtp_port=int(_env("MOTH_SMTP_PORT", "587")),
            smtp_user=_env("MOTH_SMTP_USER"),
            smtp_password=_env("MOTH_SMTP_PASSWORD"),
            smtp_from=_env("MOTH_SMTP_FROM", "MOTH Code <no-reply@localhost>"),
            smtp_starttls=_bool("MOTH_SMTP_STARTTLS", True),
            stripe_secret_key=_env("MOTH_STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_env("MOTH_STRIPE_WEBHOOK_SECRET"),
            signing_key_file=_env("MOTH_SIGNING_KEY_FILE"),
            trust_proxy_headers=_bool("MOTH_TRUST_PROXY_HEADERS", False),
            worker_release_manifest=_env("MOTH_WORKER_RELEASE_MANIFEST"),
            dev_mode=_bool("MOTH_SERVER_DEV", False),
            environment=_env("MOTH_ENVIRONMENT", "production"),
            agent_token_file=_env("MOTH_AGENT_TOKEN_FILE"),
            release_pubkey=_env("MOTH_RELEASE_PUBKEY"),
        )
        extra = _env("MOTH_SERVER_CORS_ORIGINS")
        if extra:
            s.cors_origins += [o.strip() for o in extra.split(",") if o.strip()]
        return s

    def ensure_dirs(self) -> "Settings":
        for d in (self.data_dir, self.outbox_dir, self.storage_dir, self.releases_dir):
            d.mkdir(parents=True, exist_ok=True)
        return self
