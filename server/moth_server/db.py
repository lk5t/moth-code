"""Database schema and access (SQLAlchemy Core; SQLite for development, PostgreSQL in production).

All money-like quantities (tokens, credits) are integers. Balance changes are made with
conditional ``UPDATE … WHERE balance >= n`` statements inside transactions, so they are
atomic and can never go negative, even with concurrent requests.
"""

from __future__ import annotations

import json
import time
import weakref
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey, Index, Integer, LargeBinary, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, event, select, text,
)
from sqlalchemy.engine import Connection, Engine

metadata = MetaData()
SCHEMA_VERSION = 5  # see MIGRATIONS below


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
    Column("client", String(64)),  # e.g. desktop/0.3.0 (compatibility reporting)
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
    Column("source_ref", String(128), index=True),  # e.g. the paid invoice id (for reversals)
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
    Column("update_status", String(64)),
    # 0.5: the computer's anonymised id (duplicate detection) and the total useful work it did
    Column("machine_id", String(64), index=True),
    Column("trained_tokens", BigInteger, nullable=False, default=0),
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
    # uploading | uploaded | evaluating | evaluated | published | deploying | deployed | failed
    Column("status", String(16), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("path", Text, nullable=False),
    Column("info", Text, nullable=False),  # manifest fields (architecture, params, tokenizer, …)
    Column("evaluation", Text),
    Column("created_at", Float, nullable=False),
    Column("published_at", Float),
    Column("published_by", Integer),
    Column("error", Text),
    Column("state_changed_at", Float),
    Column("previously_deployed", Boolean, nullable=False, default=False),
    Column("deployed_at", Float),
)

