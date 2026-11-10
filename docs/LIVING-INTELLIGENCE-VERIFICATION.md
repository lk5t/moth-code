# LIVING INTELLIGENCE — verification and changed-file record

Repository `lk5t/moth-code`; branch `claude/jolly-darwin-2qeihd`.
Baseline `c61d52b`; implementation through `eb362a5`.

Status: all 15 phase implementations are present. All available automated, real CPU, browser and native Windows candidate checks passed. Physical GPU and live Hugging Face verification remain unavailable as described below. Following explicit Owner approval, both signed v0.6.0 Releases are published. The publication workflows tested and released `40ab9612fe61e24bcd641032a1c4d7bbb5b6525e`, whose application source matches the verified candidates; subsequent commits only update documentation. The candidate Server/Worker runtime at `a7d8e95` and Desktop source at `eb362a5` are preserved.

## Phase status

| Phase | Implementation / evidence |
| --- | --- |
| 1 — Source usability audit | Complete; actual feature inventory and authoritative homes recorded. |
| 2 — Eight workspaces | Complete; route adapters, persistence, keyboard search, actual browser navigation. |
| 3 — Focused pages | Complete; existing controls reused in default/Advanced homes. |
| 4 — Beginner experience | Complete; skip/reopen guide and plain errors; actual first-launch Chromium path. |
| 5 — Living motion | Complete; actual simultaneous events, hidden/reduced-motion handling. |
| 6 — Live Overview | Complete; real loaded-model/promotion/rollback/account/offline tests. |
| 7 — Chat and Code | Complete; real CPU Chat/regeneration, history/search and unsaved-edit protections. |
| 8 — Project Intelligence | Complete; real files/SQLite, private scopes/consent, incremental evidence and delete/re-enable. |
| 9 — Controlled self-improvement | Complete; existing real CPU lifecycle, held-out gates/budgets/rollback, reference suite additions. |
| 10 — Dataset Quality Studio | Complete; actual TXT/JSONL/preparation/tokenization/integrity, explicitly bounded cleaning previews. |
| 11 — Full native reset | Complete implementation; isolated real trainer/files/SQLite/PostgreSQL/worker/failure/recovery/fresh-training tests. |
| 12 — Unified activity | Complete; persisted authorization-filtered history, paging/filtering and deduplicated quiet notices. |
| 13 — Stability/accessibility | Complete; real browser sizes, dialog focus, event/editor response-order and resource cleanup tests. |
| 14 — Full integration | Available CPU/browser/native Windows paths passed, including genuine training, restart, reset and upgrade. Physical GPU and live Hugging Face checks are blocked, not claimed complete. |
| 15 — Signed 0.6.0 release | Complete: Owner-approved Server/Worker and Desktop Releases published; all 11 Server and 14 Desktop jobs passed, including signing, native Windows and genuine upgrade verification. |

## Verified automated and integration evidence

- 169-test full local backend suite; four additional focused native-driver tests. Latest Linux/Windows CI covers the resulting 173 collected backend tests with applicable platform skips.
- 188-test full local server suite, followed by reset and legacy Genesis/compute regressions; final Server candidate passed the expanded 190-test suites on SQLite and PostgreSQL.
- 70-test full UI suite; TypeScript and production UI bundle.
- Real Chromium: eight workspaces at 800×600 / 1440×900, no page-wide overflow or browser exceptions; real Project Intelligence; multiline draft switching; keyboard search; actual first-launch guide/skip/Settings.
- Real browser Data UI: read-only quality inspection, tokenizer round-trip and actual TXT/JSONL preparation produced 521 training and 1,141 validation tokens without changing source files.
- Fresh isolated browser → real Cloud/sidecar: measured model disclosure and layer selection; Cloud worker toggle; actual desktop enrollment/disable; real CPU cycle progress; persisted Data workspace after reload; explicit full native reset; empty Overview; explicit fresh initialization. The fixture used its own storage and temporary Owner. Browser-driver-only CORS/async/response-shape corrections were needed; no product assertions were removed.
- Real browser → local backend → retained trained CPU fixture: user turn + assistant answer, then regeneration retaining two answers and one user turn; no existing weights reset.
- Full 49,295,872-parameter architecture: all 111 weight tensors updated, optimizer/checkpoint resumed to step 3 / 192 tokens, export verified and eight output tokens generated. This is a pipeline smoke, **not completed Foundation training or quality validation**.

