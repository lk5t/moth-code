# MOTH Server — deployment and operations

The MOTH Server is the owner-operated backend for MOTH Code. It is a single deployable
FastAPI application made of separate components:

| Component | Module | Purpose |
| --- | --- | --- |
| Accounts | `routes/auth.py`, `accounts.py` | Registration, verification, login, sessions, recovery, profiles |
| Billing | `billing.py`, `payments.py`, `routes/billing.py` | Plans, usage metering, credit ledger, Stripe checkout/webhooks |
| Referrals | `referrals.py`, `routes/referrals.py` | Codes, attribution, pending rewards, caps, reversals |
| Training coordinator | `training.py`, `routes/training.py` | Worker enrollment, job leases, verified contributions |
| Model registry | `models.py`, `routes/models.py` | Candidates, evaluation gate, deployment, rollback |
| MOTH Cloud | `routes/inference.py` | Metered inference with the deployed official MOTH model |
| Administration | `routes/admin.py`, `routes/dashboard.py` | Owner Dashboard API, flags, policy, audit log |

## Where it runs

Production authentication, billing records, model releases, inference and permanent storage
belong on **infrastructure you (the owner) control**: a VPS or dedicated server, with the
database and storage volumes backed up off-host to storage you also control.

The friend's 256 GB RAM server is **optional and replaceable**. Use it for dataset
preparation, or as a temporary training-coordinator host, but never as the only copy of
anything. Whatever it produces (prepared datasets, coordinator checkpoints) is copied back to
owner storage by the backup script below. To move the coordinator, copy its `coordinator/`
directory to the new host and start the server there.

## Quick start (Docker Compose)

Run these from `deploy/`.

1. Copy the environment template and fill it in (database URL, SMTP, optional Stripe):

   ```bash
   cp moth-server.env.example moth-server.env
   ```

2. Create the database password file. `openssl rand` prints nothing, so the password never
   appears on screen:

   ```bash
   openssl rand -base64 32 > secrets/postgres_password.txt
   ```

   Put the same password into `MOTH_SERVER_DATABASE_URL` in `moth-server.env`.

3. Start the stack:

   ```bash
   MOTH_DOMAIN=moth.example.com docker compose up -d
   ```

4. Create the owner account. This is one-time and interactive: you type LK5T's password and it
   is never stored in files:

   ```bash
   docker compose exec moth-server moth-server init-owner
   ```

Caddy obtains TLS certificates automatically. The server listens only on the internal Docker
network, and PostgreSQL is never exposed.

Without Docker, use `deploy/systemd/moth-server.service` behind your own TLS reverse proxy.

## Owner account

`moth-server init-owner` creates the reserved **LK5T** account with the permanent Owner role.

- It works only once.
- It asks for the password twice (or reads it from stdin with `--password-stdin` for automation).
- It refuses weak passwords.
- No API can create or assign the Owner role.
- Sensitive Owner actions require the password again if more than 10 minutes have passed
  since the last confirmation (HTTP 428 → the desktop app prompts automatically).

## Secrets

All secrets live in the environment. Any variable can instead be given as `VAR_FILE`
pointing to a file, such as a Docker secret. Nothing secret is stored in the repository or
sent to the desktop app.

| Variable | Purpose |
| --- | --- |
| `MOTH_SERVER_DATABASE_URL` | e.g. `postgresql+psycopg://moth:…@postgres:5432/moth` (SQLite is used if unset; development only) |
| `MOTH_SERVER_PUBLIC_URL` | Public HTTPS URL. Used in emails, referral links and worker install commands |
| `MOTH_SMTP_*` | Email delivery. Without SMTP, emails are written to `data/outbox/` (development) |
| `MOTH_STRIPE_SECRET_KEY`, `MOTH_STRIPE_WEBHOOK_SECRET` | Payments. See [BILLING.md](BILLING.md) |
| `MOTH_TRUST_PROXY_HEADERS` | `true` only behind your own reverse proxy (client IPs for rate limits and audit) |
| `MOTH_SERVER_INFERENCE_DEVICE` | `cuda`, `cpu` or `auto` for MOTH Cloud inference |

