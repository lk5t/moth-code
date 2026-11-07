# ASCENSION continuation audit — 2026-11-07

Baseline: `175faf1` on `claude/jolly-darwin-2qeihd`. This is an incremental audit of the existing
implementation, not a replacement plan. Historical release/quality claims in the changelog and
TEST_RESULTS are not independent evidence that the artifacts or infrastructure exist in this checkout.


## Missing-feature implementation — latest work

This section supersedes earlier limitations where explicitly noted. Earlier test counts remain
historical evidence; current validation is listed below.

### New working functionality

- **Measured batch autotuning:** local evolution and worker training run at most four candidate
  microbatches (one warm-up and two timed forward/backward passes each). Only divisors of the requested
  batch are considered; gradient accumulation preserves the effective batch and optimizer-step count.
  Probes take no optimizer steps and restore the model's mode and RNG. Memory admission reserves room
  for AdamW state and honors container/GPU allocation limits. The selected batch and raw timings are
  recorded, checkpointed and reused on resume. CUDA allocator failures reduce the candidate set rather
  than substituting a fake measurement. CUDA behavior still requires hardware verification.
- **Worker recovery:** periodic and graceful-stop checkpoints now use atomic writes with checksums.
  Invalid checksums are refused and preserved for diagnosis. Effective batch mismatches on resume fail
  explicitly. Training still returns one verified contribution per assigned job.
- **Evolution UI:** the automatic-evolution switch now sends the API's required `changes` envelope.
  An experiment panel shows real statuses, candidate releases, growth sizes, approval requirements and
  recorded batch/accumulation choices. Existing advanced controls and worker participation remain.
- **Intelligence timeline:** the existing chart can display recorded parameter counts, training steps
  and validation loss, alongside held-out benchmarks. Unmeasured values are omitted, not invented.
- **Real-process E2E runner:** repaired settings requests and the startup race with the default-enabled
  scheduler; added approved-source selection, corpus bounds, a deadline and per-worker CPU limits.
  Supplied work directories must be new; existing runs are never overwritten. It no longer labels an
  arbitrary uploaded package an official Foundation release. Failed cycles return failure status.
- **Full foundation architecture check:** `scripts/verify-foundation-training.py` creates an isolated
  stdlib-source training run at the actual 49,295,872-parameter architecture, updates weights, resumes,
  exports, verifies and generates. CI now runs it on Linux. It explicitly does not claim model quality.

### Real results obtained

- Full backend suite after initial implementation: **135 passed**; autotuning/recovery tests run real
  backward passes and check unchanged probe weights/RNG, preserved budgets and resume without re-probing.
- Frontend: **21 passed**, typecheck and production build passed, including the settings request and
  measured timeline UI tests.
- Full architecture: **111 weight tensors updated**, resumed to step 3 / **192 tokens**, verified export,
  **8 generated tokens in 8 streaming chunks**. Validation loss was 9.76366 at step 2 and 9.58034 at step 3.
  These are smoke measurements on a newly initialized model, not the published Foundation's quality.
- Real HTTP server + **two separate MOTH Worker processes**, using that full-size smoke package and
  Python stdlib data (PSF-2.0): **completed in 661 seconds**. Both distributed rounds applied verified
  updates; **8,192 tokens total**, **4,096 per worker**. Probe loss **9.51099 → 8.81538 → 8.50130**.
  Two different CPU workers agreed on candidate held-out loss **8.47158 over 14,329 tokens**. Candidate
  v2 passed the configured gates, served a 20% canary, passed the one-minute health-monitoring window
  and became stable in the isolated server. There was no user chat traffic during that window; this
  does not verify traffic-based latency/error behavior or general conversational quality.
  Reports: `/workspace/scratch/moth-foundation-verify-20261107/report.json` and
  `/workspace/scratch/moth-e2e-report.json` (local artifacts, not published model releases).
- Server and worker bundles built with a disposable test signing key. Signature and checksums verified,
  but full release verification **correctly failed** because the embedded production public key differs
  from that test key. Production keys and verification were left unchanged. These are not publishable
  release artifacts.
- The first simultaneous PostgreSQL/SQLite/full-size E2E attempts contended for the four-core quota,
  starved low-priority test trainers and timed out. They were stopped, their logs retained, and database
  validation rerun sequentially. No timeout was reclassified as a pass or assertions disabled.

### Feature classification