## Candidate workflows

- Passed Server (11/11 jobs): https://github.com/lk5t/moth-code/actions/runs/42706344137
- Passed Desktop (14/14 jobs): https://github.com/lk5t/moth-code/actions/runs/42712321054
- Final Server candidate passed all eleven jobs at `a7d8e952fe3bef5bd5bc760abf1529b55f8ce572`. Production signature and bundle verification passed; GitHub publication was skipped. Signed server/worker artifact: `13714576836`, SHA-256 `c0e51d9e14a9c3c72f90ba87a3b8cf3e1bf717871caaa46e757fb4a9a987794a`.
- Final Desktop candidate passed all fourteen jobs at `eb362a5c751825909fd352d2ec6bbf1accf6601e`. Signed installer and manifest checks passed. Signed Desktop artifact: [`13719676098`](https://github.com/lk5t/moth-code/actions/runs/42712321054/artifacts/13719676098), Actions artifact ZIP SHA-256 `f3760ebc1215856c9b3d1201603472509ed1b25779ad96fd8a5290da6a719b15` (172,070,159 bytes). The Server digest above is also the Actions artifact ZIP digest, not an installer checksum; each bundle's signed manifest and checksums were independently verified inside its workflow.
- Native Windows proof confirms the real installed frozen backend, eight workspaces, actual composer draft preservation, Cloud worker controls and personal enrollment, real CPU training cycle, 800×600 navigation, Owner credential-vault/session and workspace restoration after restart, isolated full reset, empty Overview and explicit fresh initialization. `production_reset=false`, `trained_foundation=false`.
- Real published **0.5.9 → 0.6.0** proof confirms production signatures, tampered-installer rejection, verified background download before close, install-on-close, successful restart report and settings/account/workspace preservation. This was an isolated HTTPS server and actual Windows installation, not a live customer rollout. The historical production-signed **0.5.1 → 0.5.4** regression also passed.
- Native evidence artifact: [`13719401241`](https://github.com/lk5t/moth-code/actions/runs/42712321054/artifacts/13719401241); upgrade evidence artifact: [`13719366424`](https://github.com/lk5t/moth-code/actions/runs/42712321054/artifacts/13719366424).
- The candidate-only workflows explicitly skipped GitHub Release creation. At candidate verification both tags were absent (HTTP 404). Subsequent Owner-approved publication is recorded below.
- Earlier Windows candidates exposed test-driver assumptions: delayed Welcome guide, selecting conversation search instead of the composer, a shortened disclosure name, and assuming published Git tags existed in a shallow checkout. These were corrected without removing assertions or altering signing/updater checks. Run 42704682002 passed its ten CI jobs and two signed Windows update jobs, built its production-signed installer/frozen backend, logged in as the isolated Owner and preserved the actual Chat draft; it then failed on the disclosure selector. Corrected final run is listed above.

## Limits and explicit approval boundaries

Physical CUDA hardware is unavailable; CPU execution and fallback/control paths are verified, physical GPU execution is not. The live Hugging Face `all-v1` failure cannot be reproduced with the available source details/network policy; raw TXT/JSONL paths and source diagnostics were tested. Dataset quality checks state their sample/heuristic limits; independent Owner reference suites are needed for unmeasured capabilities. No trained Foundation quality checkpoint is claimed.

Full reset covers fixed deployment-owned roots and records. It preserves unrelated platform/user data and creates no replacement automatically. Managed backup deletion requires separate typed scope. External originals, infrastructure snapshots, exported Desktop packages, unverified worker caches and offline workers remain explicitly disclosed; completion is not a claim of forensic erasure of every copy. The supported server deployment has one coordinator/web process; other direct native-storage writers must be stopped for an administrative reset.

Candidate verification used `publish=false`, creating only Actions artifacts. The Owner subsequently explicitly approved release publication, recorded below. No production reset or merge was performed. Existing automatic update and rollout mechanisms govern installation; this session did not observe a live customer or VPS installation. Production reset still requires its own separate authorization.

## Owner-approved publication — 10 November 2026

Both Releases were built from `40ab9612fe61e24bcd641032a1c4d7bbb5b6525e` on `claude/jolly-darwin-2qeihd` using the existing workflows with `publish=true` and the stable channel. GitHub confirms `draft=false`, `prerelease=false`, nonempty published timestamps and matching tag commit refs. All required assets are nonempty and in the `uploaded` state.

| Component | Published Release | Successful workflow | Published at (UTC) | Required assets |
| --- | --- | --- | --- | --- |
| Server/Worker | [server-v0.6.0](https://github.com/lk5t/moth-code/releases/tag/server-v0.6.0) | [42803598527](https://github.com/lk5t/moth-code/actions/runs/42803598527), 11/11 jobs | 2026-11-10T11:13:05Z | 6/6: Cloud bundle, Worker bundle and its checksum, release manifest and signature, SHA256SUMS. |
| Windows Desktop | [desktop-v0.6.0](https://github.com/lk5t/moth-code/releases/tag/desktop-v0.6.0) | [42803602128](https://github.com/lk5t/moth-code/actions/runs/42803602128), 14/14 jobs | 2026-11-10T11:41:23Z | 5/5: installer and updater signature, release manifest and signature, SHA256SUMS. |

The publication run repeated and passed the real native Windows UI/worker/CPU/reset/restart flow and the production-signed 0.5.9 → 0.6.0 lifecycle: tampered installer rejected; background download verified; installation waited for close; restart report received; settings, accounts and workspaces preserved. The historical 0.5.1 → 0.5.4 Windows update regression passed too. Server signing, bundle contents and checksums were verified before upload. Both actual GitHub Release creation steps succeeded.

The published Windows installer is `MOTH.Code_0.6.0_x64-setup.exe` (172,030,596 bytes), GitHub asset SHA-256 `f534871a5726065e5785497cc1693d1fc7a1c89b208af06706ddb3c12063dc6f`. Published Cloud bundle SHA-256: `ccc29a180d2235877eb7ada09d35ef438438710fc65963a07426af2d2a97e7c5`; Worker bundle SHA-256: `c82da783fa92c850a8a4412220d7a30deee764957e8e6c91402c2a3ba32fb53c`. These are published asset digests, distinct from the earlier candidate artifact ZIP digests.

Existing updater source, signing keys and Owner rollout controls are unchanged. Desktop availability follows the existing rollout setting; publishing is not proof that a particular live installation has updated. No production reset or live Foundation quality claim is made. Physical GPU and live Hugging Face limitations above remain.

## Exact changed files and necessity

Each path below changed from the existing v0.5.9 foundation. All existing updater source, release keys and signing requirements are preserved.

| File | Why the change was needed |
| --- | --- |
| [.github/desktop-release-notes.md](../.github/desktop-release-notes.md) | Document the requested v0.6.0 changes, preservation guarantees, reset scope and release/verification limits. |
| [.github/server-release-notes.md](../.github/server-release-notes.md) | Document the requested v0.6.0 changes, preservation guarantees, reset scope and release/verification limits. |
| [.github/workflows/release.yml](../.github/workflows/release.yml) | Retain signing and all release gates; default to non-published signed candidates and verify upgrade from 0.5.9. |
| [.github/workflows/server-release.yml](../.github/workflows/server-release.yml) | Retain signing and all release gates; default to non-published signed candidates and verify upgrade from 0.5.9. |
| [CHANGELOG.md](../CHANGELOG.md) | Document the requested v0.6.0 changes, preservation guarantees, reset scope and release/verification limits. |
| [app/package-lock.json](../app/package-lock.json) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [app/package.json](../app/package.json) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [app/src-tauri/Cargo.lock](../app/src-tauri/Cargo.lock) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [app/src-tauri/Cargo.toml](../app/src-tauri/Cargo.toml) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [app/src-tauri/tauri.conf.json](../app/src-tauri/tauri.conf.json) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [app/src/App.tsx](../app/src/App.tsx) | Start the shared activity listener before event transport. |
| [app/src/components/ActivityNotices.tsx](../app/src/components/ActivityNotices.tsx) | Render quiet notices from shared measured status without another poll. |
| [app/src/components/ErrorNotice.tsx](../app/src/components/ErrorNotice.tsx) | Show plain-language errors with optional original diagnostics. |
| [app/src/components/FeatureSearch.tsx](../app/src/components/FeatureSearch.tsx) | Search authoritative feature routes with accessible modal keyboard navigation. |
| [app/src/components/LivingMoth.tsx](../app/src/components/LivingMoth.tsx) | Render real simultaneous activity through the shared emblem and pulse. |
| [app/src/components/MothEmblem.tsx](../app/src/components/MothEmblem.tsx) | Extend real activity states and pause hidden/reduced-motion decoration. |
| [app/src/components/NavRail.tsx](../app/src/components/NavRail.tsx) | Expose the eight requested workspaces with active labels and feature search. |
| [app/src/components/StatusBar.tsx](../app/src/components/StatusBar.tsx) | Use authoritative, account-scoped loaded-model identity. |
| [app/src/components/ui/dialog.tsx](../app/src/components/ui/dialog.tsx) | Provide an accessible label for the existing close control. |
| [app/src/features/activity/ActivityWorkspace.tsx](../app/src/features/activity/ActivityWorkspace.tsx) | Provide one Activity home for Cloud events, timeline and local history. |
| [app/src/features/activity/CloudActivity.tsx](../app/src/features/activity/CloudActivity.tsx) | Filter and page authorization-scoped recorded events with stale-response protection. |
| [app/src/features/agent/ProjectIntelligencePanel.tsx](../app/src/features/agent/ProjectIntelligencePanel.tsx) | Expose local evidence, search, confirmed decisions and explicit refresh/delete controls. |
| [app/src/features/chat/ChatPanel.tsx](../app/src/features/chat/ChatPanel.tsx) | Add search, history paging, preserved scroll, regeneration and shared active identity. |
| [app/src/features/chat/ChatView.tsx](../app/src/features/chat/ChatView.tsx) | Bind attached-project state to the account and display authoritative model status. |
| [app/src/features/chat/Markdown.tsx](../app/src/features/chat/Markdown.tsx) | Reuse safe rendered text for copyable answers and code. |
| [app/src/features/evolution/EvolutionView.tsx](../app/src/features/evolution/EvolutionView.tsx) | Reuse guarded shared status and distinguish held-out gates from training loss. |
| [app/src/features/intelligence/GenesisPanel.tsx](../app/src/features/intelligence/GenesisPanel.tsx) | Label legacy reversible lineage recovery separately from full erasure. |
| [app/src/features/intelligence/IntelligenceHub.tsx](../app/src/features/intelligence/IntelligenceHub.tsx) | Reuse existing features in focused primary/Advanced homes with shared polling. |
| [app/src/features/intelligence/IntelligenceView.tsx](../app/src/features/intelligence/IntelligenceView.tsx) | Use the shared measured timeline/status snapshot. |
| [app/src/features/intelligence/NativeResetPanel.tsx](../app/src/features/intelligence/NativeResetPanel.tsx) | Require reviewed Owner deletion scope and separate typed backup approval; reject stale callbacks. |
| [app/src/features/intelligence/OverviewSummary.tsx](../app/src/features/intelligence/OverviewSummary.tsx) | Show loaded model, service, training, workers and verified improvement without inferred metrics. |
| [app/src/features/intelligence/TrainingProgress.tsx](../app/src/features/intelligence/TrainingProgress.tsx) | Connect training feedback to real activity and measurements. |
| [app/src/features/onboarding/Welcome.tsx](../app/src/features/onboarding/Welcome.tsx) | Provide skippable, reopenable beginner guidance using accessible existing dialogs. |
| [app/src/features/owner/OwnerDashboard.tsx](../app/src/features/owner/OwnerDashboard.tsx) | Keep administration accessible from Settings and route active-model links to Overview. |
| [app/src/features/owner/intelligence.tsx](../app/src/features/owner/intelligence.tsx) | Reuse selected advanced library/weakness/feedback/knowledge sections without duplicate panels. |
| [app/src/features/settings/SettingsView.tsx](../app/src/features/settings/SettingsView.tsx) | Persist sections, expose guidance and separate destructive actions, and verify permission saves. |
| [app/src/features/training/DatasetQualityStudio.tsx](../app/src/features/training/DatasetQualityStudio.tsx) | Inspect raw/prepared data, licenses, quality/cleaning previews and tokenizer behavior. |
| [app/src/features/training/TrainingView.tsx](../app/src/features/training/TrainingView.tsx) | Separate local data from training, retain existing tools and expose quality/compatibility status. |
| [app/src/features/workspace/ActivityPanel.tsx](../app/src/features/workspace/ActivityPanel.tsx) | Guard/coalesce local activity loading and show request errors. |
| [app/src/features/workspace/WorkspaceShell.tsx](../app/src/features/workspace/WorkspaceShell.tsx) | Keep existing Chat/Code mounted while presenting separate main workspaces. |
| [app/src/features/workspace/WorkspaceView.tsx](../app/src/features/workspace/WorkspaceView.tsx) | Expose recent projects and Project Intelligence through the existing Code tools. |
| [app/src/features/workspace/project-actions.ts](../app/src/features/workspace/project-actions.ts) | Protect unsaved files before authorizing/switching projects. |
| [app/src/features/workspace/workspace-actions.ts](../app/src/features/workspace/workspace-actions.ts) | Reject late project/file responses and preserve edits made during saves/refetches. |
| [app/src/index.css](../app/src/index.css) | Add subtle activity styling while retaining visible focus and reduced-motion behavior. |
| [app/src/lib/activity-notices.ts](../app/src/lib/activity-notices.ts) | Deduplicate meaningful notices across refresh/reconnect/account/reset without storing contents. |
| [app/src/lib/app-state.ts](../app/src/lib/app-state.ts) | Support requested workspace routes while preserving saved legacy state. |
| [app/src/lib/cloud-progress.ts](../app/src/lib/cloud-progress.ts) | Share one account-scoped, timed, visibility-aware status loop with late-response rejection. |
| [app/src/lib/hooks.ts](../app/src/lib/hooks.ts) | Reject stale resource responses and cancel pending event-refresh timers. |
| [app/src/lib/living-activity.ts](../app/src/lib/living-activity.ts) | Derive real local/Cloud stages and reject stale reconnect job snapshots. |
| [app/src/lib/navigation.ts](../app/src/lib/navigation.ts) | Define one authoritative eight-workspace route mapping and legacy adapters. |
| [app/src/lib/project-intelligence.ts](../app/src/lib/project-intelligence.ts) | Bind local project requests to the initiating session without transmitting Cloud tokens. |
| [app/src/lib/use-saved-section.ts](../app/src/lib/use-saved-section.ts) | Persist validated section names without storing sensitive form state. |
| [app/src/test/activity-notices.test.ts](../app/src/test/activity-notices.test.ts) | Focused regression/integration coverage for activity notices. |
| [app/src/test/chat-living.test.tsx](../app/src/test/chat-living.test.tsx) | Focused regression/integration coverage for chat living. |
| [app/src/test/cloud-progress.test.tsx](../app/src/test/cloud-progress.test.tsx) | Focused regression/integration coverage for cloud progress. |
| [app/src/test/dataset-quality.test.tsx](../app/src/test/dataset-quality.test.tsx) | Focused regression/integration coverage for dataset quality. |
| [app/src/test/editor-races.test.ts](../app/src/test/editor-races.test.ts) | Focused regression/integration coverage for editor races. |
| [app/src/test/intelligence-hub.test.tsx](../app/src/test/intelligence-hub.test.tsx) | Focused regression/integration coverage for intelligence hub. |
| [app/src/test/living-activity.test.ts](../app/src/test/living-activity.test.ts) | Focused regression/integration coverage for living activity. |
| [app/src/test/native-reset.test.tsx](../app/src/test/native-reset.test.tsx) | Focused regression/integration coverage for native reset. |
| [app/src/test/navigation-v060.test.tsx](../app/src/test/navigation-v060.test.tsx) | Focused regression/integration coverage for navigation v060. |
| [app/src/test/onboarding-v060.test.tsx](../app/src/test/onboarding-v060.test.tsx) | Focused regression/integration coverage for onboarding v060. |
| [app/src/test/owner-dashboard.test.tsx](../app/src/test/owner-dashboard.test.tsx) | Focused regression/integration coverage for owner dashboard. |
| [app/src/test/project-intelligence.test.tsx](../app/src/test/project-intelligence.test.tsx) | Focused regression/integration coverage for project intelligence. |
| [app/src/test/project-switch.test.ts](../app/src/test/project-switch.test.ts) | Focused regression/integration coverage for project switch. |
| [app/src/test/resource-isolation.test.tsx](../app/src/test/resource-isolation.test.tsx) | Focused regression/integration coverage for resource isolation. |
| [app/src/test/workspace-modes.test.tsx](../app/src/test/workspace-modes.test.tsx) | Focused regression/integration coverage for workspace modes. |
| [app/src/views.tsx](../app/src/views.tsx) | Map new workspaces onto existing feature implementations. |
| [backend/moth/__init__.py](../backend/moth/__init__.py) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [backend/moth/account_scope.py](../backend/moth/account_scope.py) | Namespace private project caches/consent by verified Cloud identity or isolated offline session. |
| [backend/moth/agent/manager.py](../backend/moth/agent/manager.py) | Allow existing tasks to reuse the appropriate private memory/index instance. |
| [backend/moth/agent/project_intelligence.py](../backend/moth/agent/project_intelligence.py) | Perform bounded incremental local static analysis using existing retrieval/memory. |
| [backend/moth/agent/retrieval.py](../backend/moth/agent/retrieval.py) | Accept bounded analysis paths and exclude outside-workspace/symlink files. |
| [backend/moth/inference/router.py](../backend/moth/inference/router.py) | Capture the approved endpoint and refuse account changes during consent/generation. |
| [backend/moth/model/benchmark.py](../backend/moth/model/benchmark.py) | Carry capability labels and score bounded reference/paraphrase consistency tasks. |
| [backend/moth/security/permissions.py](../backend/moth/security/permissions.py) | Require explicit write approval by default and validate stored Boolean settings. |
| [backend/moth/server/app.py](../backend/moth/server/app.py) | Reject invalid permission-setting values rather than granting truthy strings. |
| [backend/moth/server/extensions.py](../backend/moth/server/extensions.py) | Register the new authorized project-analysis subsystem before dependent routes. |
| [backend/moth/server/routes_agent.py](../backend/moth/server/routes_agent.py) | Give coding tasks their private scoped index and memory. |
| [backend/moth/server/routes_hybrid.py](../backend/moth/server/routes_hybrid.py) | Require profile-specific project-sharing consent; preserve legacy records without guessing ownership. |
| [backend/moth/server/routes_model.py](../backend/moth/server/routes_model.py) | Implement bounded history/search/regeneration and approved, endpoint-bound project context. |
| [backend/moth/server/routes_project_intelligence.py](../backend/moth/server/routes_project_intelligence.py) | Expose authenticated, project-authorized and profile-bound analysis/memory controls. |
| [backend/moth/server/routes_training.py](../backend/moth/server/routes_training.py) | Expose read-only source/prepared quality checks and tokenizer previews. |
| [backend/moth/training/quality.py](../backend/moth/training/quality.py) | Inspect bounded licensed records and produce non-destructive cleaning/quality evidence. |
| [backend/pyproject.toml](../backend/pyproject.toml) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [backend/tests/test_agent.py](../backend/tests/test_agent.py) | Focused regression/integration coverage for agent. |
| [backend/tests/test_benchmark.py](../backend/tests/test_benchmark.py) | Focused regression/integration coverage for benchmark. |
| [backend/tests/test_chat_living.py](../backend/tests/test_chat_living.py) | Focused regression/integration coverage for chat living. |
| [backend/tests/test_dataset_quality.py](../backend/tests/test_dataset_quality.py) | Focused regression/integration coverage for dataset quality. |
| [backend/tests/test_genesis_chat.py](../backend/tests/test_genesis_chat.py) | Focused regression/integration coverage for genesis chat. |
| [backend/tests/test_project_intelligence.py](../backend/tests/test_project_intelligence.py) | Focused regression/integration coverage for project intelligence. |
| [backend/tests/test_security.py](../backend/tests/test_security.py) | Focused regression/integration coverage for security. |
| [backend/tests/test_windows_ui_harness.py](../backend/tests/test_windows_ui_harness.py) | Focused regression/integration coverage for windows ui harness. |
| [docs/LIVING-INTELLIGENCE.md](../docs/LIVING-INTELLIGENCE.md) | Record actual source inventory, phase-by-phase evidence and limitations. |
| [scripts/test-genesis-desktop.py](../scripts/test-genesis-desktop.py) | Verify the actual signed Windows UI, eight workspaces, CPU progress and isolated full reset/fresh setup. |
| [scripts/test-published-desktop-update.py](../scripts/test-published-desktop-update.py) | Extend the existing signature/tamper/install-on-close harness to published 0.5.9 and signed candidates. |
| [scripts/windows-desktop-ui.py](../scripts/windows-desktop-ui.py) | Drive actual accessible disclosure/intro controls and wait for first-launch readiness. |
| [server/moth_server/__init__.py](../server/moth_server/__init__.py) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [server/moth_server/app.py](../server/moth_server/app.py) | Fence native HTTP work during explicit reset while preserving unrelated service APIs. |
| [server/moth_server/evolution/backends.py](../server/moth_server/evolution/backends.py) | Allocate non-reused native job IDs after reset. |
| [server/moth_server/evolution/bootstrap.py](../server/moth_server/evolution/bootstrap.py) | Preserve unregistered owned progress and allow explicit fresh initialization after reviewed erasure. |
| [server/moth_server/evolution/distributed.py](../server/moth_server/evolution/distributed.py) | Use monotonic job allocation for distributed work after reset. |
| [server/moth_server/evolution/engine.py](../server/moth_server/evolution/engine.py) | Stop automatic native work while a destructive reset requires recovery. |
| [server/moth_server/evolution/evaluation.py](../server/moth_server/evolution/evaluation.py) | Validate bounded reference suites and version capability-aware benchmark caches. |
| [server/moth_server/evolution/native_reset.py](../server/moth_server/evolution/native_reset.py) | Implement reviewed owned-root erasure, recovery fencing, verification and worker acknowledgements. |
| [server/moth_server/evolution/remote_eval.py](../server/moth_server/evolution/remote_eval.py) | Use monotonic job allocation so stale evaluation assignments cannot be reused. |
| [server/moth_server/intelligence/activity.py](../server/moth_server/intelligence/activity.py) | Project persisted history through authorization, category and cursor controls. |
| [server/moth_server/intelligence/discovery.py](../server/moth_server/intelligence/discovery.py) | Fence automatic preparation during/after empty reset and track background native writers. |
| [server/moth_server/intelligence/library.py](../server/moth_server/intelligence/library.py) | Track preparation writers so reset cannot erase files beneath active work. |
| [server/moth_server/intelligence/weakness.py](../server/moth_server/intelligence/weakness.py) | Include actual task-suite capability evidence and identify all unmeasured requested categories. |
| [server/moth_server/models.py](../server/moth_server/models.py) | Preserve internal version monotonicity and fence/track native pipeline work around reset. |
| [server/moth_server/routes/evolution.py](../server/moth_server/routes/evolution.py) | Expose Owner/reauth-protected full-reset preview/status/execution separately from legacy recovery. |
| [server/moth_server/routes/inference.py](../server/moth_server/routes/inference.py) | Avoid restoring removed native serving during reset recovery/verified empty state. |
| [server/moth_server/routes/intelligence.py](../server/moth_server/routes/intelligence.py) | Expose authoritative loaded-model status, verified improvement and privacy-filtered history. |
| [server/moth_server/routes/models.py](../server/moth_server/routes/models.py) | Track native pipeline work and report unavailable serving while reset is fenced. |
| [server/moth_server/routes/training.py](../server/moth_server/routes/training.py) | Carry scoped reset generation/cleanup acknowledgements through existing heartbeat endpoints. |
| [server/moth_server/training.py](../server/moth_server/training.py) | Fence leases, reject stale contributions, preserve worker consent and require cleanup acknowledgement. |
| [server/pyproject.toml](../server/pyproject.toml) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [server/tests/test_living_activity.py](../server/tests/test_living_activity.py) | Focused regression/integration coverage for living activity. |
| [server/tests/test_living_evaluation.py](../server/tests/test_living_evaluation.py) | Focused regression/integration coverage for living evaluation. |
| [server/tests/test_living_overview.py](../server/tests/test_living_overview.py) | Focused regression/integration coverage for living overview. |
| [server/tests/test_native_reset.py](../server/tests/test_native_reset.py) | Focused regression/integration coverage for native reset. |
| [worker/moth_worker/__init__.py](../worker/moth_worker/__init__.py) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |
| [worker/moth_worker/client.py](../worker/moth_worker/client.py) | Transport reset acknowledgement through the existing authenticated heartbeat. |
| [worker/moth_worker/runner.py](../worker/moth_worker/runner.py) | Cancel stale work then remove only proven deployment-owned checkpoint caches; report retained copies. |
| [worker/pyproject.toml](../worker/pyproject.toml) | Coordinate product version 0.6.0; leave third-party dependency versions unchanged. |

| [docs/LIVING-INTELLIGENCE-VERIFICATION.md](LIVING-INTELLIGENCE-VERIFICATION.md) | Record all 15 phase statuses, exact changed-file necessity, real verification evidence, candidate results and remaining limitations. |
