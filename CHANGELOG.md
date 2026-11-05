# Changelog

## 0.3.0 — SIMPLIFY

MOTH becomes self-managing: install once, sign in, code; everything else updates itself.

- **Automatic connection:**
  - the official MOTH Cloud HTTPS endpoint is built into release builds (no server address, SSH
    tunnel or port on first launch), with production, staging and development environments
  - a developer-only override, hidden under Settings → Advanced
  - background reconnects with exponential backoff, request timeouts and retries
  - a quiet connection status that never pops up
- **Sessions:** session restore, automatic token rotation, clear expiry handling, and version
  compatibility checks (HTTP 426 for outdated clients; older clients can still update).
- **Automatic updates for the whole ecosystem:**
  - Desktop: Tauri updater served by MOTH Cloud with staged rollouts, background download, install
    on restart or exit, and outcome reporting.
  - MOTH Cloud: a standalone update agent with signature verification, verified backups, migration
    checks, health checks, automatic rollback (including database restore), crash and reboot
    recovery, and self-update.
  - Workers: verified self-update between jobs, with automatic revert on failure.
  - Releases: one signed release workflow for every component, release channels, rollouts that halt
    automatically, and deployment history.
- **One-time server installation** (`deploy/install-server.sh`):
  - adopts the existing VPS in place, with no data moved and a backup first
  - works without sudo, listing the administrator steps separately
  - systemd or cron supervision, daily verified backups, Caddy HTTPS with internal endpoints blocked
- **Owner Dashboard:** Server (CPU, RAM, disk, API health, active users, errors), Updates (versions,
  rollouts, deployment history, pause, retry, approve migrations, rollback), AI models (lifecycle,
  evaluation, publish, deploy, rollback, evaluation data) and Workers (CPU/GPU, versions, progress).
- **Model publishing fixed:**
  - *"no evaluation set is configured"* no longer blocks publishing. Evaluation datasets can be
    uploaded and validated in the dashboard, and a built-in held-out text set is always available.
    Text datasets are scored in bits per byte, so models with any tokenizer can be evaluated.
  - Releases rejected for missing data (including v0.2 rejections) are re-evaluated automatically
    without re-uploading.
  - Persistent lifecycle states. Local validation before upload. Resumable, checksummed chunked
    uploads with duplicate detection.
  - Evaluation runs in an isolated process with real inference. Deployment checks resources and runs
    an inference health check first.
  - Interrupted work is recovered after restarts.
- **Desktop UI:** a first-launch flow (sign in → open a workspace → code), one Owner entry in the
  navigation, simpler settings, and a guided Validate → Publish view with live upload progress.
- **Tests:** the new evaluation, publishing, update-service and worker-update suites, plus a real-process
  end-to-end test of installation, adoption, updates, rollback, recovery and reboot.

## 0.2.1

- **Fix: signing in failed with "Not Found"** when the MOTH Server address was typed without `https://`. Addresses
  are now normalised (`moth.example.com` → `https://moth.example.com`, `localhost:8900` → `http://localhost:8900`,
  pasted `/v1/...` paths dropped), and an address that isn't a MOTH Server shows a clear message.
- **Fix:** the desktop app's content security policy only allowed connections to `127.0.0.1`, so an HTTPS MOTH Server
  (and avatars served from it) was blocked in the installed app.

## 0.2.0 — CONNECT

MOTH becomes a cloud service with accounts, usage plans, referrals and a GPU training network.

- **MOTH Server** (new, owner-operated):
  - accounts: Argon2id, email verification and recovery, rate limits, no enumeration, sessions and revocation
  - LK5T Owner with one-time interactive setup and re-authentication for sensitive actions
  - plans with atomic token metering and a credit ledger
  - Stripe subscriptions with verified webhooks (checkout disabled until configured)
  - referrals with pending, capped and reversible rewards
  - training coordinator with worker enrollment, leases and verified contributions
  - model registry with an evaluation gate, deployment and rollback
  - metered MOTH Cloud inference
  - Owner-only server-side content policy, Owner Dashboard API and audit log
- **MOTH Worker** (new): one-command, checksum-pinned Linux GPU enrollment; resumable, resource-limited training;
  systemd service.
- **Desktop:**
  - cloud-only chat and agent with a MOTH account and per-workspace consent
  - Windows Credential Manager sessions, saved accounts and switching
  - Settings → Account, Plan & usage, Referrals
  - Training & Referrals view
  - Owner Dashboard; Owner-only model tools with "Publish to MOTH Cloud"
  - MOTH Cloud status and outage handling
- **Removed** (cloud-only architecture): local inference and model loading, local/auto inference modes, the
  local content-policy editor (now server-side), and the v0.1 Community view (replaced by Training & Referrals).
- **Deployment:** Dockerfile, Compose (PostgreSQL + Caddy TLS), systemd unit, encrypted off-host backups with
  verified restore.
- **CI:** server tests on SQLite and PostgreSQL, Linux worker-install test, Windows Credential Manager test.

## 0.1.0 — Foundation

First release of MOTH Code: the complete pipeline from an empty, randomly initialised network to a desktop coding
agent, with every subsystem implemented and tested. No pretrained model is included.

- Desktop app (Tauri 2, React, TypeScript, Tailwind, shadcn-style UI) with MOTH branding: workspace with chat and
  agent modes, explorer, Monaco editor, terminal, Git changes, activity and memory; training dashboard; models and
  inference; learning network; settings.
- MOTH Model: original decoder-only Transformer, presets up to 400M parameters, MOTH-50M at 49.3M; custom byte-level
  BPE tokenizer.
- Training: license-tracked data, mixed precision on CUDA with CPU fallback, checkpoints with exact resume,
  evaluation, export.
- Owner-defined content policy, separate from always-on operational security.
- Autonomous coding engine with permissions, approvals, verification, memory, retrieval, cancel/resume/revert, and
  honest capability reporting.
- Opt-in community learning protocol with validation and aggregation; hybrid local/cloud inference with consent and
  redaction.
- CI on Windows and Linux; Windows installer with bundled backend; signed in-app updates.

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for what is not finished.
