# Autonomous MOTH update

Branch: `codex/autonomous-moth-evolution`, based on `4131f33`.
No production deployment, release, updater or signing configuration changes are part of this work.

## Requirement-to-code audit

The existing implementation is retained:

| Requirement | Implementation and starting gaps |
| --- | --- |
| One evolving model | `evolution/engine.py`, `memory.py`, `v2.py`: current stable checkpoint, candidate descendants and rollback history already exist. Empty-install initialization and padded model versions were absent. |
| Adaptive growth | `backend/moth/model/growth.py`: real depth/FFN expansion, preserved logits, optimizer migration. `evolution/backends.py` supports expanded local/worker candidates; evaluation gates and approval remain mandatory. Training loss was not carried into exported model evidence. |
| Retention | `evolution/v2.py`, `evaluation.py`: historical approved-build replay and capability regression gates already exist. Masked conversation datasets deliberately use local training because the current worker protocol transfers tokens only. |
| Data | `datafactory/catalog.py`, `fetch.py`, `clean.py`, `build.py`, `intelligence/library.py`: licensed pinned sources, resumable verified downloads, cleaning, near deduplication, tokenization and approval. Automatic preparation on data starvation was missing. |
| Compute | `evolution/compute.py`, `backends.py`, `distributed.py`, `worker/moth_worker/runner.py`: real CPU/CUDA training, leases, verified updates, checkpoints and resource budgets. Owner worker controls needed integration with evolution scheduling. |
| Dashboard | `OwnerDashboard.tsx`, `IntelligenceView.tsx`, `EvolutionView.tsx`, `ops.tsx`: existing real status and controls, but owner navigation and consolidated exact model statistics needed work. |
| Autonomous operation | Existing scheduler trains/evaluates/canaries/promotes/rolls back. Missing initial model/data preparation and worker-command integration are being added without replacing the engine. |

## Phase 1

An explicit owner-only, recently authenticated `POST /v1/admin/evolution/initialize` creates an
untrained 99,648-parameter MOTH 0.01 only for an empty installation. The byte tokenizer needs no
external corpus. It registers an uploaded candidate; it does not bypass evaluation or deploy random
weights automatically. A filesystem run lock, atomic checkpoint, integrity verification and registry/
unregistered-weight guards prevent resetting an existing lineage. Existing releases are returned
unchanged. Existing labels remain intact; newly assigned versions use two-digit minor numbers.

Trainer checkpoints and model manifests now retain measured train and validation losses, enabling
the existing growth controller to use actual capacity/overfitting evidence. Existing growth, optimizer,
replay, promotion and rollback systems remain the implementation.

No genuinely trained Foundation checkpoint was found in this checkout. Small-model training and
architecture smoke tests establish execution, not Foundation model quality or completed training.

Phase 1 verification: 19 backend tests passed (real training, deterministic resume, growth weight and
optimizer preservation, exports); 7 server checks passed across initialization, unregistered-weight
protection, migration, expanded-worker training, replay, promotion safeguards and actual deployment
rollback. The curriculum promotion integration also passed. Initial API testing caught and fixed a
preset argument collision before commit.

## Phase 2

`intelligence/discovery.py` adds automatic, bounded preparation from the trusted pinned catalog.
Only the locally available PSF-licensed Python standard library is enabled by default; owners select
additional catalog sources through the recently authenticated discovery policy API. Unknown sources,
unknown licenses and missing attribution are rejected. New upstream revisions still require the
existing explicit pin approval. Download/working-space budgets, retry backoff and build reuse bound
unattended work. Revoking a dataset blocks automatic preparation of its sources, including during a
build; changing preparation limits cannot silently reapprove revoked data.

The engine requests preparation when it cannot plan training. The existing Data Factory performs
verified resumable downloads, normalization, secret/personal-data scrubbing (now also for code), exact
and near deduplication, held-out decontamination and tokenization with the existing lineage tokenizer.
Build status now includes real progress messages and token counts. Pending/revoked duplicates are not
approved and active prepared files are not recopied on a duplicate build.