## MOTH Cloud inference and model deployment

Users never download weights. MOTH Cloud serves the **deployed** official release:

1. **Candidates.** These come from the training network (aggregated checkpoints are packaged
   automatically every 2 minutes, or press *Sync network checkpoints*). The Owner can also
   publish a model from the desktop's *Owner · model packages* view.
2. **Evaluation gate** (*Evaluate*). The package must load and match its checksum, generate
   text, and produce a finite held-out loss no worse than the deployed model's (within 0.02)
   on the evaluation set. The evaluation set is the coordinator's probe tokens, or
   `data/eval/tokens.bin` (uint32 token ids).
3. **Deploy.** The release is loaded and smoke-tested in a new engine before it replaces the
   current one. If that fails, the previous model keeps serving. *Roll back* redeploys the
   previous release. The deployed release is restored on restart. The `auto_deploy_models`
   flag deploys candidates automatically once they pass evaluation.
4. **Enable** `cloud_inference_enabled` in *Flags* once MOTH-operated GPU capacity exists.
   Until then the desktop app honestly reports that MOTH Cloud inference is unavailable.

GPU inference needs a CUDA PyTorch build. Build the image from an NVIDIA CUDA runtime base
and install a `cu12x` PyTorch wheel, or run the systemd variant on a GPU host.

## Training coordinator

Initialise once, from an exported base model and a prepared, properly licensed dataset:

```bash
moth-server training-init --model /path/exported-model --dataset /path/prepared-dataset --shards 32 --steps 200 --min-contributions 4
```

For a quick local experiment, `python scripts/dev-bootstrap-training.py OUT` creates a tiny
base model and a stdlib (PSF-2.0) dataset.

Publish a worker release so users get the one-command installer:

```bash
python scripts/build-worker-release.py --out dist
```

```bash
moth-server worker-release dist/moth-worker-0.2.0.tar.gz --version 0.2.0
```

## Backups

```bash
MOTH_SERVER_DATA_DIR=/data MOTH_SERVER_DATABASE_URL=… MOTH_BACKUP_DIR=/backups MOTH_BACKUP_REMOTE=owner-s3:moth-backups MOTH_BACKUP_GPG_RECIPIENT=you@example.com scripts/backup-server.sh
```

The script backs up:

- a consistent database dump (`pg_dump`, or SQLite's online backup)
- official model releases and worker releases
- training coordinator state (checkpoints, shards, probe set)
- the evaluation set

It writes a `SHA256SUMS` file and can optionally encrypt with GPG and copy off-host with
rclone. Run it daily from cron or a systemd timer.

**Restore.** Extract the archive and check `sha256sum -c SHA256SUMS`. Then restore the
database (`pg_restore`, or copy `database.sqlite` to `data/moth-server.db`), copy `storage/`,
`coordinator/` and `eval/` into the data directory, and start the server. It redeploys the
last deployed release on start.

## Security notes

- **Passwords:** Argon2id (64 MiB, t=3, p=2), rehashed on login if parameters change.
- **Tokens:** sessions, email tokens, enrollment tokens and worker credentials are random and
  stored only as SHA-256 hashes.
- **Credentials:** worker credentials (`mw_…`) cannot call user APIs, and user sessions
  cannot call worker APIs.
- **Rate limits:** database-backed, so they apply across restarts and processes.
  Registration, login (per IP and per username), recovery and verification are all limited.
- **No account enumeration:** registering a duplicate email gives the same response, and the
  account owner is notified instead. Login errors are generic. Recovery always answers the
  same way.
- **Audit log:** every admin action, login, payment webhook and model change is recorded.
- **Uploads:** avatars are validated by magic bytes and limited to 256 KB. Model archives are
  checked for path traversal.
