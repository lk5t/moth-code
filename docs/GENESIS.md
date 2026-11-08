# GENESIS delivery record

Work stays on `claude/jolly-darwin-2qeihd`. The existing ASCENSION engine, trainer,
checkpoint format, dataset library, signed releases and update agents remain the foundation.

Production model reset is **not activated**. The GENESIS request requires verified backups
and separate explicit Owner approval before the deployed model is replaced. A prepared
fresh baseline must be labelled untrained; neither a baseline nor a CPU smoke test proves
that Foundation training is complete.

## Verified integration fixes

- The exact Desktop `PUT /api/participant` JSON request now binds to a request body. Its
  Pydantic model and the related on-device settings model are defined at module scope so
  postponed annotations resolve. The regression checks authentication, disable persistence,
  missing-body validation and the real signed-out enrollment error.
- Local CPU training defaults on where no Owner override exists. Explicit CPU disables and
  pauses survive settings merges. Threads use the existing quota-aware CPU detector.
- Scheduling ignores stale worker heartbeats, prefers compatible GPUs, and keeps the local
  assistant-mask-preserving trainer as the fallback. CPU workers remain available.
- API validation arrays become readable field messages rather than raw JSON.
- Local checks: participant regression **1 passed**; compute plus existing Evolution 2.0
  regression cases **10 passed**. GPU selection is simulated; physical GPU execution has
  not been verified.

## Phase status

| Phase | Status |
|---|---|
| 1 Backup and fresh lineage | Owner-gated backup, fresh seed, activation and restoration implemented; 3 isolated regression cases passed; production reset still awaits Owner approval |
| 2 Quality data | Existing approved-source discovery, provenance/license validation, deduplication, masks and held-out separation retained; data factory regressions passed |
| 3 CPU/GPU coordination | Automatic CPU fallback, compatible GPU selection and stale-worker checks tested; real CPU optimizer, checkpoint and server-restart recovery verified; physical GPU unverified |
| 4 Evolution/growth | Real approved GENESIS reset → 0.01 → 0.02 → 0.03 promotion/rollback verified; real degraded candidate rejection, expanded-model training and distributed recovery regressions passed |
| 5 Code/Chat workspace | Implemented compact switch, retained mounted workspaces, drafts/files, separate general history and consent-gated project excerpts; focused UI and real local API regressions passed |
| 6 Intelligence control center | Five tabs consolidate existing controls; actual architecture and reported-step activity, selectable layers and timeline; focused UI regressions passed; native Windows verification pending |
| 7 UI consistency | Sidebar consolidation, persistent navigation/layout, keyboard shortcuts, collapsible advanced panels, smaller minimum window and reduced-motion support implemented; native layout verification pending |
| 8 Integration fixes | Worker JSON/control APIs and real browser enrollment/training verified; original 0.5.1 → 0.5.4 Windows lifecycle passed an independent completion guard; 0.5.7 full native UI/release pending |
| 9 Real verification | In progress; no physical GPU available |
| 10 Delivery | Progress committed and pushed by phase; release confirmation recorded only after GitHub publication |

## Updater work carried forward

The Cloud endpoint previously returned HTTP 204 for missing installers, unsupported platforms,
paused releases and rollout exclusions; the desktop interpreted that as “up to date”. The
repair distinguishes those results, preserves HTTP errors, retains Tauri signature/version
verification, retries failed checks, and tests installation on normal window close.

The real Cloud offered signed 0.5.4 metadata to a 0.5.1 request on 2026-11-08 at 00:49 UTC,
with `Cache-Control: no-store`. Its desktop registration timestamp was 00:33:49 UTC, after
GitHub publication at 00:16:44 UTC. That verifies relay delay, not the installed user's
complete failure history. The user's device update has not been verified.

Server 0.5.5 was published through the existing signed workflow:
https://github.com/lk5t/moth-code/releases/tag/server-v0.5.5
Its updater agent has no code changes. Windows CI on the corrected updater source is green;
the current A-to-B Windows update test passed detection/download/signature verification,
installation on close, restart/reporting and user-data preservation. The separate original
published 0.5.1-to-0.5.4 test is now verified below. Desktop 0.5.5 was not published.

## Reset safety evidence