# ---- v0.3: resumable uploads, software releases, deployments, error log ------------------------
uploads = Table(
    "uploads", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", Integer, nullable=False),
    Column("name", String(128), nullable=False),
    Column("size", BigInteger, nullable=False),
    Column("sha256", String(64), nullable=False, index=True),
    Column("chunk_size", Integer, nullable=False),
    Column("received", Text, nullable=False, default="[]"),  # chunk indexes already stored
    Column("manifest", Text, nullable=False, default="{}"),
    Column("status", String(16), nullable=False),  # uploading | complete | failed | expired
    Column("error", Text),
    Column("release_version", Integer),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

software_releases = Table(
    "software_releases", metadata,
    Column("id", Integer, primary_key=True),
    Column("component", String(16), nullable=False),  # server | desktop | worker
    Column("version", String(32), nullable=False),
    Column("channel", String(16), nullable=False, default="stable"),
    # available | rolling_out | paused | halted | complete | withdrawn
    Column("status", String(16), nullable=False, default="available"),
    Column("rollout_percent", Integer, nullable=False, default=100),
    Column("manifest", Text, nullable=False, default="{}"),
    Column("notes", Text),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    UniqueConstraint("component", "version", name="uq_software_release"),
)

deployments = Table(
    "deployments", metadata,
    Column("id", Integer, primary_key=True),
    Column("component", String(16), nullable=False),
    Column("from_version", String(32)),
    Column("to_version", String(32), nullable=False),
    # started | succeeded | failed | rolled_back | needs_approval | skipped
    Column("status", String(16), nullable=False),
    Column("step", String(64)),
    Column("log", Text, nullable=False, default=""),
    Column("error", Text),
    Column("started_at", Float, nullable=False),
    Column("finished_at", Float),
)

update_reports = Table(
    "update_reports", metadata,
    Column("id", Integer, primary_key=True),
    Column("component", String(16), nullable=False),  # desktop | worker
    Column("client_id", String(64), nullable=False),
    Column("from_version", String(32)),
    Column("to_version", String(32), nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("error", Text),
    Column("created_at", Float, nullable=False),
    Index("ix_update_reports_version", "component", "to_version"),
)

error_log = Table(
    "error_log", metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", Float, nullable=False, index=True),
    Column("source", String(64), nullable=False),
    Column("message", Text, nullable=False),
)


# ---- v0.4: model evolution (approved data, cycles, experiments, evaluations, lineage) ----------------
training_datasets = Table(
    "training_datasets", metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(128), nullable=False),
    Column("path", Text, nullable=False),  # prepared dataset directory (train/val bins + meta.json)
    Column("sha256", String(64), nullable=False),  # of train.bin: identifies the data, never its contents
    Column("tokens_train", BigInteger, nullable=False, default=0),
    Column("tokens_val", BigInteger, nullable=False, default=0),
    Column("tokenizer_fingerprint", String(64), nullable=False),
    Column("license", Text, nullable=False),
    Column("sources", Text, nullable=False, default="[]"),  # source specs and licenses (no contents)
    Column("tags", Text, nullable=False, default="[]"),
    Column("contains_user_data", Boolean, nullable=False, default=False),
    Column("status", String(16), nullable=False),  # pending | approved | revoked
    Column("approved_by", Integer),
    Column("approved_at", Float),
    Column("created_by", Integer),
    Column("created_at", Float, nullable=False),
    Column("revoked_at", Float),
)

evolution_cycles = Table(
    "evolution_cycles", metadata,
    Column("id", Integer, primary_key=True),
    # planning | waiting_for_compute | training | evaluating | deploying | monitoring
    # | completed | rejected | failed | cancelled
    Column("status", String(24), nullable=False, index=True),
    Column("trigger", String(16), nullable=False),  # schedule | manual
    Column("base_version", Integer),
    Column("base_sha256", String(64)),
    Column("plan", Text, nullable=False, default="{}"),
    Column("candidate_version", Integer),
    Column("result", Text, nullable=False, default="{}"),
    Column("error", Text),
    Column("created_at", Float, nullable=False),
    Column("started_at", Float),
    Column("updated_at", Float, nullable=False),
    Column("finished_at", Float),
)

evolution_experiments = Table(
    "evolution_experiments", metadata,
    Column("id", Integer, primary_key=True),
    Column("cycle_id", Integer, nullable=False, index=True),
    # planned | waiting | running | paused | trained | evaluating | passed | rejected | failed | cancelled
    Column("status", String(16), nullable=False, index=True),
    Column("backend", String(16)),  # local | worker
    Column("config", Text, nullable=False),  # reproducible configuration (hyper-parameters, data, base, seed)
    Column("config_hash", String(64), nullable=False, index=True),
    Column("dataset_id", Integer, nullable=False),
    Column("base_version", Integer, nullable=False),
    Column("base_sha256", String(64), nullable=False),
    Column("rationale", Text),
    Column("job_id", Integer),
    Column("worker_id", Integer),
    Column("attempts", Integer, nullable=False, default=0),
    Column("max_attempts", Integer, nullable=False, default=3),
    Column("progress", Float),
    Column("run_dir", Text),
    Column("candidate_version", Integer),
    Column("metrics", Text, nullable=False, default="{}"),
    Column("resources", Text, nullable=False, default="{}"),
    Column("compute_seconds", Float, nullable=False, default=0.0),
    Column("error", Text),
    Column("created_at", Float, nullable=False),
    Column("started_at", Float),
    Column("updated_at", Float, nullable=False),
    Column("finished_at", Float),
)

evaluation_reports = Table(
    "evaluation_reports", metadata,
    Column("id", Integer, primary_key=True),
    Column("model_version", Integer, nullable=False, index=True),
    Column("suite", String(64), nullable=False),
    Column("suite_sha", String(64), nullable=False),
    Column("metrics", Text, nullable=False),
    Column("created_at", Float, nullable=False),
    UniqueConstraint("model_version", "suite_sha", name="uq_eval_report"),
)

model_lineage = Table(
    "model_lineage", metadata,
    Column("version", Integer, primary_key=True),
    Column("parent_version", Integer, index=True),
    Column("method", String(24), nullable=False),  # upload | network | continued | migration | from_scratch
    Column("cycle_id", Integer),
    Column("experiment_id", Integer),
    Column("datasets", Text, nullable=False, default="[]"),
    Column("created_at", Float, nullable=False),
)

evolution_events = Table(
    "evolution_events", metadata,
    Column("id", Integer, primary_key=True),
    Column("ts", Float, nullable=False, index=True),
    Column("cycle_id", Integer, index=True),
    Column("experiment_id", Integer),
    Column("level", String(8), nullable=False),  # info | warning | error
    Column("kind", String(48), nullable=False),
    Column("message", Text, nullable=False),
    Column("data", Text, nullable=False, default="{}"),
)


# ---- 0.5.1 INTELLIGENCE: conversations, knowledge, feedback, dataset library --------------------------
conversations = Table(
    "conversations", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("title", String(120), nullable=False, default=""),
    Column("model", String(64)),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

conversation_messages = Table(
    "conversation_messages", metadata,
    Column("id", Integer, primary_key=True),
    Column("conversation_id", Integer, ForeignKey("conversations.id"), nullable=False, index=True),
    Column("role", String(16), nullable=False),
    Column("content", Text, nullable=False),
    Column("model", String(64)),
    Column("model_version", Integer),
    Column("sources", Text, nullable=False, default="[]"),  # knowledge citations
    Column("stats", Text, nullable=False, default="{}"),
    Column("created_at", Float, nullable=False),
)

knowledge_docs = Table(
    "knowledge_docs", metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", Integer, ForeignKey("users.id"), index=True),  # NULL = shared (Owner-approved) knowledge
    Column("key", String(200), nullable=False),  # stable identity of a document across versions
    Column("title", String(200), nullable=False),
    Column("source", String(500), nullable=False, default=""),
    Column("license", String(64), nullable=False, default=""),
    Column("version", Integer, nullable=False, default=1),
    Column("sha256", String(64), nullable=False),
    Column("status", String(16), nullable=False, default="active"),  # active | superseded | pending | deleted
    Column("chars", Integer, nullable=False, default=0),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
)

knowledge_chunks = Table(
    "knowledge_chunks", metadata,
    Column("id", Integer, primary_key=True),
    Column("doc_id", Integer, ForeignKey("knowledge_docs.id"), nullable=False, index=True),
    Column("ord", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("length", Integer, nullable=False),  # number of terms (BM25 length normalisation)
)

knowledge_terms = Table(
    "knowledge_terms", metadata,
    Column("term", String(48), primary_key=True),
    Column("chunk_id", Integer, ForeignKey("knowledge_chunks.id"), primary_key=True, index=True),
    Column("tf", Integer, nullable=False),
)

feedback = Table(
    "feedback", metadata,
    Column("id", Integer, primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), nullable=False, index=True),
    Column("message_id", Integer),
    Column("model", String(64)),
    Column("model_version", Integer),
    Column("rating", Integer, nullable=False),  # +1 | -1
    Column("category", String(32), nullable=False, default=""),  # wrong | unhelpful | code_error | unsafe | other
    Column("capability", String(24), nullable=False, default="conversation"),
    Column("comment", Text, nullable=False, default=""),
    Column("correction", Text, nullable=False, default=""),
    # prompt/response are stored only when the user consented to training use
    Column("prompt", Text),
    Column("response", Text),
    Column("consent", Boolean, nullable=False, default=False),
    Column("status", String(16), nullable=False, default="new"),  # new | approved | rejected | used
    Column("created_at", Float, nullable=False, index=True),
)

library_builds = Table(
    "library_builds", metadata,
    Column("id", Integer, primary_key=True),
    Column("status", String(16), nullable=False),  # queued | running | ready | failed
    Column("path", String(500)),
    Column("content_sha256", String(64)),
    Column("tokenizer_fingerprint", String(32)),
    Column("manifest", Text, nullable=False, default="{}"),
    Column("error", Text),
    Column("created_at", Float, nullable=False),
    Column("finished_at", Float),
)


# ---- schema migrations ------------------------------------------------------------------------
# ``create_all`` adds new tables; columns and data changes are versioned migrations. A migration
# marked destructive (drops or rewrites data irreversibly) is never applied automatically: it needs
# ``moth-server migrate --approve-destructive`` or Owner approval in the dashboard.
def _add_column(c: Connection, table: str, column: str, ddl: str) -> None:
    cols = {r[1] if c.dialect.name == "sqlite" else r[0] for r in c.execute(text(
        f"PRAGMA table_info({table})" if c.dialect.name == "sqlite" else
        f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table}'"))}
    if column not in cols:
        c.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _m2_lifecycle(c: Connection) -> None:
    """v0.3 model lifecycle: candidate→uploaded, passed→published, rejected→failed, retired→published."""
    _add_column(c, "model_releases", "error", "TEXT")
    _add_column(c, "model_releases", "state_changed_at", "FLOAT")
    _add_column(c, "model_releases", "previously_deployed", "BOOLEAN NOT NULL DEFAULT FALSE")
    _add_column(c, "model_releases", "deployed_at", "FLOAT")
    _add_column(c, "workers", "update_status", "VARCHAR(64)")
    _add_column(c, "sessions", "client", "VARCHAR(64)")
    for old, new in (("candidate", "uploaded"), ("passed", "published"), ("rejected", "failed"), ("retired", "published")):
        extra = ", previously_deployed = TRUE" if old == "retired" else ""
        c.execute(text(f"UPDATE model_releases SET status = :new{extra} WHERE status = :old"), {"new": new, "old": old})
    c.execute(text("UPDATE model_releases SET deployed_at = published_at WHERE status = 'deployed'"))


def _m3_evolution(c: Connection) -> None:
    """v0.4 model evolution: the new tables are created by ``create_all``; record the lineage of every
    existing release (its origin; no parent is invented). Nothing existing is modified or removed."""
    rows = c.execute(text("SELECT version, info, created_at FROM model_releases")).all()
    known = {r[0] for r in c.execute(text("SELECT version FROM model_lineage")).all()}
    for version, info, created in rows:
        if version in known:
            continue
        try:
            src = (json.loads(info or "{}").get("source") or {}).get("type")
        except ValueError:
            src = None
        method = {"training-network": "network"}.get(src or "", "upload")
        c.execute(text("INSERT INTO model_lineage (version, parent_version, method, datasets, created_at) "
                       "VALUES (:v, NULL, :m, '[]', :t)"), {"v": version, "m": method, "t": created or now()})


def _m4_workers(c: Connection) -> None:
    """0.5 workers: anonymised machine id and the amount of verified work (tokens trained)."""
    _add_column(c, "workers", "machine_id", "VARCHAR(64)")
    _add_column(c, "workers", "trained_tokens", "BIGINT NOT NULL DEFAULT 0")
    c.execute(text("CREATE INDEX IF NOT EXISTS ix_workers_machine_id ON workers (machine_id)"))


MIGRATIONS: list[tuple[int, str, bool, Any]] = [
    (2, "v0.3: model lifecycle states, resumable uploads, software releases, deployments", False, _m2_lifecycle),
    (3, "v0.4: model evolution (training datasets, cycles, experiments, evaluation reports, lineage)", False,
     _m3_evolution),
    (4, "v0.5: worker machine id and contribution totals", False, _m4_workers),
    (5, "v0.5.1: conversations, knowledge engine, feedback, dataset library (new tables only)", False,
     lambda c: None),
]


class MigrationApprovalRequired(RuntimeError):
    pass


class Database:
    _instances: "weakref.WeakSet[Database]"

    def __init__(self, url: str):
        Database._instances.add(self)
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

    @classmethod
    def dispose_all(cls) -> None:
        """Close every connection pool (tests create many apps against one PostgreSQL server)."""
        for db in list(cls._instances):
            db.engine.dispose()

    def schema_version(self) -> int:
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)"))
            v = c.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        return int(v) if v is not None else 0

    def pending_migrations(self) -> list[dict]:
        cur = self.schema_version()
        if cur == 0:  # brand-new database: create_all builds the current schema directly
            return []
        return [{"version": v, "description": d, "destructive": destructive}
                for v, d, destructive, _ in MIGRATIONS if v > cur]

    def approved_migrations(self) -> set[int]:
        try:
            return {int(v) for v in (self.get_config("approved_destructive_migrations", []) or [])}
        except Exception:  # noqa: BLE001 — config table may not exist yet on a brand-new database
            return set()

    def migrate(self, approve_destructive: bool = False) -> list[int]:
        """Bring the schema up to date. Returns the migrations applied. Never applies a destructive
        migration without explicit approval (CLI flag, or the Owner approving that migration version
        in the dashboard); raises MigrationApprovalRequired instead."""
        fresh = self.schema_version() == 0
        pending = self.pending_migrations()
        approved = self.approved_migrations()
        blocked = [m for m in pending if m["destructive"] and not approve_destructive and m["version"] not in approved]
        if blocked:
            raise MigrationApprovalRequired(
                "destructive migration(s) need Owner approval: " + ", ".join(f"{m['version']} ({m['description']})"
                                                                            for m in blocked))
        metadata.create_all(self.engine)
        applied = []
        if fresh:
            with self.engine.begin() as c:
                c.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": SCHEMA_VERSION})
            return applied
        for v, _d, _destructive, fn in MIGRATIONS:
            if v in {m["version"] for m in pending}:
                with self.engine.begin() as c:  # each migration is its own transaction
                    fn(c)
                    c.execute(text("INSERT INTO schema_version (version) VALUES (:v)"), {"v": v})
                applied.append(v)
        return applied

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


Database._instances = weakref.WeakSet()
