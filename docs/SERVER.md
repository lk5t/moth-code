# MOTH Cloud (MOTH Server) — installation and operations

The MOTH Server is the owner-operated backend for MOTH Code. It is a single deployable
FastAPI application made of separate components:

| Component | Module | Purpose |
| --- | --- | --- |
| Accounts | `routes/auth.py`, `accounts.py` | Registration, verification, login, sessions, recovery, profiles |
| Billing | `billing.py`, `payments.py`, `routes/billing.py` | Plans, usage metering, credit ledger, Stripe checkout/webhooks |
| Referrals | `referrals.py`, `routes/referrals.py` | Codes, attribution, pending rewards, caps, reversals |
| Training coordinator | `training.py`, `routes/training.py` | Worker enrollment, job leases, verified contributions |
| Model registry | `models.py`, `routes/models.py` | Lifecycle, evaluation gate, deployment, rollback |
| MOTH Cloud | `routes/inference.py` | Metered inference with the deployed official MOTH model |
| Administration | `routes/admin.py`, `routes/dashboard.py` | Owner Dashboard API, flags, policy, audit log |
| Updates | `releases.py`, `routes/updates.py`, `deploy/agent/` | Signed releases, desktop/worker update service, server update agent |
| Uploads | `routes/uploads.py`, `evalsets.py` | Resumable model uploads, evaluation datasets |
| System | `routes/system.py` | Owner Dashboard → Server (CPU, RAM, disk, errors) |

After the one-time installation below, MOTH Cloud runs, restarts, backs itself up and updates itself.
Routine operation needs no SSH, no tunnels and no terminal.

## Install once

### Moving the existing VPS over (no data is moved or deleted)

The VPS currently runs `moth-server serve` by hand, reached through an SSH tunnel. To switch it to the
self-managing setup, run these **on the VPS** (as the account that runs MOTH today; administrator rights
are *not* required):

1. Download the release bundle from the GitHub release (`moth-cloud-0.3.0.tar.gz`) and unpack it:

   ```bash
   tar xzf moth-cloud-0.3.0.tar.gz && cd moth-cloud-0.3.0
   ```

2. Find the data directory the current server uses — by default `data/` in the directory where you
   start `moth-server serve` (it contains `moth-server.db`). If you start it with an environment file,
   note its path too.