Isolated tests preserve a real optimizer state and original checkpoint bytes, verify a complete archive restoration, reject unapproved activation and tampered backups, initialize 99,648 fresh parameters with zero steps/tokens, and restore a deleted legacy checkpoint. Worker leases must quiesce before preparation; lease issuance is synchronized with the reset gate. Existing registry records remain available. A fresh baseline can score worse than the legacy model: only the separately confirmed Owner reset uses the existing explicit regression override, while retaining the real evaluation result. Automatic promotion gates are unchanged.

## Recovered workspace and UI verification

The disconnection preserved the uncommitted workspace/UI implementation. TypeScript checking
and seven focused UI cases pass, including Code/Chat drafts and unsaved files, Intelligence
navigation and controls, and the rule that training animation requires increased measured steps.
The Owner dashboard retains administration and links to Intelligence; existing advanced training,
registry, growth approval, rollback and worker controls remain accessible there.

Twenty-four backend cases pass, including actual HTTP project-consent enforcement and general/project
history separation, plus data factory, optimizer-moment growth and continued-training regressions.
The chat transport in the consent test is a named simulation, not training or inference-quality evidence.
No editor contents, account credentials or conversation messages are added to navigation storage.
Project excerpts are opt-in and use the existing cloud-consent and redaction path with Cloud history storage disabled.

## CPU and control evidence (2026-11-08)

The real CPU lifecycle and Evolution regression suite passed **18 cases**. Automatic preparation
used licensed PSF standard-library text with a distinct held-out split. The 99,648-parameter seed
promoted to 0.02 after 20 steps / 10,240 tokens and to 0.03 after 32 cumulative steps / 16,384 tokens.
General held-out loss measured 7.78162 → 4.96959 → 4.53979. Dataset validation loss measured
3.76954 and 3.54090. Every promotion gate passed; rollback reproduced the original seed bytes.
These small-model smoke measurements do not establish general coding/reasoning competence.

A separate real subprocess test paused for a **simulated memory shortage**, checkpointed, resumed,
was actually killed, then recovered in a new server application and completed 400 steps with
`resumed=true`, 204,800 tokens and validation loss 2.46481. It uses a 127,296-parameter legacy
fixture, not a trained Foundation checkpoint. The degraded-candidate rejection regression also passed.

Five focused control/compute cases verify authenticated HTTP worker-setting persistence, resuming
the same cycle, a new cycle after cancellation, prepared-reset blocking and preserving explicit
CPU disables. Multi-GPU selection now returns the fitting device index; GPU preference considers
each job's actual memory/worker allowlist and fresh heartbeat rather than delaying CPU work for
an incompatible GPU. Windows resource discovery handles platforms without `os.getloadavg`.

The combined lifecycle was subsequently run from both an empty installation and an explicitly
approved GENESIS reset over retained legacy releases: **4 lifecycle cases passed**. The GENESIS
path verifies zero inherited steps/tokens, both evaluated promotions, preserved ancestry and
rollback. [Recorded measurements](GENESIS-CPU-EVIDENCE.json) include real training losses,
checkpoint hashes and every promotion gate. The fresh configuration is 2 layers, width 64,
4 attention/KV heads, FFN width 128, context 256, tied embeddings, 272 byte/special-token vocabulary
entries, and 99,648 parameters. Fresh weights have no inherited optimizer state.

Nine additional Evolution 2.0 and discovery cases passed, including actual expanded-parameter
training after Owner approval, two real CPU worker runners with expired-lease recovery and
duplicate-shard rejection, continued development checkpoints and trusted-source ingestion.
GPU hardware declarations in selection tests are explicitly simulated; no GPU execution is claimed.

## Release candidate

The coordinated release candidate is **0.5.7**. Server 0.5.6 is already published; the native
Windows gate subsequently exposed a Windows-only Cloud memory-admission bug, so the next server
and Desktop packages share a new version rather than replacing immutable release assets. All application/server/worker version declarations agree.
Frontend verification passed **40 tests**, TypeScript checking and a production frontend build.
The existing Desktop release workflow now gates publication on an actual installed Windows UI
smoke covering launch, Code/Chat draft retention, restored navigation, the five Intelligence tabs,
real desktop-worker enrollment/toggles and a real CPU cycle requested through the UI. This gate
uses isolated test services; its result is pending until Windows Actions completes.

The published-compatibility helper now imports its temporary test CA into the isolated runner's
machine Root store (avoiding an interactive user consent dialog) and explicitly passes a verifying
TLS context to its Python registration helper. Production TLS/signatures are unchanged.

