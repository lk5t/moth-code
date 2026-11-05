# Known limitations & remaining requirements (v0.3.0)

Everything the README lists as working is implemented and tested (see [TEST_RESULTS.md](TEST_RESULTS.md)).
This page lists what depends on the Owner's infrastructure or accounts, what could not be verified in
the development environment, and what is unfinished — so nothing is overstated.

## Steps only the Owner can do (one time)

| Needed | Why | Where |
| --- | --- | --- |
| A **domain** pointing at the VPS, and **Caddy** (or another TLS proxy) on ports 80/443 | The official HTTPS endpoint desktops connect to | DNS at your registrar; Caddy needs root once ([SERVER.md](SERVER.md#steps-that-need-an-administrator-root)) |
| Run **`install-server.sh`** on the VPS | Switches the existing server to supervised, self-updating operation (adopts its data) | [SERVER.md](SERVER.md#moving-the-existing-vps-over-no-data-is-moved-or-deleted) |
| GitHub **secrets** `MOTH_RELEASE_SIGNING_KEY`, `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` and the variable **`MOTH_CLOUD_URL`** | Signed releases and the built-in endpoint | [RELEASING.md](RELEASING.md) |
| A read-only **GitHub token** on the server (while the repository is private) | The update agent downloads releases | `--github-token-file` |
| **SMTP**, **Stripe**, an Authenticode certificate | Real emails, paid plans, no SmartScreen warning | unchanged from v0.2 |

Until `MOTH_CLOUD_URL` and the signing secrets exist, release builds still work but have no built-in
address (the sign-in screen asks for one) and no automatic desktop updates.

**Desktops already on v0.2.x need one manual install of v0.3.0**, because v0.2 had no working updater.
After that every update is automatic. The same is true for workers enrolled with v0.2.

## Not verified in the development environment

- **Windows:** installing the v0.3.0 setup.exe, upgrading from v0.2.1 on a real PC, and a real
  signed desktop update. CI builds the installer and signed updater artifacts. The update service, the
  staged rollout logic and the client logic are tested, but no Windows machine was available to click
  through an actual update.
- **The live VPS:** it was not touched. The installer and update agent were tested end to end on Linux
  with real processes: adopting a running v0.2.1 server, updates, rollback with database restore,
  recovery after a crash mid-update, and a simulated reboot. They were not run on the actual VPS or
  under real systemd (the container has no systemd). The cron supervisor path was tested.
- **HTTPS:** the Caddy configuration is generated and syntax-correct but was not run against a real
  domain and certificate.
- **GPU:** no NVIDIA GPU was available. CPU inference and CPU workers are tested; the CUDA paths are
  unchanged from v0.2 and untested on hardware.
- **PostgreSQL backups by the agent** need `pg_dump`/`pg_restore` on the server; the agent's backup and
  restore were exercised with SQLite. The server itself is tested on PostgreSQL.

## Model capability

No well-trained MOTH model exists yet. Publishing and deployment now work reliably, but the models
available today (a few million parameters, trained for minutes on CPU) produce code-like text, not
useful answers. The agent reports "beyond current model" until MOTH-50M is trained at scale.

## Design limits

- Staged rollouts use the install's random id; there is no per-region or per-plan targeting.
- The update agent keeps the latest 3 releases and 5 backups locally; off-host backups still use
  `scripts/backup-server.sh` (needs your storage and GPG key).
- Downloads that are interrupted restart from the beginning (desktop) or are retried (server, worker);
  only model uploads resume chunk by chunk.
- Docker installations update by pulling a new image, not through the agent.
- The terminal is line-oriented (not a full PTY). Changing the email address and deleting accounts are
  not implemented.
