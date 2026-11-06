# Verified test results

Everything below was actually run. Commands are listed so the results can be reproduced.

# Desktop 0.3.1 / Server 0.3.1

## Automated suites (Linux x86-64)

| Suite | Command | Result |
| --- | --- | --- |
| MOTH Server | `cd server && python -m pytest -q` | **65 passed** |
| Desktop backend | `cd backend && python -m pytest -q` | **105 passed** |
| Frontend | `cd app && npx tsc -b && npm test && npm run build` | typecheck ok, **19 passed**, build ok |
| Rust shell | `cargo test` | **6 passed** (adds the update-endpoint test) |
| Ecosystem end-to-end | `python scripts/test-ecosystem-update.py` | **PASS, all 11 steps** |

GitHub Actions CI [run 28](https://github.com/lk5t/moth-code/actions/workflows/ci.yml) passed every job.

New tests:

| Test | What it proves |
| --- | --- |
| `test_desktop_and_server_releases_are_separate` | A desktop release is never offered to the server agent, and a server release is never offered to desktops. Both can have the same version. |
| `test_update_links_follow_the_address_the_client_used` | Through a proxy or tunnel (`X-Forwarded-Proto/Host`), the desktop download URL uses the tunnel address, not the internal one. |
| `test_owner_can_change_the_public_address` | Only an Owner who signed in again recently can set the public address, and it must be HTTPS. |
| `test_cloud_health_explains_why_nothing_is_served` / `test_cloud_status_explains_why_nothing_is_served` | The server reports `no_model_deployed`, then `inference_disabled`, then `ready`. The desktop backend passes the reason through to the UI. |
| `test_upload_shows_a_retry_notice_during_interruptions` | An HTTP 524 page and a dropped connection mid-upload are retried, a notice is shown, and publishing completes. |

## Windows auto-update, end to end ([`desktop-update-test.yml`](../.github/workflows/desktop-update-test.yml))

Run [42187948122](https://github.com/lk5t/moth-code/actions/runs/42187948122) (commit `19f2a34`)
on `windows-latest` **passed**. Real installers, a real MOTH Server and a real NSIS installation were
used. Nothing was mocked:

1. Version A (0.3.1) and version B (0.3.99) were built with `tauri build`, signed with throw-away
   test keys.
2. A signed desktop manifest for B was built and verified with `verify-release.py`.
3. B was registered with a running MOTH Server through the update-agent API, exactly as the agent
   does. The server re-verified it and offered 0.3.99 to 0.3.1.
4. A was installed silently, user data was written to `%APPDATA%\MOTH Code`, and A was started.
5. A found, downloaded and verified B **by itself** and installed it. The registry now reports
   0.3.99. App log: `MOTH Code 0.3.1 started` → `update available: 0.3.99` → `downloaded and verified
   0.3.99 (5752675 bytes)` → `installing 0.3.99` → `MOTH Code 0.3.99 started` → `up to date`.
6. B started and reported a successful update to the server, and the user data was preserved.

The test builds differ from releases in only two ways: they use a loopback `http://` server, and they
install the downloaded update without waiting for the user to click *Restart now*. The release
workflow runs this test before every desktop release.

## Live verification in the browser (real MOTH Server and desktop backend)

These checks ran through a deliberately faulty “tunnel” proxy that injected five HTTP 524 errors and
three dropped connections:

- An address that is not a MOTH Cloud server was rejected with a reason, and the tunnel address was
  accepted.
- The status bar showed *no model deployed yet*, then *inference turned off*, then the model name.
- The 90 MB MOTH-50M package was published through the failures (with visible retry notices),
  evaluated, deployed and used in chat.
- Switching to another address of the same server kept the user signed in.

## Not verified here (0.3.1)

- Installing on the Owner's own PC, and the one manual upgrade from v0.2.1.
- The live VPS and `https://mothcloud.ddns.net` (HTTPS is not configured for that domain yet). The
  Cloudflare tunnel address was not used from this environment.
- A desktop update signed with the **production** updater key. The production key was checked by the
  `check-secrets` workflow; the end-to-end update test uses throw-away keys.

# v0.3.0 — SIMPLIFY

## Automated suites (Linux x86-64, 4 CPU threads, no GPU, Python 3.13, PyTorch CPU)

| Suite | Command | Result |
| --- | --- | --- |
| MOTH Server | `cd server && python -m pytest -q` | **60 passed** (46 from v0.2, 14 new) |
| Desktop backend | `cd backend && python -m pytest -q` | **104 passed** |
| Frontend | `cd app && npx tsc -b && npm test && npm run build` | typecheck ok, **19 passed**, build ok |
| Rust shell | `cargo test` | **5 passed** |
| **Ecosystem end-to-end** (real processes) | `python scripts/test-ecosystem-update.py` | **PASS, all 11 steps** |
| MOTH Worker one-command install | `bash scripts/test-worker-install.sh` | **PASS** |

GitHub Actions CI [run 23](https://github.com/lk5t/moth-code/actions/runs/42113035558) (commit `d088cb7`) passed all
nine jobs: backend on Ubuntu and Windows, server on SQLite and **PostgreSQL 16**, worker install, the MOTH
Cloud install/update/rollback/recovery end-to-end test, frontend, and the desktop shell on Ubuntu and Windows.

## Model publishing and the evaluation fix

The reported failure was `ReleaseError: no evaluation set is configured (coordinator probe or
data/eval/tokens.bin)`. v0.2 evaluated only against the training coordinator's probe tokens or a
hand-placed `tokens.bin`, so a server without a training run rejected every model.

| Test | What it proves |
| --- | --- |
| `test_v02_rejected_model_is_recovered_without_reupload` | A database built with the **real v0.2 schema** (from git history) holding a model rejected with exactly that error migrates to v0.3. The pipeline re-evaluates it automatically on the built-in dataset (bits per byte) without re-uploading; it is published, then deployed. |
| `test_missing_eval_data_guided_recovery` | With no dataset at all the release fails with a clear guided message and can't be deployed. Invalid datasets are refused with specific reasons (too short, binary, not UTF-8, missing tokenizer, bad token file). Uploading valid text makes the waiting release continue automatically (attempt 2) to *published*. Duplicates, pinning and tampered datasets are handled. |
| `test_token_datasets_require_matching_tokenizer` | Token datasets are used only for models with the same tokenizer; otherwise they are skipped with the reason. |
| `test_chunked_upload_resumes_after_interruption` | A non-MOTH manifest is refused before upload. A damaged chunk is rejected; completing early reports what is missing. Restarting resumes the same upload, re-sent chunks are harmless, temporary files are cleaned up, and duplicates are detected before upload. |
| `test_stale_uploads_expire_and_interrupted_work_recovers` | Abandoned uploads expire. A release stuck in *evaluating* after a restart becomes *failed: interrupted*, is retried automatically, and can be retried from the dashboard without re-uploading. |
| `test_upload_completion_survives_a_transient_server_error` | Found in live testing: a server error while completing keeps the chunks and returns a retryable 503; the retry publishes the model. |
| `test_publish_with_network_failures_and_app_restart` | The **desktop publisher** against a real server. The network fails mid-upload and the job pauses with its state persisted; a new publisher (an app restart) resumes it, despite more failures. Real evaluation, publish, deploy, then a user's chat is served by the model. Re-publishing is detected as a duplicate. |
| `test_publish_errors_are_clear` | Local validation stops a broken package before upload with the reason. Non-owners are refused. A stale Owner sign-in triggers re-authentication (428). |
| `test_upload_evaluate_deploy_rollback_and_restore` (updated) | v0.3 states. A failed deployment (corrupted weights) keeps the current model serving. A lower-scoring model needs an explicit override. Rollback works, and so does restore after a server restart. |

## Automatic updates

| Test | What it proves |
| --- | --- |
| `test_agent_api_is_hidden_and_signatures_enforced` | The agent API is 404 without its token. Tampered manifests, other keys' signatures and files that don't match the signed SHA-256 are refused. |
| `test_desktop_updates_staged_rollout_and_automatic_halt` | The Tauri update endpoint offers the signed update to about 10% of installs, then 50%. Reported failures above the limit halt the rollout automatically and log/notify; the Owner can promote it. |
| `test_outdated_clients_get_426_but_can_still_update` | Clients below the minimum version get 426 but can still reach health and the update service. The floor can't be lowered. |
| `test_owner_update_controls_require_owner` | Pause, check now, rollback requests, deployment history with logs, failure notification and system metrics; all Owner-only. |
| `test_worker_update_waits_for_job_and_verifies` | The running job is accepted *before* the update installs. Tampered offers are refused. A version that fails to start three times is reverted. |
| `test_stdlib_verifier_copies_are_identical_and_correct` | The agent, worker and server ed25519 verifiers are identical and correct; the committed public keys match. |

### `scripts/test-ecosystem-update.py`: real installation and updates

1. A **real v0.2.1 server** (code from git history) runs with an Owner account, like the VPS today.
2. `install-server.sh` **adopts it in place** without sudo: verified backup, migration to schema 2,
   cron supervision.
3. The Owner signs in with the **v0.2 password**.
4. A real **MOTH Worker 0.3.0** enrolls and connects over HTTP.
5. Signed release **0.3.1** (new migration, new agent): the agent verifies, backs up, migrates to schema
   3, restarts and health-checks, records the deployment with its log, and **updates itself**.
6. The **worker** installs 0.3.1 between jobs, restarts into it, reconnects and reports success.
7. Broken release **0.3.2** migrates to schema 4 then crashes. It is **rolled back automatically**, the
   database is restored to schema 3, and the Owner is notified.
8. A **tampered** release is ignored.
9. The agent is killed **right after switching** to 0.3.4; the next run finishes and verifies the update.
10. **Reboot**: all processes are SIGKILLed, and the supervisor brings MOTH Cloud back on 0.3.4.
11. An **Owner-requested rollback** returns to 0.3.1 with accounts intact.

Bugs this test found and that are fixed:

- the installer couldn't find the old server process without `ss`;
- worker update URLs depended on the public URL;
- recovery after a mid-update crash didn't restart the old process;
- the agent treated killed but unreaped (zombie) processes as running, so the cron supervisor would
  not restart a crashed server;
- the background agent and a manual `moth check` could overlap (now an exclusive lock).

## Live verification in the browser (real MOTH Server, local backend, production-mode UI)

- **First launch:** the welcome screen (Sign in → Open a workspace → Code). No server address is shown
  anywhere; the production build connected to its built-in endpoint.
- **Training:** a real `moth-small` model (6.16M parameters) was trained on CPU for 300 steps
  (validation loss 3.67) and exported.
- **Publishing:** *Validate* in Owner → Model packages reported checksum, architecture, tokenizer and
  resources. *Publish* uploaded it.
  - The first attempt hit a server error (that server had been started without the MOTH backend on its
    path), which exposed the completion bug above.
  - After the fix, the **same release recovered through the resumed upload**: it was evaluated
    (2.06 bits/byte on the built-in dataset, with the warning that a stdlib-trained model overlaps that
    data), published, then **deployed** from Owner Dashboard → AI models.
- **Inference:** after enabling cloud inference, workspace chat streamed a reply from
  `moth-small-v0.3-step300` on MOTH Cloud (CPU) at about 100 tokens/s.
- **Evaluation data:** a held-out text file was uploaded through the dashboard and validated.
- **Dashboard:** the Server (CPU, memory, disk, active users, recent errors), Updates and Workers panels
  rendered against real data.

## Not verified here (v0.3)

- A real Windows install, upgrade and signed desktop update (no Windows machine; CI builds the installer).
- The live VPS (not touched), real systemd, a real domain with HTTPS, real GPUs, and agent backups on
  PostgreSQL. See [LIMITATIONS.md](LIMITATIONS.md).

# v0.2.0 — CONNECT

## Automated suites (Linux x86-64, 4 CPU threads, no GPU, Python 3.13, PyTorch 2.15 CPU)

| Suite | Command | Result |
| --- | --- | --- |
| MOTH Server on SQLite | `cd server && python -m pytest -q` | **46 passed** |
| MOTH Server on PostgreSQL 16 | `MOTH_TEST_DATABASE_URL=postgresql+psycopg://… python -m pytest -q` | **46 passed** |
| Desktop backend | `cd backend && python -m pytest -q` | **104 passed** |
| Linux worker install, end to end | `bash scripts/test-worker-install.sh` | **PASS** |
| Frontend unit tests | `cd app && npm test` | **13 passed** |
| Frontend typecheck and production build | `npm run typecheck && npm run build` | passed |
| Rust shell | `cargo test` | **5 passed** (Windows CI also runs a strict Credential Manager round trip) |

## What the v0.2 tests cover

| Area | Highlights |
| --- | --- |
| Authentication | Register → email verification (single-use, expiring) → username-only login; passwords stored as Argon2id; case-insensitive unique usernames; reserved LK5T/admin names; duplicate emails (including Gmail dot and `+tag` variants) give an identical response and notify the real owner; generic login errors; per-IP and per-username rate limits with Retry-After; Remember Me and short sessions; listing, revocation, sign-out-everywhere, expiry; password change and reset revoke other sessions; scanner-safe verification page; avatar validation (type, size, no SVG). |
| Owner | One-time CLI initialisation (a second attempt fails); Owner role cannot be created or assigned; the Owner can't be demoted or suspended; re-authentication returns 428 when stale; every admin route returns 401/403 for non-owners. |
| Metering | Allowance is used before credits; the unused reservation is refunded; settlement is idempotent; a reused request id is refused (no free re-serving); balances never go negative; 25 concurrent reservations against a 10-request budget produce exactly 10 successes; ledger sum equals balance; period rollover; Owner is unlimited and unmetered; real metered inference counts exactly prompt + generated tokens. |
| Payments | Webhook signature, timestamp and secret verification; exactly-once processing; subscription create/update/delete; renewal via `invoice.paid`; `past_due`; checkout disabled until configured; mocked Stripe checkout sends no card data. |
| Referrals | Registration alone earns nothing; first paid invoice → pending reward → credited after the pending period, exactly once; refunds and disputes reverse with ledger clawback; monthly cap; same-IP referrals held for review, then approved; invalid codes and suspended referrers ignored; masked dashboard; share page. |
| Training network | Single-use, expiring enrollment tokens; install command pins the release SHA-256; worker and user credentials are mutually isolated; GPU required unless the development flag is set; two real workers complete a verified round aggregated into checkpoint v1; expired leases are requeued; reconnect resumes the same job; pause and revoke (revoked jobs return to the queue); tampered updates are rejected without credit; GPU referral rewards only after verified jobs, with self-referral blocked; mid-job checkpoint resume. |
| Model deployment | Network checkpoint → candidate → evaluation gate → deploy → metered MOTH Cloud serving with Owner exemption; uploads; unevaluated or rejected releases can't deploy; a corrupted release fails deployment while the previous model keeps serving; rollback; a restarted server restores the deployment; unsafe archives are rejected. |
| Server policy | Owner-only editing; validation; blocked input refused before metering. |
| Desktop cloud-only | No local load endpoints or inference modes; chat and agent require sign-in; agent requires per-workspace consent; secrets redacted before sending; outages reported clearly; server errors (402 allowance) surfaced. |

## Live verification (real services, browser-driven UI)

- **Accounts.** Register in the desktop UI, verify through the branded email page from the development outbox,
  sign in, then use the account menu (saved accounts) and Settings → Account (profile, sessions). The local backend
  received the session in memory only.
- **MOTH Cloud.**
  - Setup: the 6.2M `moth-small` model was uploaded to a real MOTH Server, evaluated (held-out loss 4.156) and
    deployed, then cloud inference was enabled.
  - Chat: a normal user chatted from the desktop UI and the reply streamed from MOTH Cloud.
  - Metering: the server metered exactly **316 tokens**.
  - Visibility: owner tools stay hidden for that user.
- **Outage.** With the server stopped, chat shows "Can't reach MOTH Cloud right now" with Retry, and the status bar
  shows "MOTH Cloud offline". Editor, terminal and Git are unaffected.
- **Training & Referrals** generated a single-use enrollment command.
- **Owner Dashboard (LK5T)** showed overview, users, and the models tab against real data.
- **Linux worker install, step by step:**
  - the generated command downloaded the release and passed `sha256sum -c`;
  - a tampered copy was rejected;
  - `install.sh` built the venv and enrolled (credential file mode 600);
  - the installed `moth-worker run` completed a **verified** training job;
  - the systemd unit was written.
- **Backup and restore.** `scripts/backup-server.sh` produced a checksummed archive. A fresh server started from the
  restored data redeployed model v1 and accepted existing logins.

## GitHub Actions (v0.2)

- **CI** [run 14](https://github.com/lk5t/moth-code/actions/runs/42059010993) (commit `053021a`) passed every job:
  - backend tests on Ubuntu and Windows
  - server tests on SQLite and PostgreSQL
  - the Linux worker-install test
  - frontend typecheck, tests and build
  - the desktop shell on Ubuntu and Windows, including the strict Credential Manager test
- **Release (Windows)** [run](https://github.com/lk5t/moth-code/actions/runs/42061896108) (commit `5c7d380`)
  passed:
  - the frozen-backend smoke test
  - the NSIS build of `MOTH Code_0.2.0_x64-setup.exe` (123 MiB)
  - publishing pre-release [v0.2.0](https://github.com/lk5t/moth-code/releases/tag/v0.2.0) with the installer,
    `moth-worker-0.2.0.tar.gz` and its `.sha256`
- An earlier release attempt built the installer, but `tauri-action` failed silently while creating the release
  (GitHub's API was also returning 502s at the time). The workflow now creates the release with `gh` before the
  build, so a failure there is reported clearly.

## Not verified here (v0.2)

- Real NVIDIA GPU execution (no GPU available); real Stripe test mode; real SMTP delivery.
- Docker image build; systemd on a booted host; the v0.2 Windows installer (built by the release workflow).

# v0.1.0 — Foundation

## v0.1 automated suites

| Suite | Command | Result |
| --- | --- | --- |
| Backend (pytest) | `cd backend && python -m pytest -q` | **103 passed, 0 failed** |
| Frontend (Vitest) | `cd app && npm test` | **13 passed** |
| Frontend typecheck | `cd app && npm run typecheck` | passed |
| Frontend production build | `cd app && npm run build` | passed |
| Rust shell | `cargo test --manifest-path app/src-tauri/Cargo.toml` | **2 passed** |

## GitHub Actions CI ([run 3](https://github.com/lk5t/moth-code/actions/runs/42020977341), commit `0c22e73`) — all passed

| Job | Result |
| --- | --- |
| Backend tests (ubuntu-latest, Python 3.12) | passed |
| Backend tests (windows-latest, Python 3.12) | passed |
| Frontend typecheck, tests and build | passed |
| Desktop shell (ubuntu-latest), Rust build + tests | passed |
| Desktop shell (windows-latest), Rust build + tests | passed |

The first CI run (commit `1e5e744`) failed on Windows. It exposed real bugs that the Linux suite could not catch:

- PowerShell needs `&` to run a command that starts with a quoted path.
- PowerShell didn't propagate exit codes.
- `edit_file` couldn't match text in CRLF files.
- The CLI crashed writing UTF-8 to a cp1252 console.

All four were fixed and covered by tests. On Linux, one flaky assertion was replaced by a deterministic comparison.

## What the backend tests cover

| Area | Highlights |
| --- | --- |
| Model | Analytic and real parameter counts match (MOTH-50M = 49,295,872 parameters); causality; KV-cache decoding equals full recomputation; grouped-query attention; deterministic greedy generation; cancellation. |
| Training genuinely updates weights | After one backward pass and AdamW step, **every** parameter tensor has changed and all gradients are finite. |
| Learning | On a synthetic corpus, the final train loss is under 60% of the initial loss, and validation loss decreases. |
| Resume | A run stopped at step 12 and resumed to step 30 produces **bit-identical weights** to an uninterrupted 30-step run (deterministic algorithms enabled). |
| Checkpoints / export | Best and latest checkpoints, atomic writes, rotation, STOP-file pause; export → load → evaluate; a corrupted model file is detected by checksum. |
| Tokenizer | Lossless round-trip on random Unicode; special-token handling with no injection from plain text; deterministic training; save/load fingerprints. |
| Data | License required for every source; validation split; chat loss masks; trusted vs untrusted special-token encoding. |
| CLI end to end | `tokenizer → prepare → train → export → generate` as real subprocesses. |
| API end to end | Tokenizer, dataset and training jobs through HTTP; concurrent-run refusal with no leftovers; export; load; streamed chat over WebSocket; evaluation job. |
| Agent | Real file edit plus a real pytest verification run; failed verification → `needs_review`; invalid model output → `model_incapable`; `give_up`; out-of-workspace denial; approval deny/approve for deletes; step limit; error memory recall; cancel, resume and revert; recovery after restart; context-budget trimming; **a genuine untrained MOTH network driving the loop is reported as incapable and changes nothing.** |
| Security | Workspace boundary and symlink escape; destructive, publish and network command classification; secret detection; approval broker; API token auth for HTTP and WebSocket. |
| Policy | No default restrictions; block/redact/warn; validation; persistence; credential redaction independent of policy. |
| Hybrid inference | Local-only without a model fails clearly; an unconfigured cloud is reported as not available; consent gates for chat and project data; auto prefers local; cloud output equals local output for the same model; secrets redacted before sending; non-MOTH servers refused; API key masked. |
| Community | Opt-in default, pause, schedule (including overnight windows), daily limits, clamped resource settings; validation rejects missing keys, bad shapes, NaN, oversized and empty updates; weighted FedAvg; two clients complete a round and aggregate into version 1 with lineage; checksum, stale-base and harmful (probe-loss) updates rejected; corrupted shard download detected; personal export uses only test-verified tasks. |
| Robustness | No CUDA / broken driver → CPU; hardware info never raises; corrupt model manifests reported; impossible training config fails cleanly with its error recorded; failing subsystem isolated. |
| Workspace | File ops; project scan; terminal streaming, exit codes, cancel (process tree), timeout, `cd` confinement; git status/diff/commit/log; CRLF-preserving edits; PowerShell wrapping. |

## Manual / integration verification

These were run in the development environment, not by the automated suites.

- **Real training run through the UI backend:**
  - Tokenizer `stdlib-4k`, trained on 3 MB of Python stdlib (PSF-2.0).
  - Dataset: 845,927 train and 6,908 validation tokens.
  - `moth-small` (6.16M parameters), 600 steps, seq 256 × batch 16, on CPU, at ~4.1K tokens/s.
  - Validation loss fell from ≈8.3 (random init) to **4.186**.
  - Exported, loaded and chatted with: 75 tokens/s on CPU. The output is Python-like text, as expected at this scale.
- **Agent with that model:** the task "Add a multiply function…" ended as `model_incapable` after three unusable
  outputs, with no file changes. That is the expected and honest result.
- **Desktop app launch (Linux, Xvfb):**
  - The Tauri shell started the backend with an ephemeral port, a token and its parent PID.
  - Unauthenticated API calls got 401.
  - The backend exited after the app was force-killed (within ~6.5 s).
- **Bundled backend:**
  - A PyInstaller build (~900 MB with CPU PyTorch) announced readiness and loaded all subsystems.
  - It ran a frozen generation, and a training job it launched as a frozen subprocess completed.
  - The Tauri app built with the release resource mapping launched the bundled backend from its resource
    directory.
- **UI:** browser screenshots against the real backend covered the workspace, editor, terminal (a typed command
  returned its output), chat streaming, agent report, training dashboard (live loss curve), models, community and
  settings.

## Windows release build ([run](https://github.com/lk5t/moth-code/actions/runs/42023871281)) — passed

- PyInstaller backend built on Windows. The frozen-backend smoke test passed: server handshake, all subsystems
  loaded, and a CLI tokenizer job ran.
- The Tauri release build bundled `MOTH Code_0.1.0_x64-setup.exe` (123 MiB, LZMA, with the MOTH theme hooks and
  artwork) using NSIS 3.13.
- It was published as pre-release [v0.1.0](https://github.com/lk5t/moth-code/releases/tag/v0.1.0).
- The installer's look was checked by compiling an NSIS installer with the same theme, pages and artwork, running it
  under Wine and screenshotting each page (see `docs/images/`).

## Not verified here

- Installing the released setup.exe on a real Windows PC (the repository is private, so this environment cannot
  download release assets).
- The signed update flow (it needs signing secrets).
- GPU (CUDA) training and inference. No GPU was available. The code paths are written for CUDA, and CPU fallback is
  tested.
- Training MOTH-50M to a useful quality level.
