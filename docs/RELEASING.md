# Releasing MOTH (signed desktop and server releases)

Since 0.3.1 there are **two kinds of release**, published by separate workflows so that a desktop
update never touches the server and a server update never changes the desktop:

| Kind | Workflow | Tag | Contents |
| --- | --- | --- | --- |
| Desktop | **Desktop release** (`release.yml`) | `desktop-vX.Y.Z` | `MOTH.Code_<v>_x64-setup.exe` + `.sig`, `moth-release-desktop-<v>.json` + `.sig`, `SHA256SUMS` |
| Server | **Server release** (`server-release.yml`) | `server-vX.Y.Z` | `moth-cloud-<v>.tar.gz`, `moth-worker-<v>.tar.gz`, `moth-release-<v>.json` + `.sig` |

The manifest's `kind` field (`desktop` or `server`) says which is which. The MOTH Cloud update agent
installs only server releases on the VPS and relays desktop releases to the server, which offers them
to desktops. The artifacts:

| Artifact | Who installs it |
| --- | --- |
| `MOTH.Code_<v>_x64-setup.exe` + `.sig` | New users (download) and existing desktops (automatic update) |
| `moth-cloud-<v>.tar.gz` | The MOTH Cloud update agent on the server |
| `moth-worker-<v>.tar.gz` (+ `.sha256`) | MOTH Connect workers (automatic update, and one-command enrollment) |
| `moth-release-<v>.json` + `.sig` | Everything above: versions, SHA-256 of every file, schema/API versions, rollout policy, signed with ed25519 |

Nothing is deployed from arbitrary commits: only these workflows, started by the Owner, can produce a
signed manifest, and they run the full test suite first. The desktop workflow also runs the **Windows
auto-update end-to-end test** (`desktop-update-test.yml`) and refuses to publish if it fails.

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
| Variable (optional) | `MOTH_CLOUD_URL` | the default HTTPS address of MOTH Cloud, e.g. `https://moth.example.com`. Only set it to a permanent address — never a temporary tunnel. Users can always change the address in Settings → Connection without a new build |
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
3. Server: GitHub → Actions → **Server release** → *Run workflow* with the tag (e.g. `server-v0.3.1`).
4. Desktop: GitHub → Actions → **Desktop release** → *Run workflow* with the tag (e.g. `desktop-v0.3.1`).
   Channel `stable`, or `beta` for a staged pre-release.

Both run all CI jobs (backend on Windows and Linux, server on SQLite and PostgreSQL, worker install,
MOTH Cloud update end-to-end test, frontend, desktop shell). The desktop workflow then runs the Windows
auto-update test, builds the installer with signed updater artifacts and signs a desktop manifest; the
server workflow builds the cloud and worker bundles and signs a server manifest. Each manifest is
verified before the GitHub release is published, and an existing tag is never overwritten.

**Upgrading from 0.3.0:** publish `server-v0.3.1` first and wait until the Owner Dashboard → Updates
shows MOTH Cloud 0.3.1. A 0.3.0 server stores manifests by version number only, so it cannot hold a
desktop and a server release with the same version; 0.3.1 servers store them separately.

## What happens next (automatically)

- **MOTH Cloud** (within 15 minutes): the agent verifies the release, takes a verified backup, updates
  the server, checks its health and rolls back on failure. The Owner Dashboard → Updates shows progress
  and history.
- **Desktops**: each desktop checks the MOTH Cloud address it is connected to (Settings → Connection)
  5 seconds after start and every 6 hours. Updates are offered in stages (10% → 50% → 100% of installs, six hours apart). Downloads happen in
  the background. Each one is verified against the updater key built into the app, and the app then
  shows *“MOTH Code X is ready — Restart now / Later”*; if the user chooses Later, it installs when the
  app closes. `%APPDATA%\dev.mothcode.desktop\logs\updates.log` records every step. If more than 20% of reported installs fail, the
  rollout halts and the Owner is notified. Pause, resume or release to everyone from the dashboard.
- **Workers**: 25% → 100%; each worker updates between training jobs and reconnects.

A build without the signing secrets still produces an installer, but it is marked as not updatable and is
never published as an automatic update. A build without `MOTH_CLOUD_URL` asks for the server address
on first start.
