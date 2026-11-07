# Changelog

## 0.5.1 — ASCENSION, milestone 2: INTELLIGENCE

MOTH Cloud and MOTH Code 0.5.1. Details: [docs/INTELLIGENCE.md](docs/INTELLIGENCE.md).

- **Intelligence Router:** every chat request goes to the best available model for what it needs
  (benchmarked per capability, then latency), with fallback when a model fails and plain-language
  errors when none can answer. External (OpenAI-compatible) providers are supported but **off by
  default**, and used only for users who allow them.
- **Real streaming chat on MOTH Cloud** (`/v1/chat`): tokens stream as they are generated; optional cloud
  conversation history with delete controls (MOTH Code keeps its history on the computer and asks the
  cloud not to store it).
- **Knowledge Engine:** shared (Owner-approved) and private documents, versioned and deduplicated, BM25
  search, cited answers. Private knowledge is isolated per user.
- **Feedback learning with consent:** rate answers and report what went wrong. Prompts and answers are
  stored only with the user's opt-in; Owner-approved feedback becomes training data.
- **Smart Dataset Library & Data Factory:** eight approved, licensed datasets (TinyStories, Dolly 15k,
  OpenAssistant, Simple English Wikipedia, GSM8K, ARC, MBPP, Python standard library), pinned to exact
  revisions and SHA-256, downloaded once and reused; cleaning, PII scrubbing, quality scoring, benchmark
  decontamination, exact and near-duplicate removal, reproducible manifests, Owner-approved dataset
  updates.
- **Curriculum and Weakness Detection:** staged curriculum with replay and epoch caps; capability
  benchmarks on held-out data (maths, reasoning, executed code, instruction following, held-out loss per
  domain, safety); weaknesses, regressions and recommendations; candidate models must not regress beyond
  sampling noise.
- **Training integrity:** checkpoints carry SHA-256 sidecars; resuming verifies them and falls back to the
  newest intact checkpoint; one trainer per run directory (lock); bf16 training on CPUs with AMX.
- **Safety baseline** on MOTH Cloud (Owner toggle).
- Database schema 5 (new tables only; nothing existing is changed).
- MOTH Code: Settings → Intelligence & privacy (consent switches, models, my knowledge); sources and
  ratings under cloud answers; Owner Dashboard → Intelligence (dataset library, builds, weaknesses and
  curriculum, feedback review, shared knowledge).

## 0.5.0 — ASCENSION, milestone 1: EasyConnect workers, CPU workers, Rewards 2.0

MOTH Cloud, MOTH Code and MOTH Worker 0.5.0 are released together. This is the first of the staged
ASCENSION releases (see [docs/ASCENSION.md](docs/ASCENSION.md)).

- **EasyConnect worker installation:**
  - MOTH Code → Training & Referrals → **Add a computer** gives one command for Linux/macOS and one
    for Windows (PowerShell)
  - it downloads MOTH Worker from your MOTH Cloud, verifies the pinned SHA-256, installs Python
    packages and the right PyTorch (CUDA or CPU), enrolls with a single-use 15-minute token, and
    starts the worker automatically: systemd, cron without sudo, a Windows scheduled task, or launchd
  - crash restarts, a single running instance and a rotating log
  - re-running the command on the same computer replaces its old registration
  - `moth-worker uninstall` removes everything and revokes the worker
  - Windows needs no administrator rights; Python is installed with winget if it is missing
- **Fix:** MOTH Cloud now serves the worker bundle that its update agent relays from signed releases
  (`/downloads/worker/…` returned 404 on 0.4.0 servers).
- **CPU workers are production workers:**
  - no experimental flag (the old "Allow CPU workers" setting is retired)
  - workers report a measured benchmark (GFLOP/s), their CPU and memory
  - jobs are assigned by capability: a worker only gets jobs that fit its memory, and jobs that
    benefit from a GPU wait briefly for an online GPU worker
  - CPU workers use all but one core by default, adjustable per worker in MOTH Code
- **Referral Rewards 2.0:**
  - compute rewards are proportional to the tokens a referred worker actually trained, per verified
    job, after a minimum number of verified jobs
  - signing up, idle workers, failed jobs and repeated claims earn nothing
  - rewards are held for Owner review when a worker is unreliable or its computer is enrolled under
    another account (privacy-preserving machine ids)
  - rewards for a referred user's payment are off by default
  - users see the rules in plain words and each referred worker's contribution and earnings; the
    Owner can approve or reject held rewards
- **Database:** migration 4 (additive): `workers.machine_id`, `workers.trained_tokens`.
- **Tests:** end-to-end worker installation on Linux (CPU-only, cron start, crash recovery, uninstall)
  and on Windows (CI), Rewards 2.0 rules, and an upgrade test from the release production runs
  (server-v0.4.0), including existing worker credentials.

## 0.4.0 — EVOLUTION

MOTH Cloud can now improve its own model, safely and unattended. See [docs/EVOLUTION.md](docs/EVOLUTION.md).

- **Automatic model evolution:**
  - continued training from the deployed model's weights, with its exact architecture; never from
    scratch unless explicitly configured
  - candidates are new versions; the active model is never overwritten
  - resumable, checkpointed training jobs
  - one cycle at a time, scheduled automatically with back-off; evolution pauses itself after
    repeated failures
  - state survives restarts and upgrades