3. Run the installer, adopting that data directory. Replace the paths and the domain with yours:

   ```bash
   ./deploy/install-server.sh --domain moth.example.com --adopt-data ~/moth/data --replace-running
   ```

   Add `--adopt-env ~/moth/moth-server.env` if you have an environment file (SMTP, Stripe, PostgreSQL),
   and `--github-token-file ~/gh-token.txt` while the repository is private (a fine-grained GitHub
   token with read-only access to this repository's contents, so the server can download releases).

The installer checks Python and disk space, takes a **verified backup** of the existing database,
migrates it, installs the update agent, and sets up supervision so MOTH Cloud survives SSH
disconnects, crashes and reboots. It prints anything that needs an administrator at the end.

### Steps that need an administrator (root)

Only for HTTPS and boot-time startup. The installer prints the exact commands; typically:

- **DNS:** point the domain at the VPS's public IP (A/AAAA record) — at your domain registrar.
- **HTTPS:** install Caddy and use the generated `config/Caddyfile`. Caddy obtains and renews the
  TLS certificate automatically and blocks internal endpoints. Ports 80 and 443 must be open; the API
  port (8900) stays private on 127.0.0.1.
- **Run without a login session:** `sudo loginctl enable-linger <user>` (systemd user services), or
  ensure `cron` is installed (the installer falls back to a cron supervisor that checks every minute
  and at boot).

Without a domain, MOTH Cloud still runs on `127.0.0.1:8900` and updates itself; only the desktop
connection needs the domain.

Then set the repository variable **`MOTH_CLOUD_URL`** to `https://<your domain>` (GitHub → Settings →
Secrets and variables → Actions → Variables) so desktop builds connect automatically (see
[RELEASING.md](RELEASING.md)).

### A fresh server

Same command without `--adopt-data`. As root it installs to `/opt/moth-cloud`, creates a `moth`
system user and systemd services, and configures Caddy and the firewall if they are present.
Create the Owner afterwards (you choose the password; it is never stored anywhere else):

```bash
/opt/moth-cloud/bin/moth server init-owner
```

### Layout

| Path | Contents |
| --- | --- |
| `config/moth.env` | Server settings and secrets (mode 600) |
| `config/agent.json`, `config/agent.token` | Update agent settings and its private API token |
| `data/` (or the adopted directory) | Database, uploads, models, evaluation data, outbox |
| `releases/<version>/`, `current`, `previous` | Installed releases; `current` is what runs |
| `runtime/<hash>/` | Python environments, shared by releases with the same dependencies |
| `agent/` | The update agent's own copy (it updates itself last, with crash protection) |
| `backups/` | Verified backups (before every update, daily, and on request; latest 5 kept) |
| `logs/`, `run/` | Logs and process ids |

## Automatic updates

The update agent checks for new releases every 15 minutes (or immediately with *Check now* in the
Owner Dashboard). For each new **signed** release on the server's channel it:

1. verifies the manifest signature and every file's SHA-256;
2. registers the desktop and worker updates with the server, which hands them to clients in stages;
3. checks disk space and pending migrations — a **destructive** migration waits for your approval in
   Owner Dashboard → Updates;
4. prepares the new Python environment while the old version keeps serving;
5. takes and verifies a database backup;
6. switches `current`, restarts the server (migrations run at startup) and verifies health: version,
   schema, authentication, model registry, and that the deployed model is serving again;
7. on any failure switches back to the previous release — restoring the database backup if the schema
   changed — and reports it (dashboard, error log, email to the Owner);
8. finally updates itself.

An update interrupted by a crash or reboot is finished or rolled back on the agent's next start.
Pause updates, retry a failed version, approve migrations or roll back from **Owner Dashboard → Updates**.

### Operator command (exceptional recovery only)

```bash
~/moth-cloud/bin/moth status
```

Other subcommands: `check` (run one update cycle now), `rollback`, `backup`, `restart`, `logs`,
`supervise`, and `server <moth-server command>` (for example `server init-owner`).

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
| `MOTH_AGENT_TOKEN_FILE`, `MOTH_RELEASE_PUBKEY` | Written by the installer: agent API token file and the release signing public key |
| `MOTH_ENVIRONMENT` | `production`, `staging` or `development` (shown in the dashboard) |

## AI models: publishing, evaluation and deployment

Users never download weights. MOTH Cloud serves the **deployed** official release. Every model goes
through the same states, shown in Owner Dashboard → AI models:

`uploading → uploaded → evaluating → published → deploying → deployed` (or `evaluated` when it passed
every check but scores worse than the active model, or `failed` with the reason and a retry button).

1. **Select & validate (desktop).** Owner → Model packages → *Validate* checks files, metadata,
   checksum, architecture, tokenizer and every tensor shape before anything is uploaded.
2. **Upload.** *Publish to MOTH Cloud* uploads in 8 MB checksummed chunks. Interrupted uploads resume
   (also after closing the app); identical weights are recognised as duplicates. Network training
   checkpoints are registered automatically.
3. **Evaluate (automatic).** The model is loaded in a separate process and actually run: several
   prompts must generate text, and it is scored on held-out **evaluation data**. Passing every check
   publishes it (eligible to deploy). A model scoring worse than the active one waits for *Publish anyway*.
4. **Deploy (you).** MOTH Cloud checks free memory, loads the model on the available hardware (CUDA GPU
   if present, otherwise CPU), runs a real inference health check, and only then switches users to it.
   If anything fails the previous model keeps serving. *Roll back model* returns to the previous one.

### Evaluation data

Earlier versions only accepted the training network's probe set or a hand-made `data/eval/tokens.bin`,
so on a server without a training run every model was rejected with *"no evaluation set is configured"*.
Now:

- **Text datasets** (Owner Dashboard → AI models → Evaluation data → *Upload text*) work with every MOTH
  model: the score is bits per byte using each model's own tokenizer. Upload code or text the models
  were **not** trained on. Files are checked (UTF-8, not binary, at least 4 KB, ≤ 64 MB, no duplicates).
- **Token datasets** (training probe sets) are used only for models with the same tokenizer.
- A **built-in** dataset (a fixed sample of the Python standard library, PSF-2.0) is always available,
  so evaluation is never blocked. The report warns when a model's training data may overlap with it.

Releases that failed only because no evaluation data existed — including ones rejected by v0.2 — are
re-evaluated automatically as soon as data is available, without re-uploading. Evaluation checks are
never skipped.

### Inference hardware

MOTH Cloud detects the hardware and never assumes a GPU. Without one, models are served on CPU (fine
for small models; the dashboard shows the memory a model needs before you deploy it). Enable
`cloud_inference_enabled` in *Policy & flags* when you're ready to serve users.

## Docker Compose (alternative)

`deploy/docker-compose.yml` runs MOTH Cloud with PostgreSQL and Caddy. Docker installations are
updated by pulling a new image rather than by the update agent.

```bash
cp moth-server.env.example moth-server.env
openssl rand -base64 32 > secrets/postgres_password.txt
MOTH_DOMAIN=moth.example.com docker compose up -d
docker compose exec moth-server moth-server init-owner
```

## Where it runs

Production authentication, billing records, model releases, inference and permanent storage
belong on **infrastructure you (the owner) control**: a VPS or dedicated server, with the
database and storage volumes backed up off-host to storage you also control.

The friend's 256 GB RAM server is **optional and replaceable**. Use it for dataset
preparation, or as a temporary training-coordinator host, but never as the only copy of
anything. Whatever it produces (prepared datasets, coordinator checkpoints) is copied back to
owner storage by the backup script below. To move the coordinator, copy its `coordinator/`
directory to the new host and start the server there.

## Training coordinator

Initialise once, from an exported base model and a prepared, properly licensed dataset:

```bash
moth-server training-init --model /path/exported-model --dataset /path/prepared-dataset --shards 32 --steps 200 --min-contributions 4
```

For a quick local experiment, `python scripts/dev-bootstrap-training.py OUT` creates a tiny
base model and a stdlib (PSF-2.0) dataset.

Worker releases are published automatically by the update agent from each signed MOTH release. To
publish one by hand (for example on a server without the agent):

```bash
python scripts/build-worker-release.py --out dist
```

```bash
moth-server worker-release dist/moth-worker-0.3.0.tar.gz --version 0.3.0
```

## Full backups (off-host)

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


The update agent already keeps verified database backups locally (before every update and daily at
03:17). Use `scripts/backup-server.sh` in addition for encrypted, off-host copies that include models
and training data.

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
- **Update agent:** its API (`/v1/agent/*`) needs a random token from a mode-600 file and is
  blocked by the reverse proxy; it answers 404 to everyone else. Releases are installed only if
  their manifest verifies against the pinned ed25519 release key and every file matches its
  SHA-256. The agent never runs code from the release manifest itself.
- **No development endpoints in production:** `/docs` and `/openapi.json` exist only with
  `MOTH_SERVER_DEV=1`; the proxy blocks them as well.
- **Compatibility:** clients send `X-Moth-Client`; versions below the minimum get HTTP 426 before
  any handler runs, so an outdated client can't write data in an old format.