Chromium verification against an actual isolated Cloud, fresh 0.01 model and local desktop backend
passed Code/Chat draft retention, real Monaco unsaved edits, interactive architecture selection,
all five tabs, actual desktop-worker enrollment and persistent worker toggles, a CPU cycle requested
through the actual Resume button with measured training progress, navigation restoration
after reload and an 800×600 layout without horizontal overflow. Screenshots were inspected at
1280×800 and 800×600. This is browser evidence; native Windows evidence is tracked separately.
That review corrected tab alignment and a stale “waiting” label while training was explicitly paused.
The current-lineage comparison now excludes archived legacy evaluations after GENESIS activation;
an isolated reset regression verifies the old comparison stays archived.


## Confirmed delivery and Windows update evidence

Server 0.5.6 is published, not a draft, with all six required server/worker assets uploaded and
SHA-256 digests reported by GitHub. The existing workflow verified signatures, checksums and bundle
contents before publication. Its tag targets `649c5caae4fe7c7cc4c4284f1aeb19fd7a28dc48`.

- Release: https://github.com/lk5t/moth-code/releases/tag/server-v0.5.6
- Signed release workflow: https://github.com/lk5t/moth-code/actions/runs/42471592334
- Signing-key preflight: https://github.com/lk5t/moth-code/actions/runs/42472768884

An Actions read-only probe subsequently confirmed the actual VPS running healthy server 0.5.6,
API 3 / schema 5, with serving model release 1 retained. The updater agent and its keys have no
source changes. No production model backup/reset/activation was performed by this task.

The real published 0.5.1 and 0.5.4 installers passed their Windows compatibility lifecycle at
https://github.com/lk5t/moth-code/actions/runs/42478185293. The independent proof step requires the
record written only after signature rejection, verified authentic download, installation on normal
close, registry upgrade, restarted-client success reporting and account/settings/workspace checks.
This verifies an isolated Windows installation of the original signed binaries, not the user's PC.
A one-time reinstall is not inherently required: a configured, reachable Cloud endpoint can update
0.5.1 automatically. Existing staging/halts and local network/TLS failures can still defer an offer.

The original installer has a single Settings page and does not expose the requested WebView debug
endpoint in this runner. Its test uses normal Windows accessibility controls instead. Both native
verification scripts now write evidence only after their assertions, and separate workflow steps
require the evidence before proceeding. A green interpreter exit alone is insufficient.

Local full server verification passed **150 tests**; frontend verification passed **40 tests** plus
TypeScript checking and a production build. Full CI passed at `4770d22`, including SQLite/PostgreSQL,
Linux/Windows backend and desktop-shell suites, worker installs, and real Cloud update/recovery.
The current A/B Windows updater also passed its real close/install/restart/data-preservation test
(job 128707604113 in run 42472119952). Desktop 0.5.7 publication remains pending its complete signed
build and native GENESIS UI/control verification.

The first full native Windows GENESIS run reached actual Owner login, retained drafts, interactive
architecture/tabs and enrolled/disabled a real Desktop participant, then failed waiting for CPU
progress. Source inspection and a failing regression confirmed that the Cloud RAM reader used
Linux `/proc/meminfo` exclusively: Windows returned no memory measurement, and safe CPU admission
correctly refused unknown capacity. The native Windows `GlobalMemoryStatusEx` fallback now measures
available physical memory without extra dependencies or relaxed limits. The Linux reader is unchanged;
failed native readings still return unknown. Six focused compute regressions pass. The installed-app
release gate remains mandatory and records bounded scheduling/trainer diagnostics on failures.

## Tests and activation that remain conditional

- **Physical GPU execution:** unavailable in this environment. Selection/VRAM/permissions/fallback
  tests use explicitly simulated declarations. Real CPU training and two actual CPU worker runners
  exercise the training protocol; this does not certify multi-host GPU throughput.
- **Production fresh lineage:** use Intelligence → Training → GENESIS to prepare and review the
  verified archive first. Only the Owner's separate typed approval activates fresh 0.01. Until
  then the live legacy release remains deployed. Stored CPU disables, pauses and limits remain
  respected; the new default applies where no Owner override is stored.
- **Genuinely trained Foundation quality:** no completed trained Foundation checkpoint and matching
  evaluation package was verified. The existing full-architecture training/resume/inference smoke
  checks the pipeline, not model competence. Absolute coding/math/reasoning/language/instruction,
  knowledge/safety and long-term retention acceptance tests require that trained package and its
  genuinely held-out evaluation manifests. Never overwrite existing training checkpoints to run them.