| Feature | Current classification |
| --- | --- |
| Native CPU streaming, model loading, checkpoint recovery; 49.3M architecture training/resume | Implemented and tested. Published Foundation quality remains a separate blocked check. |
| Batch autotuning, research variants, replay/curriculum, growth and continued training | Implemented and tested on CPU; CUDA tuning/training awaits hardware verification. |
| Shared Cloud/worker rounds, real contributions, CPU evaluation, staged promotion | Implemented and tested with full-size real processes. Existing tiny-model tests cover desktop participation and failed-worker recovery. |
| Dashboard, timeline, evolution controls and experiment/growth display | Implemented with real backend data; UI regression tests pass. Native Windows execution awaits verification. |
| PostgreSQL and SQLite migrations/integration | Implemented and tested: PostgreSQL 116 passed / 1 SQLite-only skip; SQLite 117 passed. |
| Genuinely trained Foundation evaluation | Blocked until actual training produces a verified checkpoint and matching held-out corpus. Completion of the historical run is unverified; scratch-training preparation and safe resume are implemented and tested now. |
| Windows installer/startup/updater | Existing implementation/CI retained; awaiting a Windows runner with MSVC/WebView2/Rust and signing configuration. No real Windows installer built here. |
| NVIDIA training/inference and heterogeneous GPU/CPU performance | Implemented paths awaiting hardware verification; `torch.cuda.is_available()` is false. |
| Signed production release artifacts | Blocked: no private signing key matching the pinned production public keys. Test-key artifacts cannot be published. |
| Residual-width/head/tokenizer architecture migration and distillation | Partial: only compatible depth/FFN growth is implemented. Major architecture changes remain approval-gated rather than silently replacing a lineage. |

No production deployment, release publication, production-key change, database reset or model-data
replacement was performed. The PostgreSQL database was a disposable, loopback-only Docker test instance, removed after validation.

## Implementation checklist

| Phase / requirement | Status and evidence |
| --- | --- |
| Audit existing progress | Done: reviewed history through the 0.5.1 intelligence, 0.5.2 groundwork, 0.5.3 evolution/distributed/serving, 0.5.4 experience and latest E2E commits; component inventory, architecture, milestone, deployment, release and limitation docs. |
| 0.5.1 router, streaming, knowledge, consent, library and curriculum | Implemented. `test_intelligence_v051.py` now passes all 10 tests using registered/evaluated/deployed real tiny MOTH weights instead of bypassing the registry. Existing external-provider support remains opt-in; no provider configured here. |
| 0.5.2 held-out evaluation and historical comparisons | Implemented in `model/capabilities.py`, `model/benchmark.py`, `evolution/evaluation.py`, `evolution/memory.py`; code execution, instruction-format, math/reasoning and per-domain loss benchmarks. Instruction-format accuracy does not establish semantic conversation quality. |
| 0.5.2 release gates and compatibility | Existing checks cover package integrity, tokenizer, shapes, finite weights, inference and regressions. This continuation also refuses non-finite release measurements. Actual foundation package and its held-out files are absent locally; its release cannot be reproduced here. |
| 0.5.2 native streaming and model loading | Implemented in Cloud, local backend and React chat. Real tiny-model streaming, consent, history and fallback tests exercise integration; production foundation capability and Windows behavior remain unverified here. |
| 0.5.3 research lab and continuous learning | Existing curriculum mixtures, replay, weakness-driven variants, experiment hashes, early stopping, development checkpoints and historical gates. Growth evidence is now restricted to the selected ancestry, and growth size counts only consecutive plateau cycles. |
| 0.5.3 hardware optimization | Partial: memory admission, CPU thread/GPU limits, speed-proportional worker steps, learning-rate ranking, cosine schedules, configured batch/accumulation and compute budgets exist. Superseded by the implementation below: real batch autotuning now preserves effective batch/step budgets and persists its decisions. GPU execution still needs hardware validation. |
| 0.5.3 coordinated Desktop/Cloud/workers | Implemented as local-SGD rounds in one experiment, token-weighted verified aggregation, expired-lease recovery, CPU evaluation consensus, desktop participation and contributions. Data preparation stays on the server. This is not synchronous heterogeneous all-reduce. |
| 0.5.3 integrity and recovery | Existing atomic hashed checkpoints and OS run locks; continuation recovers from malformed/stale latest pointers and rejects damaged/missing distributed starting weights before issuing jobs. Distributed rounds retain aggregate weights/history, but do not persist each worker's AdamW moments as one global optimizer state. |
| 0.5.3 adaptive growth | Existing depth/FFN expansion preserves logits, migrates optimizer moments, trains an isolated candidate and requires approval above the configured ratio. Regression tests cover actual small-model weight transfer and further optimization. Residual-width/head/tokenizer migrations and distillation are not implemented. |
| 0.5.3 model promotion | Existing signed artifacts, gates, canary serving, pinning, monitoring and rollback. Production rollout/approval settings must be reviewed by the Owner before use; no live deployment performed. |
| 0.5.4 navigation and dashboards | Existing Chat, Code, Intelligence, Evolution, Network and Settings preserved. Dashboard uses stored measurements, versions, lineage, dataset history and contributions. No redesign performed. |
| CI/CD and installers | Existing CI, Windows desktop/update, server and model-release workflows retained. Local signing/verification tests use disposable test keys. Real Windows packaging, PostgreSQL matrix, production signing and live updates are not verified by these Linux checks. |

