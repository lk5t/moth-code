# Releasing MOTH (one signed release for every component)

A MOTH release is **one approved, signed set of artifacts** built from one commit:

| Artifact | Who installs it |
| --- | --- |
| `MOTH.Code_<v>_x64-setup.exe` + `.sig` | New users (download) and existing desktops (automatic update) |
| `moth-cloud-<v>.tar.gz` | The MOTH Cloud update agent on the server |
| `moth-worker-<v>.tar.gz` (+ `.sha256`) | MOTH Connect workers (automatic update, and one-command enrollment) |
| `moth-release-<v>.json` + `.sig` | Everything above: versions, SHA-256 of every file, schema/API versions, rollout policy, signed with ed25519 |

Nothing is deployed from arbitrary commits: only the **Release** workflow, started by the Owner, can
produce a signed manifest, and it runs the full test suite first.

## One-time setup

Two signing keys exist: the **release key** (ed25519; signs the manifest the server agent and workers
verify) and the **desktop updater key** (minisign; the Tauri updater verifies every desktop update).
Their public halves are committed (`deploy/agent/release-signing.pub`,
`worker/moth_worker/release-signing.pub`, `app/src-tauri/updater.pub`). The private halves must never
be committed: store them as GitHub Actions secrets.

In GitHub → the repository → **Settings → Secrets and variables → Actions**:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `MOTH_RELEASE_SIGNING_KEY` | the release private key (one line of base64) |
| Secret | `TAURI_SIGNING_PRIVATE_KEY` | the contents of the updater private key file |
| Secret | `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | its password |
| Variable | `MOTH_CLOUD_URL` | the official HTTPS address of MOTH Cloud, e.g. `https://moth.example.com` |
| Variable (optional) | `MOTH_STAGING_URL` | a staging MOTH Cloud for the `beta` channel |

Keep an offline copy of the private keys (a password manager). If the release key is ever lost, a
new public key has to be installed on the server (`MOTH_RELEASE_PUBKEY` in `config/moth.env`) and
workers need to be re-enrolled; desktops would need one manual reinstall if the updater key is lost.

On the server, the update agent needs read access to the releases while the repository is private:
create a fine-grained GitHub token with **read-only Contents** access to this repository and pass it
to the installer with `--github-token-file` (it is stored with mode 600 and never leaves the server).

## Cutting a release

1. Set the same version everywhere: `app/package.json`, `app/src-tauri/tauri.conf.json`,
   `app/src-tauri/Cargo.toml`, `backend/pyproject.toml` + `backend/moth/__init__.py`,
   `server/pyproject.toml` + `server/moth_server/__init__.py`, `worker/pyproject.toml` +
   `worker/moth_worker/__init__.py`. The workflow refuses mismatched versions.
2. If the database schema changed, add a migration to `server/moth_server/db.py` (`MIGRATIONS`) and bump
   `SCHEMA_VERSION`. Mark it destructive if it removes or rewrites data irreversibly: MOTH Cloud then
   waits for the Owner's approval before installing the release.
3. GitHub → Actions → **Release** → *Run workflow* with the tag (e.g. `v0.3.0`) and channel (`stable`,
   or `beta` for a staged pre-release).

The workflow runs all CI jobs (backend on Windows and Linux, server on SQLite and PostgreSQL, worker
install, MOTH Cloud update end-to-end test, frontend, desktop shell), builds the Windows installer with
signed updater artifacts, builds the cloud and worker bundles, signs the manifest and publishes the
GitHub release.

## What happens next (automatically)

- **MOTH Cloud** (within 15 minutes): the agent verifies the release, takes a verified backup, updates
  the server, checks its health and rolls back on failure. The Owner Dashboard → Updates shows progress
  and history.
- **Desktops**: offered in stages (10% → 50% → 100% of installs, six hours apart). Downloads happen in
  the background and install at the next restart. If more than 20% of reported installs fail, the
  rollout halts and the Owner is notified. Pause, resume or release to everyone from the dashboard.
- **Workers**: 25% → 100%; each worker updates between training jobs and reconnects.

A build without the secrets still produces an installer, but it is marked as not updatable and has no
built-in MOTH Cloud address — it is never published as an automatic update.