- **Approved training data only:**
  - training uses only datasets the Owner approved, each with a declared license
  - data containing user data needs explicit confirmation that the users gave permission
  - secret-looking files are skipped
  - only hashes, licenses and counts are recorded
  - revoking a dataset stops unfinished experiments that use it
- **Training memory:**
  - runs, reproducible configurations, data used, results, regressions, weaknesses, resource use,
    duration and model lineage are kept in the database
  - experiment planning uses this history: new data first, then measured weaknesses, then learning
    rates that worked before
  - an exact configuration is never run twice
  - event retention is configurable
- **Smart compute manager:**
  - detects CPU, RAM, disk, GPUs and VRAM, and the GPUs of MOTH workers
  - trains on a local GPU, a MOTH GPU worker (existing worker software, new `evolve_train` job), or
    the server's CPU only if enabled
  - only during low activity, within thread, memory, disk and daily-budget limits
  - pauses with a checkpoint when MOTH Cloud gets busy or resources run low, and resumes later
  - without suitable hardware, training waits and says why
- **Experiment laboratory and evaluation gates:**
  - the candidate and the deployed model run the same deterministic benchmarks: held-out score on
    the training data, retention on everything learned before (catastrophic forgetting), Python
    completion validity, optional Owner task suites (reasoning, instruction following, accuracy),
    speed and memory
  - every gate must pass; a lower training loss never counts as an improvement
- **Safe promotion:**
  - the existing checksum and inference health check, then an atomic switch
  - post-deployment monitoring of real error rate and latency, plus health probes
  - automatic rollback to the previous stable model
  - Owner rollback to any earlier compatible version
- **Evolution dashboard** (Owner Dashboard → Evolution):
  - status, active and stable model, cycle and experiments with real progress, evaluation
    comparison, version history with lineage, compute, training data, activity and warnings, and
    settings
- **Database:** migration 3 (additive) adds `training_datasets`, `evolution_cycles`,
  `evolution_experiments`, `evaluation_reports`, `model_lineage` and `evolution_events`; existing
  releases get their lineage recorded.
- **Update agent:** the server's own update and rollback now run before relaying desktop/worker files,
  so a slow download can no longer delay a server update.
- **Fix:** the training network no longer cancels queued jobs of other kinds when a new round starts.

## Server 0.3.2 — reliable release downloads

- **Fix: the update agent could not relay Desktop 0.3.1 to clients.** The VPS logged *“could not fetch
  desktop 0.3.1: MOTH.Code_0.3.1_x64-setup.exe does not match the SHA-256 in the signed manifest”*.
  The release was correct: the signed manifest, GitHub's own digest of the uploaded file, and the
  release workflow's checksums all agree (`19bd549b…`). The agent's download was the problem. When a
  connection dropped part-way through the 129 MB installer, Python's `urllib` returned the partial
  body without an error. The agent then correctly rejected the short file, deleted it, and started
  over 15 minutes later.
- Downloads are now checked against the announced length and the size in the signed manifest, and
  interrupted downloads resume with HTTP Range requests (up to 10 attempts). The SHA-256 and
  signature checks are unchanged. A complete file with different bytes is still refused, and the
  error now reports the received size and hash.
- All components are now version 0.3.2. Desktop 0.3.1 stays the current desktop release: its signed
  artifacts are correct and were not replaced.

## Desktop 0.3.1 / Server 0.3.1 — connection and updates

Fixes *“MOTH Cloud unavailable”* and makes desktop updates work end to end.

- **Editable MOTH Cloud address (Settings → Connection).** Enter any address and choose *Test & use*.
  MOTH Code checks that it really is a MOTH Cloud server before switching. If the same server is
  reachable at the new address, you stay signed in. *Use default* goes back to the built-in address,
  and changing the address never needs a new build. The sign-in dialog shows the address in use. No
  temporary address is built into the release.
- **Clear cloud status.** The status bar says why nothing is served:
  - unreachable (retrying)
  - not a MOTH Cloud server
  - no model deployed yet
  - inference turned off

  Tunnel errors (HTTP 52x) are explained. `/v1/health` now returns `status` and `message`.
- **Server behind a tunnel or proxy.** Download and update links follow the address the client used
  (trusted `X-Forwarded-*` headers), so they work through Cloudflare tunnels. The Owner can set the
  server's public address in the dashboard (Server → Public address). Emails and referral links use
  that address.
- **Model uploads.** Interrupted chunk uploads are retried, with a visible notice (*“HTTP 524 …
  retrying in N s”*). Paused uploads resume by themselves every minute. The upload percentage and size
  are shown. Errors from proxies (HTML pages, 413, 52x) are turned into readable messages.
- **Desktop updates, verified end to end:**
  - the update endpoint follows the configured server address
  - checks run at start-up (not only after the local backend is ready) and every 6 hours
  - the download is verified with the updater key, and downgrades are blocked
  - *Restart now / Later*, installing on close if postponed
  - the local backend is stopped before the installer runs
  - an update log for support
- **Separate desktop and server releases** (`desktop-vX.Y.Z` / `server-vX.Y.Z`, manifest `kind`).
  The update agent installs only server releases on the VPS and relays desktop releases to clients.
- Update agent: stale (zombie) process detection and a single-instance lock.

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
