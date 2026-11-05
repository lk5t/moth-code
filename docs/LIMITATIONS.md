# Known limitations & remaining deployment requirements (v0.2.0)

Everything the README lists as working is implemented and tested. This page lists what still
depends on external infrastructure, what is unfinished, and what has not been verified, so
nothing is overstated.

## Infrastructure the Owner must provide

| Needed | Why | Until then |
| --- | --- | --- |
| A deployed **MOTH Server** on owner-controlled hosting (TLS domain, PostgreSQL, backups) | Accounts, metering, billing, referrals, training coordination, MOTH Cloud | Development: `moth-server serve` locally (SQLite, email outbox). See [SERVER.md](SERVER.md) |
| **SMTP** credentials | Real verification and recovery emails | Emails are written to `data/outbox/` |
| **Stripe** credentials, prices and a webhook | Paid Pro/Max subscriptions | Paid plans show "Coming soon"; checkout returns 503 |
| **GPU capacity** for MOTH Cloud inference, plus a deployed model, plus `cloud_inference_enabled` | MOTH is cloud-only | Chat and the agent report that MOTH Cloud inference is not available yet. The server can serve on CPU for testing only. |
| A published **MOTH Worker release** on the server | One-command enrollment | The app shows the manual `moth-worker enroll` command |
| An initialised **training coordinator** (base model + licensed dataset) | Workers need jobs | Workers stay idle; the UI says no training run is active |
| An updater signing key ([RELEASING.md](RELEASING.md)) and an Authenticode certificate | Signed in-app updates; no SmartScreen warning | Release builds don't offer updates; Windows warns on install |

## Model capability

No well-trained MOTH model exists yet. The only real model trained during development was a
6.2M-parameter `moth-small` (10 minutes on CPU, stdlib code, validation loss ≈4.19). It was
deployed in development to verify the cloud pipeline, and its output is code-like text, not
useful answers. The agent reports "beyond current model" until MOTH-50M is trained at scale
and fine-tuned on agent data.

## Training network

- Verified end to end on CPU only. The development environment has no NVIDIA GPU, so the
  worker's CUDA path, the driver-matched PyTorch install and the RTX 3060 reference
  configuration are untested on real hardware.
- The worker loop and enrollment were verified on Linux. Real rented-GPU providers and
  systemd service startup on a booted machine were not exercised: the unit file is written
  and validated, but the container has no running systemd.
- Aggregation is token-weighted federated averaging with per-update validation and a
  held-out probe loss. Robust aggregation against coordinated poisoning, secure aggregation,
  contributor reputation and large-model sharding are future work. Each round downloads the
  full checkpoint, which is fine at ≤50M parameters.
- Scheduling is first-come. There is no GPU-capability matching beyond "has a GPU".

## Billing

- The Stripe integration is verified with signed test webhooks and a mocked API. It was not
  run against Stripe's real test mode, because no credentials were available here.
- There are no taxes, invoices or emails beyond what Stripe provides. Usage-based overage
  billing is not implemented; usage beyond the allowance draws on earned credits only.

## Accounts

- Changing email address and deleting an account aren't implemented yet. The Owner can
  suspend accounts.
- Rate limits are per IP and per account. Distributed attacks need an upstream WAF.
- In browser development mode (no Tauri), tokens are kept in `sessionStorage` for the tab
  only. The desktop app uses Windows Credential Manager. A real Credential Manager round
  trip is asserted in the Windows CI job; on Linux CI the keyring may be unavailable and that
  test is skipped.

## Desktop

- The terminal is line-oriented, not a full PTY.
- The installer bundles CPU PyTorch for the Owner's local training tools only. Users don't
  need it for inference.
- The Docker image and Compose stack were written and syntax-checked but not built here (no
  Docker in the development environment). The server, backup and restore were verified
  directly with Python, SQLite and PostgreSQL.