- **Small-model lifecycle policy:** real loss/improvement/retention gates run in an isolated FAST
  fixture with shortened rollout timing and relaxed speed/memory noise limits; production defaults
  are unchanged. These measurements do not establish Foundation-level abilities.
- **Production protected actions and user device:** authenticated live Owner/worker operations and
  the user's desktop update were not exercised using production credentials. Real authenticated
  APIs were tested against isolated servers. The VPS public health/update routes were checked by
  Windows Actions; direct workspace access to the VPS/log-download hosts remains proxy-restricted.
- **Windows publisher certificate:** the existing updater and release-manifest signatures are
  preserved. Windows Authenticode signing is not added by this update.

## Exact changed files

Compared with the source at `03331f6` before the carried-forward updater repair. Existing files are reused; no updater agent or signing key was changed.

| File | Necessary purpose |
|---|---|
| `.github/desktop-release-notes.md` | Describe GENESIS, preserved data, signed updates and the separate Owner reset approval. |
| `.github/server-release-notes.md` | Describe GENESIS, preserved data, signed updates and the separate Owner reset approval. |
| `.github/workflows/ci.yml` | Expose Rust failure details through Actions annotations without changing test exit status. |
| `.github/workflows/desktop-update-test.yml` | Verify original published installers/signatures and actual close-triggered update installation. |
| `.github/workflows/release.yml` | Add the real installed Windows GENESIS gate and set the release version default. |
| `.github/workflows/server-release.yml` | Set the coordinated server release version default. |
| `app/package-lock.json` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `app/package.json` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `app/src-tauri/Cargo.lock` | Lock the coordinated app version and direct use of the already-locked HTTP/TLS dependencies. |
| `app/src-tauri/Cargo.toml` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `app/src-tauri/src/updates.rs` | Preserve HTTP update errors and initialize the existing TLS provider; retain signed-version/download/install verification. |
| `app/src-tauri/tauri.conf.json` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `app/src/App.tsx` | Keep both Code/Chat workspaces mounted and route AI tools to the consolidated Intelligence view. |
| `app/src/components/NavRail.tsx` | Remove duplicate primary AI destinations and provide navigation shortcuts. |
| `app/src/features/chat/ChatPanel.tsx` | Separate general/project history and pass only explicitly attached project context. |
| `app/src/features/chat/ChatView.tsx` | Offer opt-in project excerpts using existing per-project Cloud consent. |
| `app/src/features/intelligence/GenesisPanel.tsx` | Present verified backup review, typed Owner activation and restoration controls. |
| `app/src/features/intelligence/IntelligenceHub.tsx` | Consolidate five tabs, retain advanced controls and visualize real architecture/reported steps. |
| `app/src/features/intelligence/IntelligenceView.tsx` | Reuse overview inside the hub; make timeline points selectable and respect paused status. |
| `app/src/features/owner/OwnerDashboard.tsx` | Keep administration while moving native AI controls into Intelligence. |
| `app/src/features/training/NetworkTraining.tsx` | Show readable control failures and real resume/CPU/worker settings. |
| `app/src/features/workspace/WorkspaceShell.tsx` | Add the compact mode switch and keyboard shortcut while retaining original mounted views. |
| `app/src/features/workspace/WorkspaceView.tsx` | Persist the existing horizontal panel layout with stable panel identifiers. |
| `app/src/index.css` | Honor reduced-motion preferences throughout the existing interface. |
| `app/src/lib/account.ts` | Convert FastAPI validation/details into readable errors in the existing API clients. |
| `app/src/lib/app-state.ts` | Persist navigation, mode and panel settings without storing editor text or credentials. |
| `app/src/lib/backend.ts` | Convert FastAPI validation/details into readable errors in the existing API clients. |
| `app/src/lib/errors.ts` | Convert FastAPI validation/details into readable errors in the existing API clients. |
| `app/src/lib/updater.ts` | Retain update errors, retry failed checks, reject invalid pending state and install verified downloads once on close/restart. |
| `app/src/test/intelligence-hub.test.tsx` | Verify consolidated controls, measured-activity-only animation and retained drafts/unsaved files. |
| `app/src/test/lib.test.ts` | Regress readable validation errors and updater detection/download/rejection/close behavior. |
| `app/src/test/owner-dashboard.test.tsx` | Verify retained administration/updater controls after AI navigation consolidation. |
| `app/src/test/updater.test.ts` | Regress readable validation errors and updater detection/download/rejection/close behavior. |
| `app/src/test/workspace-modes.test.tsx` | Verify consolidated controls, measured-activity-only animation and retained drafts/unsaved files. |
| `app/src/views.tsx` | Map legacy AI destinations to the hub and retain the Owner guard. |
| `backend/moth/__init__.py` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `backend/moth/server/routes_hybrid.py` | Resolve request models at module scope to fix PUT /api/participant query.body validation. |
| `backend/moth/server/routes_model.py` | Enforce project consent/redaction for chat context and filter general history separately. |
| `backend/pyproject.toml` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `backend/tests/test_genesis_chat.py` | Verify real local HTTP consent/history behavior with an explicitly simulated inference transport. |
| `backend/tests/test_server.py` | Reproduce the exact participant JSON/authentication/persistence error, including optional-worker builds. |
| `docs/GENESIS-CPU-EVIDENCE.json` | Record phase status, measured CPU/evaluation/checkpoint evidence, delivery results and limitations. |
| `docs/GENESIS.md` | Record phase status, measured CPU/evaluation/checkpoint evidence, delivery results and limitations. |
| `scripts/desktop-update-harness.py` | Allow an explicitly verifying TLS context for isolated signed-release registration. |
| `scripts/prepare-release.mjs` | Document that the update test exercises actual window-close installation; preserve release signing configuration. |
| `scripts/test-genesis-desktop.py` | Gate release on a real installer/frozen-backend/Cloud UI and training-control smoke test. |
| `scripts/test-published-desktop-update.py` | Verify published 0.5.1/0.5.4 bytes/signatures and native tamper rejection, close installation and preserved data. |
| `scripts/windows-desktop-ui.py` | Drive unchanged signed Windows releases through accessibility patterns when release WebView debugging is unavailable. |
| `server/moth_server/__init__.py` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `server/moth_server/evolution/backends.py` | Use safe CPU defaults/resources, fresh compatible workers and the GPU device that actually fits. |
| `server/moth_server/evolution/compute.py` | Use safe CPU defaults/resources, fresh compatible workers and the GPU device that actually fits. |
| `server/moth_server/evolution/distributed.py` | Prefer fitting GPU participants when real distributed training can use them. |
| `server/moth_server/evolution/engine.py` | Preserve GPU priority when choosing between local and distributed backends. |
| `server/moth_server/evolution/genesis.py` | Implement verified training archives, fresh weights, separate Owner activation and safe restoration without overwriting progress. |
| `server/moth_server/evolution/settings.py` | Enable eligible CPU fallback by default while preserving stored Owner overrides and safe thread quotas. |
| `server/moth_server/evolution/v2.py` | Allocate accepted model versions within the active lineage after an approved reset. |
| `server/moth_server/routes/evolution.py` | Expose Owner-gated GENESIS operations, resume eligible cycles and report active-lineage comparisons. |
| `server/moth_server/routes/intelligence.py` | Return actual architecture/initialization data and filter the active model timeline by lineage. |
| `server/moth_server/routes/system.py` | Measure native available Windows RAM for safe CPU admission; preserve Linux measurements and unknown-capacity refusal. |
| `server/moth_server/routes/updates.py` | Distinguish genuine no-update from rollout, metadata, artifact, signature and compatibility errors. |
| `server/moth_server/training.py` | Synchronize leases with reset preparation, retire legacy rounds and match GPU preference to each eligible job. |
| `server/pyproject.toml` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `server/tests/test_autonomous_lifecycle.py` | Verify real CPU progression and rollback from both an empty installation and an approved GENESIS reset. |
| `server/tests/test_evolution.py` | Regress authenticated training controls, resumption, cancellation recovery and persisted worker settings. |
| `server/tests/test_genesis_compute.py` | Regress CPU defaults/Owner limits, stale workers, GPU fit and job permissions with explicit simulated hardware. |
| `server/tests/test_genesis_reset.py` | Verify real weights/optimizer archival, tamper protection, Owner gates, new-lineage metrics and restoration. |
| `server/tests/test_updates.py` | Regress desktop update HTTP semantics and artifact/channel/version requirements. |
| `worker/moth_worker/__init__.py` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
| `worker/pyproject.toml` | Coordinate release version 0.5.7; Tauri config also permits the tested smaller window size. |
