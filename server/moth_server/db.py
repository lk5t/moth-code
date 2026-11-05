"""Database schema and access (SQLAlchemy Core; SQLite for development, PostgreSQL in production).

All money-like quantities (tokens, credits) are integers. Balance changes are made with
conditional ``UPDATE … WHERE balance >= n`` statements inside transactions, so they are
atomic and can never go negative, even with concurrent requests.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey, Index, Integer, LargeBinary, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, event, select, text,
)
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()
SCHEMA_VERSION = 1


def now() -> float:
    return time.time()


# ---- accounts (phase 1) -------------------------------------------------------------
users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(32), nullable=False),
    Column("username_lc", String(32), nullable=False, unique=True),
    Column("email", String(254), nullable=False),
    Column("email_normalized", String(254), nullable=False, unique=True),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(16), nullable=False, default="user"),  # user | admin | owner
    Column("status", String(16), nullable=False, default="active"),  # active | suspended
    Column("email_verified_at", Float),
    Column("display_name", String(64)),
    Column("avatar", LargeBinary),
    Column("avatar_type", String(32)),
    Column("settings", Text, nullable=False, default="{}"),
    Column("referral_code", String(16), nullable=False, unique=True),
    Column("referred_by", Integer, ForeignKey("users.id")),
    Column("credit_balance", BigInteger, nullable=False, default=0),
    Column("plan_code", String(16), nullable=False, default="free"),
    Column("registration_ip", String(64)),
    Column("created_at", Float, nullable=False),
    Column("last_login_at", Float),
)

sessions = Table(
    "sessions", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("remember", Boolean, nullable=False, default=True),
    Column("device_name", String(128)),
    Column("user_agent", String(256)),
    Column("ip", String(64)),
    Column("created_at", Float, nullable=False),
    Column("last_used_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("revoked_at", Float),
    Column("reauth_at", Float),
)

email_tokens = Table(
    "email_tokens", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("purpose", String(16), nullable=False),  # verify | reset
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("used_at", Float),
)

rate_events = Table(
    "rate_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("key", String(200), nullable=False),
    Column("ts", Float, nullable=False),
    Index("ix_rate_events_key_ts", "key", "ts"),
)

audit_log = Table(
    "audit_log", metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", Float, nullable=False, index=True),
    Column("actor_id", Integer),
    Column("action", String(64), nullable=False),
    Column("target", String(128)),
    Column("detail", Text),
    Column("ip", String(64)),
)

server_config = Table(
    "server_config", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", Text, nullable=False),
    Column("updated_at", Float, nullable=False),
)

# ---- billing & usage (phase 2) ------------------------------------------------------------
plans = Table(
    "plans", metadata,
    Column("code", String(16), primary_key=True),  # free | pro | max
    Column("name", String(64), nullable=False),
    Column("price_cents", Integer, nullable=False, default=0),
    Column("currency", String(8), nullable=False, default="usd"),
    Column("interval", String(16), nullable=False, default="month"),
    Column("monthly_tokens", BigInteger, nullable=False, default=0),
    Column("priority", Integer, nullable=False, default=0),
    Column("features", Text, nullable=False, default="{}"),
    Column("provider_price_id", String(128)),
    Column("checkout_enabled", Boolean, nullable=False, default=False),
    Column("sort", Integer, nullable=False, default=0),
    Column("updated_at", Float, nullable=False),
)

subscriptions = Table(
    "subscriptions", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("plan_code", String(16), nullable=False),
    Column("status", String(24), nullable=False),  # incomplete | active | past_due | canceled
    Column("provider", String(16), nullable=False, default="stripe"),
    Column("provider_customer_id", String(128)),
    Column("provider_subscription_id", String(128), unique=True),
    Column("current_period_start", Float),
    Column("current_period_end", Float),
    Column("cancel_at_period_end", Boolean, nullable=False, default=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

usage_periods = Table(
    "usage_periods", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("period_start", Float, nullable=False),
    Column("period_end", Float, nullable=False),
    Column("allowance", BigInteger, nullable=False),
    Column("used", BigInteger, nullable=False, default=0),
    Column("plan_code", String(16), nullable=False),
    UniqueConstraint("user_id", "period_start", name="uq_usage_period"),
)

usage_events = Table(
    "usage_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("request_id", String(64), nullable=False, unique=True),  # idempotency: one charge per request
    Column("status", String(16), nullable=False),  # reserved | settled | released
    Column("model", String(128)),
    Column("reserved_allowance", BigInteger, nullable=False, default=0),
    Column("reserved_credits", BigInteger, nullable=False, default=0),
    Column("input_tokens", BigInteger, nullable=False, default=0),
    Column("output_tokens", BigInteger, nullable=False, default=0),
    Column("charged_allowance", BigInteger, nullable=False, default=0),
    Column("charged_credits", BigInteger, nullable=False, default=0),
    Column("period_id", Integer),
    Column("unmetered", Boolean, nullable=False, default=False),
    Column("created_at", Float, nullable=False),
    Column("settled_at", Float),
)

credit_ledger = Table(
    "credit_ledger", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("amount", BigInteger, nullable=False),  # +grant / -spend
    Column("kind", String(32), nullable=False),  # referral_reward | gpu_referral_reward | admin_adjustment | usage | reversal
    Column("reference", String(128)),
    Column("idempotency_key", String(128), nullable=False, unique=True),
    Column("balance_after", BigInteger, nullable=False),
    Column("note", Text),
    Column("actor_id", Integer),
    Column("created_at", Float, nullable=False),
)

payment_events = Table(
    "payment_events", metadata,
    Column("id", String(128), primary_key=True),  # provider event id (dedupe)
    Column("type", String(64), nullable=False),
    Column("received_at", Float, nullable=False),
    Column("processed_at", Float),
    Column("outcome", Text),
)

# ---- referrals (phase 3) -----------------------------------------------------------------
referrals = Table(
    "referrals", metadata,
    Column("id", Integer, primary_key=True),
    Column("referrer_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("referred_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("status", String(16), nullable=False),  # registered | qualified | rewarded | reversed | review | rejected
    Column("flags", Text, nullable=False, default="[]"),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

referral_rewards = Table(
    "referral_rewards", metadata,
    Column("id", Integer, primary_key=True),
    Column("referrer_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("kind", String(16), nullable=False),  # user | gpu
    Column("referral_id", Integer, ForeignKey("referrals.id")),
    Column("worker_id", Integer),
    Column("qualifying_ref", String(128), nullable=False, unique=True),  # one reward per qualifying event
    Column("amount", BigInteger, nullable=False),
    Column("status", String(16), nullable=False),  # pending | credited | reversed | capped | rejected
    Column("available_at", Float, nullable=False),
    Column("ledger_id", Integer),
    Column("reason", Text),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

# ---- training network & models (phase 4) ----------------------------------------------------
enrollment_tokens = Table(
    "enrollment_tokens", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("referral_code", String(16)),
    Column("worker_name", String(64)),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("used_at", Float),
)

workers = Table(
    "workers", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(64), nullable=False),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("status", String(16), nullable=False, default="offline"),  # online | offline | revoked
    Column("paused", Boolean, nullable=False, default=False),
    Column("hardware", Text, nullable=False, default="{}"),
    Column("limits", Text, nullable=False, default="{}"),
    Column("version", String(32)),
    Column("referrer_id", Integer),
    Column("verified_jobs", Integer, nullable=False, default=0),
    Column("failed_jobs", Integer, nullable=False, default=0),
    Column("enrolled_at", Float, nullable=False),
    Column("last_heartbeat_at", Float),
    Column("revoked_at", Float),
)

training_jobs = Table(
    "training_jobs", metadata,
    Column("id", Integer, primary_key=True),
    Column("kind", String(24), nullable=False),  # train_round
    Column("status", String(16), nullable=False),  # queued | leased | completed | failed | cancelled
    Column("spec", Text, nullable=False),
    Column("worker_id", Integer, index=True),
    Column("lease_expires_at", Float),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=3),
    Column("progress", Float),
    Column("result", Text),
    Column("error", Text),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

model_releases = Table(
    "model_releases", metadata,
    Column("id", Integer, primary_key=True),
    Column("version", Integer, nullable=False, unique=True),
    Column("name", String(128), nullable=False),
    Column("channel", String(16), nullable=False, default="stable"),
    Column("status", String(16), nullable=False),  # draft | published | revoked
    Column("sha256", String(64), nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("path", Text, nullable=False),
    Column("info", Text, nullable=False),  # manifest fields (architecture, params, tokenizer, …)
    Column("evaluation", Text),
    Column("created_at", Float, nullable=False),
    Column("published_at", Float),
    Column("published_by", Integer),
)


class Database:
    def __init__(self, url: str):
        kwargs: dict[str, Any] = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        else:
            kwargs["pool_pre_ping"] = True
        self.engine: Engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _pragmas(dbapi_conn, _):  # noqa: ANN001
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.close()
        self.is_sqlite = url.startswith("sqlite")

    def migrate(self) -> None:
        metadata.create_all(self.engine)
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
            v = c.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
            if v is None:
                c.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": SCHEMA_VERSION})

    @contextmanager
    def tx(self) -> Iterator[Connection]:
        """A transaction. On SQLite, BEGIN IMMEDIATE serialises writers (no lost updates)."""
        with self.engine.connect() as conn:
            if self.is_sqlite:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
                try:
                    yield conn
                    conn.exec_driver_sql("COMMIT")
                except BaseException:
                    conn.exec_driver_sql("ROLLBACK")
                    raise
            else:
                with conn.begin():
                    yield conn

    def one(self, stmt, conn: Connection | None = None) -> dict | None:
        if conn is not None:
            row = conn.execute(stmt).mappings().first()
        else:
            with self.engine.connect() as c:
                row = c.execute(stmt).mappings().first()
        return dict(row) if row else None

    def all(self, stmt, conn: Connection | None = None) -> list[dict]:
        if conn is not None:
            return [dict(r) for r in conn.execute(stmt).mappings().all()]
        with self.engine.connect() as c:
            return [dict(r) for r in c.execute(stmt).mappings().all()]

    # ---- config ---------------------------------------------------------------------
    def get_config(self, key: str, default: Any = None) -> Any:
        row = self.one(select(server_config.c.value).where(server_config.c.key == key))
        return json.loads(row["value"]) if row else default

    def set_config(self, key: str, value: Any, conn: Connection | None = None) -> None:
        def write(c: Connection) -> None:
            exists = c.execute(select(server_config.c.key).where(server_config.c.key == key)).first()
            if exists:
                c.execute(server_config.update().where(server_config.c.key == key)
                          .values(value=json.dumps(value), updated_at=now()))
            else:
                c.execute(server_config.insert().values(key=key, value=json.dumps(value), updated_at=now()))
        if conn is not None:
            write(conn)
        else:
            with self.tx() as c:
                write(c)