Verification: a real PSF standard-library build was cleaned, tokenized and registered against MOTH
0.01's tokenizer. Discovery/permission/license/budget/revocation and existing library integration tests
passed (3 server tests); all 6 Data Factory tests passed, including resumed downloads, checksum
rejection, deduplication, provenance, and actual mixture training. Remote catalog bytes in regression
tests are served by deterministic HTTP fixtures; a live full remote-corpus download was not performed.

## Phase 3

Owner worker controls now start a selected worker, start all compatible online workers, or enable
server-only CPU training using the existing evolution engine. Starts validate memory capacity and
select the current deployed checkpoint; if data is insufficient, Phase 2 prepares approved sources.
Participant selection is enforced at capacity selection, distributed shard creation and job claiming.
Starting a different participant set while a cycle is active is rejected rather than changing a run.
Existing worker Pause/Resume remains available; Stop releases its job without revoking its credential.
Global pause/resume/cancel controls are exposed next to the worker controls.

Paused workers now save a checkpoint and heartbeat their lease. Stop/cancel notifications make current
workers save progress and release their in-memory job. Completed training is checkpointed before result
upload; network failure no longer loses the last optimization steps. Old worker clients remain API
compatible, but need this updated worker code for prompt stop notifications. Existing stale-result
lease validation protects the stable model regardless.

Worker heartbeats report measured steps, tokens, loss and checkpoint step, and completed job history
retains actual training measurements. Container CPU and RAM quotas now bound hardware reporting and
CPU thread selection. Existing GPU execution/resource limits are preserved. Worker/distributed export
no longer copies its parent's accepted model label into an unaccepted candidate.

Verification: 14 server tests passed, including selected-worker exclusion, pause/lease retention,
stop and real checkpoint resume, Start All, genuine server CPU training, existing training-network
regressions, actual expanded-worker training and two-worker distributed recovery. Two worker UI tests
and TypeScript checks passed. Container quota and deterministic trainer resume checks passed.
CUDA/Windows hardware is absent; native GPU execution and Windows packaging were not run. Distributed
training remains the existing synchronized, token-weighted local-update algorithm, not shared AdamW
state across machines. Full optimizer continuity is supported by local development checkpoints;
worker jobs retain AdamW within a resumable job but start fresh moments on a new assignment.

## Phase 4

Owner navigation now has exactly five main sections: Overview, Intelligence, Network, Community and
Settings. All original model/evaluation-data, evolution, data/feedback/knowledge, server, worker,
user, billing/referral, update, policy/flags and audit panels remain available under those groups.
The desktop's broader navigation, branding and updater screens are unchanged.

`ModelOverview.tsx` and owner-only `/v1/admin/model-overview` show exact registered parameters,
architecture/config, verified checkpoint bytes/hash, recorded cumulative steps/tokens, live training
loss/progress, CPU/GPU active-worker counts, promotion/retention gates, accepted ancestry and growth/
failure history. Missing measurements explicitly show Unavailable. Checkpoint verification is cached
only for an unchanged file stat/hash identity and detects actual corruption. Comparisons require
matching held-out datasets/metrics. The existing interactive benchmark timeline remains accessible.

The dataset library now exposes unattended source approvals and download/preparation limits, live
build messages, actual token counts and recorded model usage. Unknown licenses cannot be enabled.
Advanced architecture, source and history details are expandable.

Verification: 7 focused server tests passed, covering owner authorization, initialization/migration,
exact metrics, checkpoint corruption and discovery. Five focused UI tests passed, covering the five
sections, preserved panel navigation, missing metrics, worker controls and evolution/parameter charts;
TypeScript checks passed. Browser/native desktop visual testing is deferred to final verification.

## Phase 5 recovery checkpoint

The cloud disconnection left Phase 5 uncommitted after Phase 4 (`e196ada`). Its working files
survived and are being preserved before further validation. Prior successful checks included a real
PSF CPU lifecycle (MOTH 0.01 → 0.02 → 0.03, 32 steps/16,384 tokens, original-weight rollback), 140
backend tests, 25 frontend tests, a frontend build and Chromium checks against that test database.
These are historical results; final recovery verification is pending.

