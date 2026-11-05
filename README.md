<p align="center">
  <img src="branding/moth-icon-1024.png" width="120" alt="MOTH emblem" />
</p>

<h1 align="center">MOTH Code</h1>

<p align="center">An independent AI coding agent for Windows, powered by MOTH — its own neural network, trained from scratch and served from MOTH Cloud.</p>

---

MOTH Code is a desktop development environment with chat, an autonomous coding agent, a project explorer, a Monaco
editor, a terminal and Git. Its intelligence comes **only** from MOTH's own models: original decoder-only Transformers
initialised from random weights. No pretrained weights and no third-party AI APIs are used anywhere.

**v0.2.0 "CONNECT"** makes MOTH a cloud service:

- Everyone, including the Owner, uses the official MOTH model on **MOTH Cloud** through a MOTH account. Usage is
  metered on the server.
- Users never download model weights.
- Anyone can contribute GPU training compute with **MOTH Worker**.
- New checkpoints must pass an evaluation gate before they are deployed for all users.

> **Status.** All of the systems below are implemented and tested. They depend on infrastructure the Owner has to
> provide: a deployed MOTH Server, SMTP, Stripe credentials, and GPU capacity for MOTH Cloud inference. Until that
> exists, the app honestly reports what is unavailable. See [docs/LIMITATIONS.md](docs/LIMITATIONS.md).

## What's in v0.2.0

| Area | What works today |
| --- | --- |
| **Accounts** | Username/password accounts on the owner-operated MOTH Server: Argon2id, email verification, password recovery, rate limits, no account enumeration. Remember Me sessions stored in Windows Credential Manager. Saved accounts and switching, session revocation, profiles and avatars. |
| **Owner (LK5T)** | One-time `init-owner` setup with a password entered interactively. Permanent Owner role that cannot be assigned through the API. Unlimited, unmetered usage. Re-authentication for sensitive actions. Owner Dashboard. |
| **Plans & usage** | Configurable Free/Pro/Max allowances. Atomic reserve-then-settle token metering with no negative balances or double charges. Credit ledger and transaction history. Stripe subscriptions with verified webhooks; checkout stays off until configured. |
| **Referrals** | Codes and share links. Rewards are usage credits only, earned from verified paid invoices or verified GPU training work, with pending periods, caps, reversals, fraud holds and an auditable ledger. |
| **Training network** | One-command, checksum-pinned Linux GPU worker enrollment, isolated worker credentials, job leases, heartbeats, resume after interruption, pause/revoke and GPU limits. Every contribution is verified before it is accepted. |
| **Model deployment** | Candidates come from aggregated checkpoints or Owner uploads. An evaluation gate runs before deploy, with smoke-tested hot swap, automatic rollback, and restore after restart. No weights on user PCs. |
| **Coding agent** | Runs on MOTH Cloud with per-workspace consent before any file content is sent. Includes v0.1's permissions, approvals, verification, memory, cancel, resume and revert. |
| **Desktop app** | Tauri 2 with the black-and-crimson MOTH UI, workspace, Training & Referrals, Plan & usage, Referrals, Owner Dashboard, signed in-app updates, and a themed installer. |
| **MOTH Model** | Original Transformer (MOTH-50M = 49.3M parameters), custom BPE, full training pipeline. Model training tools are Owner-only in the desktop app. |

## Components

| Component | Path | Runs on |
| --- | --- | --- |
| Desktop client | `app/` (Tauri, React) + `backend/` (local tools, agent runtime) | Users' Windows PCs |
| MOTH Server | `server/` (auth, billing, referrals, coordinator, model registry, MOTH Cloud) | Owner-controlled server ([docs/SERVER.md](docs/SERVER.md)) |
| MOTH Worker | `worker/` | Optional Linux GPU servers ([docs/WORKER.md](docs/WORKER.md)) |

## Installer

The Windows installer is themed to match the app. Download it from
[Releases](https://github.com/lk5t/moth-code/releases).

<p>
  <img src="docs/images/installer-welcome.png" width="32%" alt="Installer welcome page" />
  <img src="docs/images/installer-location.png" width="32%" alt="Installer location page" />
  <img src="docs/images/installer-finish.png" width="32%" alt="Installer finish page" />
</p>

## Quick start (development)

Prerequisites: Python 3.10+ (3.12 recommended), Node.js 22+, Rust (stable), Git. On Windows also the
[Tauri prerequisites](https://tauri.app/start/prerequisites/) (WebView2 and the MSVC build tools).

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

For an NVIDIA GPU, install a CUDA build of PyTorch instead (see [docs/SETUP.md](docs/SETUP.md)).

```bash
python -m pip install -e "./backend[dev]"
```

```bash
cd app && npm install && npm run tauri dev
```

`tauri dev` starts the frontend dev server and the desktop shell, which launches the Python backend automatically.

Run a development MOTH Server in another terminal (development mode writes emails to `data/outbox/`):

```bash
python -m pip install -e "./server[dev]"
```

```bash
cd server && moth-server init-owner && moth-server serve
```

Then set the server address in the app (Settings → Account, or `VITE_MOTH_SERVER_URL=http://127.0.0.1:8900`), and
create an account. To serve chat, deploy a model and enable `cloud_inference_enabled` in the Owner Dashboard
([docs/SERVER.md](docs/SERVER.md)).

## Repository layout

```
app/                 Desktop app (React + TypeScript + Tailwind + shadcn-style UI)
app/src-tauri/       Tauri 2 shell (Rust): launches and supervises the backend, updater
backend/moth/        Python backend
  model/             MOTH Transformer, BPE tokenizer, generation, export/registry
  training/          data sources & licenses, dataset prep, trainer, checkpoints, evaluation
  agent/             autonomous coding engine, tools, memory, retrieval
  inference/         local inference, MOTH Cloud client/server, hybrid router
  community/         opt-in learning network: protocol, client, coordinator, validation
  policy/            owner-defined content policy
  security/          permissions, approvals, credential detection/redaction
  workspace/         files, project scanner, terminal, git
  server/            FastAPI HTTP/WebSocket API
backend/tests/       pytest suite
branding/            MOTH emblem (SVG) and icon source
docs/                Architecture, setup, training, security, protocols, releasing, limitations, test results
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [MOTH Server deployment & operations](docs/SERVER.md)
- [MOTH Worker (GPU training)](docs/WORKER.md)
- [Plans, metering & payments](docs/BILLING.md)
- [Setup & building](docs/SETUP.md)
- [Training MOTH models](docs/TRAINING.md)
- [Security, permissions & owner policy](docs/SECURITY.md)
- [Community learning & MOTH Cloud protocols](docs/PROTOCOLS.md)
- [Releasing & signed updates](docs/RELEASING.md)
- [Known limitations & unfinished work](docs/LIMITATIONS.md)
- [Verified test results](docs/TEST_RESULTS.md)

## Tests

```bash
cd backend && python -m pytest -q
```

```bash
cd server && python -m pytest -q
```

```bash
bash scripts/test-worker-install.sh
```

```bash
cd app && npm test && npm run typecheck
```

```bash
cargo test --manifest-path app/src-tauri/Cargo.toml
```

## License

No license has been chosen for this repository yet. Until the owner adds one, default copyright applies.
Training-data licenses are tracked per dataset and recorded in every exported model's manifest.