## Focused changes

- Chat test setup follows the real registry/evaluation/deployment contract; production routing remains strict.
- Checkpoint discovery tolerates a malformed, missing-field, unsafe or stale `latest.json` and scans the
  newest checkpoint; verified recovery still checks its checksum and quarantines damaged weights.
- Growth ignores unrelated lineages, rejects non-finite improvement evidence, and counts the current
  consecutive plateau rather than accumulating every old plateau.
- Distributed training verifies the recorded checksum of the development checkpoint or base weights
  before loading or issuing jobs. A missing/damaged development checkpoint is reported explicitly.
- Stable-release criteria reject infinite or NaN measurements, including apparent infinite speed.

No database schema, API, model architecture, tokenizer, existing weights, datasets, accounts, worker
registrations, rewards, branding or production infrastructure was changed.

## Validation and remaining prerequisites

Run commands with `/workspace/moth-code/.venv/bin` on PATH; backend verification invokes `python`
internally. Limit CPU suites with `OMP_NUM_THREADS=2 MKL_NUM_THREADS=2`.

Current execution results are recorded below after the suites finish. Previous onboarding ran backend
121/121, frontend 19/19, typecheck/build and browser entry successfully; server baseline was 107 passed,
5 failed due to the registry-bypassing chat fixture. Those baseline failures are fixed rather than skipped.

Remaining prerequisites: the trained MOTH package/checkpoint and matching approved dataset cache for
`scripts/e2e-evolution-cycle.py`; NVIDIA hardware for CUDA/Windows GPU validation; a Windows runner with
MSVC/WebView2/Rust for installer verification; PostgreSQL for its database matrix; production signing and
service configuration for release readiness. Do not replace missing artifacts with randomly initialized
weights and describe that as foundation-model validation. The documented foundation target is
49,295,872 parameters; no claim about a currently deployed model or its quality is established here.

Do not publish or deploy without explicit Owner authorization. Completion of CPU tests alone does not
make all ASCENSION requirements or production releases complete.

### Executed checks on the continuation

| Check | Result |
| --- | --- |
| Backend full suite, final backend changes | **133 passed** (39.74 s). Includes bit-identical training resume, checkpoint integrity, real optimizer updates and depth/FFN growth. |
| Intelligence suite after registry fixture repair | **10 passed** (31.88 s); the prior five failures are no longer present. |
| New evolution integrity suite | **5 passed** (3.43 s): selected-lineage evidence, corrupt/missing base refusal, and expanded-model memory admission. |
| Approval-to-expanded-candidate training integration after memory-admission fix | **1 passed** (33.17 s), with actual tiny MOTH training. |
| Frontend | **19 passed**; typecheck and production build passed. UI source unchanged. |
| Foundation architecture | Meta-device parameter enumeration: **49,295,872**. This verifies architecture size, not trained-model quality. |
| CUDA availability | **False**; GPU execution not run. Rust/Cargo also absent; Windows packaging not run on this Linux host. |

Growth memory admission now includes the expanded parameter count and additional layers, rather than
using the smaller parent's estimate. All focused tests use isolated temporary state; no persistent
training runs or production records were altered.

The complete existing SQLite server suite finished with **112 passed, 0 failed** in 378.20 s.
It exercises real two-worker distributed rounds, expired-lease recovery, desktop participation in the
same experiment, two-worker CPU evaluation, dataset/consent handling, migrations, serving pinning,
staged promotion/rollback, signed model packages, accounts, rewards and updates. Its collection preceded
the new integrity file and the memory-admission edit; the additional five integrity cases and the
post-edit growth integration passed separately as listed above. No tests were skipped to obtain these
results. PostgreSQL, real CUDA/Windows and the full-size foundation E2E remain unrun.


## Final validation and Foundation-status correction

The user clarified that Foundation training may never have finished. A filesystem search including
ignored files found **no `.pt` checkpoints, `latest.json`, or split model weights anywhere in this
checkout**, excluding only dependency/Git/cache directories. No remote `model-*` tags were listed.
The sole existing model manifest is `server/w/models/moth-cloud-test/manifest.json`, describing a
**127,296-parameter test model** with no accompanying weights. Therefore this repository verifies the
architecture/pipeline, not a completed trained Foundation. FOUNDATION, LIMITATIONS, TEST_RESULTS and
the changelog now distinguish historical claims from verified current evidence.

Additional implemented functionality:

- `train-moth-foundation.py --prepare-only` prepares approved catalog data, tokenizer, corpus mixture
  and lineage without starting model training. It also supports approved-source selection, development
  corpus caps, explicit CPU/CUDA selection and optional batch-probe disablement.