The full server run reported 130 passed and one failure:
`tests/test_evolution.py::test_full_cycle_continued_training_to_deployment` at its repeat-planning
assertion. Its fixture assumes manual datasets only; newly enabled automatic preparation can introduce
another dataset asynchronously. The recovered fixture explicitly disables discovery for these legacy
manual-data cases; automatic preparation is exercised separately in `test_autonomous_lifecycle.py`.
This change still needs its recovery test run. The interrupted final deployment-lock patch did not
reach `models.py`; its necessity and minimal completion will be checked before final delivery.

No trained Foundation model is claimed. No production release, deployment, updater or release-workflow
change is authorized by this phase.

## Phase 5 implementation

Recovered progress is saved remotely as `595df9b`. The existing engine, Data Factory, growth functions,
worker protocol and deployment mechanism remain in use. Phase 5 closes their integration gaps:

- An explicit, recently authenticated owner action evaluates and activates the untrained initial
  baseline. It never replaces an existing deployed lineage or calls an initialized model trained.
  Interrupted registration reuses the original checkpoint and release row; missing/corrupt progress
  blocks initialization rather than generating replacement weights.
- Data starvation starts approved preparation; completion wakes the scheduler immediately. Interrupted
  builds become retryable failures while verified downloads remain intact. Automatic standard-library
  builds exclude the server's fixed general evaluation files. Trusted remote revision checks run with
  bounded frequency, and changed revisions still require the existing approval gate.
- Download streams are bounded by pinned size. CPU/GPU job admission respects reported available
  memory, GPU usage and owner GPU-memory fractions. Existing CUDA execution is preserved.
- Continuation locks cover initialization and export as well as training. Development-checkpoint
  corruption cannot silently discard optimizer/RNG state; grown checkpoints are atomic and verified.
  Quarantined worker progress cannot silently restart from the base weights.
- Training tokens, distributed local steps and losses come from recorded work. Unknown historical
  totals remain unknown. Accepted ancestry remains visible after rollback. Rejected or unsigned
  candidates do not consume the next accepted version number.
- Parent checks prevent a candidate replacing a manually selected model. The final parent comparison
  occurs inside the existing deployment lock, including promotion of an already loaded canary.
  Existing retention, improvement, signing, health and monitored-traffic gates remain required.

The remaining regression was a fixture isolation issue in
`test_full_cycle_continued_training_to_deployment`: automatic preparation could add a curriculum build
while this manual-dataset test was running, so replanning did not necessarily enumerate the original
manual experiment among skipped configurations. The legacy manual-data fixture now explicitly turns
off discovery; its assertions are preserved. The separate real automatic lifecycle test starts with
no approved data and verifies preparation, two evaluated promotions, real monitored requests,
signatures, parent ancestry, cumulative counts and rollback. Both tests passed after recovery.

Fresh recovery verification so far: all 140 backend tests passed; the corrected server regression
and three autonomous lifecycle/recovery cases passed. The PSF CPU lifecycle recorded 20 steps/10,240
tokens at MOTH 0.02 and cumulative 32 steps/16,384 tokens at MOTH 0.03, each with 99,648 parameters.
Unchanged parameter count demonstrates that version increments are independent of growth. Dedicated
growth tests verify real expansion separately. Final focused server/frontend checks are recorded below
once complete.

## Files changed in Phase 5 only

No dependency, database-schema, GitHub workflow, software updater or production-infrastructure file was changed.

| File | Necessary Phase 5 change |
| --- | --- |
| `app/src/features/owner/ModelOverview.tsx` | Expose explicit untrained-baseline activation and accurate last-activation wording. |
| `backend/moth/datafactory/build.py` | Exclude configured general-evaluation files from automatic standard-library corpora. |
| `backend/moth/datafactory/catalog.py` | Allow update checks to target only approved catalog sources. |
| `backend/moth/datafactory/fetch.py` | Bound streamed downloads by their pinned size. |
| `backend/moth/model/registry.py` | Export measured training tokens. |
| `backend/moth/training/continue_run.py` | Lock initialization/export, reject damaged development state, verify grown initialization and return actual tokens. |
| `backend/moth/training/trainer.py` | Preserve unknown historical totals instead of fabricating cumulative counts. |
| `backend/tests/test_continue_v053.py` | Require corrupted development state to fail closed. |
| `backend/tests/test_datafactory.py` | Verify oversized responses cannot exhaust the download budget. |
| `docs/AUTONOMOUS_UPDATE.md` | Record recovery, the precise regression, validation, limitations and changed-file reasons. |
| `server/moth_server/evolution/backends.py` | Carry measured worker steps/loss and preserve unknown imported-history totals. |
| `server/moth_server/evolution/bootstrap.py` | Activate only an explicitly evaluated initial baseline; recover interrupted registration without new weights. |
| `server/moth_server/evolution/compute.py` | Respect owner GPU-memory limits when calculating usable worker capacity. |
| `server/moth_server/evolution/distributed.py` | Apply the same admission policy and report measured local steps/loss across rounds. |
| `server/moth_server/evolution/engine.py` | Keep stable ancestry coherent, stop stale-parent promotion and restore metadata after signing failure. |
| `server/moth_server/evolution/v2.py` | Advance model versions from accepted history and parent identity. |
| `server/moth_server/intelligence/discovery.py` | Bound approved-source revision checks and use held-out-safe automatic preparation. |
| `server/moth_server/intelligence/library.py` | Recover interrupted builds and wake evolution when approved automatic preparation finishes. |
| `server/moth_server/models.py` | Record native initialization provenance and enforce parent identity inside the deployment lock. |
| `server/moth_server/routes/dashboard.py` | Expose baseline origin and retain accepted descendant history after rollback. |
| `server/moth_server/routes/evolution.py` | Add owner-authenticated baseline activation and respect worker memory limits on start. |
| `server/moth_server/routes/intelligence.py` | Recover library work once during server startup. |
| `server/moth_server/serving.py` | Forward the expected parent when promoting a loaded canary. |
| `server/moth_server/training.py` | Account for available RAM, occupied GPU memory and owner GPU fraction in job admission. |
| `server/tests/test_ascension_gaps.py` | Verify worker candidates cannot inherit their parent accepted model label. |
| `server/tests/test_autonomous_lifecycle.py` | Exercise genuine PSF CPU preparation/training, two promotions, signatures, rollback and recovery. |
| `server/tests/test_discovery.py` | Check every existing trusted catalog license remains approvable. |
| `server/tests/test_evolution.py` | Isolate the legacy manual-data fixture from automatic preparation without weakening its assertions. |
| `server/tests/test_evolution_v053.py` | Assert known imported steps and unavailable historical token totals accurately. |
| `server/tests/test_native_lineage.py` | Verify native origin and recovery of interrupted registration without replacing seed weights. |
| `server/tests/test_training_controls.py` | Verify resource admission and refusal to reset quarantined worker progress. |
| `worker/moth_worker/hardware.py` | Report available RAM within the effective memory budget. |
| `worker/moth_worker/runner.py` | Refuse a silent reset after worker-checkpoint quarantine. |

## Operating and validation limits

For an empty installation, use Intelligence → MOTH AI → Initialize MOTH 0.01, then explicitly evaluate
and activate the untrained baseline. Start server CPU training or compatible workers from Network.
An existing lineage is reused; initialization never shrinks or replaces it. Data source approvals,
resource limits, growth approvals and all evaluation/monitoring gates continue to apply.

Recovery verification used a CPU-only Linux environment. Actual CUDA execution and native Windows
packaging could not run here; GPU admission arithmetic is tested with reported hardware fixtures.
Live Hugging Face downloads were not performed (the environment does not allow that host); real local
PSF preparation and checksum/resume/download-budget regression fixtures were exercised. Production
Desktop/Cloud update installation was not attempted. Existing updater source, signing configuration,
release workflows and infrastructure are unchanged. No trained Foundation checkpoint was verified,
and these small-model tests do not establish Foundation training completion or useful AI quality.

GitHub delivery: recovery checkpoint `595df9b` and completed implementation `455dc47` were pushed to
`codex/autonomous-moth-evolution`. Draft pull-request creation was attempted with `gh pr create` against
`claude/jolly-darwin-2qeihd`, but `https://api.github.com/graphql` returned Forbidden. Git transport still
works; no merge, production deployment or GitHub Release was attempted.