- Existing corpus, tokenizer and replay mixture are retained; incompatible sources, tokenizer/build
  fingerprints or missing preparation metadata on a progressed run cause explicit errors.
- The trainer verifies the resumed checkpoint's tokenizer/build identity. If all resumable checkpoints
  are damaged, it refuses random reinitialization, preserves the damaged artifacts and leaves the best
  weights untouched. Random initialization remains available in a genuinely new run directory.
- Worker checkpoints retain optimizer/sampler/RNG and tuning state. The focused recovery test verifies
  checksums, resume without re-probing, acceptance of the real contribution and checkpoint cleanup.
- Owner batch-autotune settings propagate into local and distributed worker specs; existing clients
  and protocols remain compatible. No database schema change was required.

| Final check | Executed outcome |
| --- | --- |
| Backend full suite, including scratch preparation/train/resume and all-invalid-checkpoint protection | **138 passed**, 49.90 s |
| Server on PostgreSQL 16, sequential rerun | **116 passed, 1 skipped**, 443.25 s; skip is the test constructing an old SQLite database |
| Server on SQLite, sequential rerun | **117 passed**, 408.27 s; includes the legacy SQLite migration |
| Focused worker resume and evolution integrity after final recovery edits | **6 passed**, 4.64 s |
| Frontend final suite | **21 passed**; typecheck and build passed |
| Full-size training/export/streaming smoke and real HTTP/two-worker evolution | Passed as detailed above; this is not Foundation-quality validation |
| Signature/package verification with a test key against production pins | Correctly refused due to key mismatch; production signing remains unavailable |
| Windows / NVIDIA hardware | Not run; platform/hardware absent |

The new scratch-pipeline subprocess test uses real approved Python-stdlib data and a deliberately tiny
model: prepare-only → train to step 2 → resume to step 3. It verifies that data/tokenizer/lineage bytes
remain identical, optimizer state persists and an incompatible source request is refused. The separate
49.3M smoke checks the full target architecture. Neither replaces held-out evaluation of a genuinely
trained Foundation model. That future quality check requires the actual trained weights and their
matching approved corpus/evaluation files; do not start an expensive training run or reset existing
progress merely to obtain a green status.

Runtime signing-variable presence was checked without reading values: `MOTH_RELEASE_SIGNING_KEY`,
`TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` and `MOTH_CLOUD_URL` are unset.
Enter production configuration only through secure settings when preparing an authorized release.
No release or production deployment was performed. Existing update/signature infrastructure is retained;
server regression coverage includes signed updates, rollout and rollback, while real Windows installer
execution still needs its own runner.

## Strict minimal-change fixes (latest)

Only the identified integration gaps were addressed in this pass. Existing model expansion, worker
protocol, mixture format, UI components, authorization helpers and model lifecycle were reused.

- Single-worker growth now expands an isolated verified base on the server using the existing growth
  functions, checks initial function preservation, sends the expanded config/weights through the
  existing worker protocol, and validates/packages the actual expanded result. Norm bounds remain
  active for zero-initialized projections; an oversized update is rejected in regression coverage.
- The Desktop now calls the existing growth-approval endpoint. Use Cloud Workers now sends the required
  settings `changes` envelope. No navigation, styling or branding redesign was performed.
- Replay composes current data with up to 65,536 historical tokens per split/domain/build, drawn only
  from still-approved compatible builds in the model's lineage. Originals are untouched, licensing
  metadata is retained, and revoking a replay dataset cancels dependent experiments.
- Best checkpoints retain the optimizer/RNG state of their selected weights; the exported candidate
  and its development checkpoint now come from the same snapshot. Legacy weight-only best checkpoints
  remain intact; a complete checkpoint is selected instead when continuation state is required.
- Stable promotion waits for the configured monitored request count and successful model-manifest
  signing. Existing rollback behavior is retained.
- Assistant-masked training is routed to the existing local trainer. Token-only worker/distributed
  paths explicitly refuse it rather than silently losing masks. Full masked distributed training
  needs a version/capability-negotiated mask transport; that protocol extension was deliberately not
  implemented in minimal-change mode. Distributed growth and asynchronous straggler scheduling remain
  outside this pass; no distributed architecture rewrite was attempted.

Focused validation: 7 integration checks passed (new worker-growth/promotion/replay regressions plus
existing curriculum, local growth, distributed recovery and rollback checks); 5 existing evolution
integrity checks passed; 14 backend training/continuation/autotuning checks passed; 3 focused UI tests
passed and TypeScript type checking passed. The offline test fixture explicitly sets min_requests=0;
a separate regression verifies that production-style min_requests=2 blocks promotion without traffic.
No broad suite rebuild, dependency change, release publication or production action was performed.
