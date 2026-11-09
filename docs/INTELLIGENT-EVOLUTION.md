Current continuation results and remaining verification: [INTELLIGENT-EVOLUTION-VERIFICATION.md](INTELLIGENT-EVOLUTION-VERIFICATION.md). The phase notes below are historical progress records.

# Intelligent Evolution — phased implementation

Branch: `claude/jolly-darwin-2qeihd`. Prior UI/progress changes are saved at `c867035`.
The 0.5.9 Desktop and Server release workflows failed their server-test gates and did not publish.
This update is not a public-release readiness claim.

## Source findings before Phase 1

- `evolution/settings.py`, `planner.py`, `compute.py`, `engine.py`: existing validated Owner configuration, measured learning-rate ranking, resource admission, inference protection, pauses and daily budgets. The requested mode/priority controls were absent; the settings UI exposed low-level numeric tuning.
- `evolution/backends.py`, `distributed.py`, `remote_eval.py`, `evaluation.py`: existing local subprocess training, worker jobs, validated contributions, recoverable checkpoints, held-out evaluation and promotion gates. Reuse these; physical GPU behavior remains unverified here.
- `backend/moth/community/participant.py` and `server/routes/evolution.py`: contribution persists by server/credential; explicit account/device consent separation needs further work. Owner training-start operations can unpause selected workers. Do not describe this as the requested independent personal-device authorization system.
- `models.py`, `evolution/backends.py`, `evolution/genesis.py`: model/package identity and lineage exist; earned public milestones and successful-deployment revision numbering need a separate implementation and migration. Do not relabel checkpoints as earned milestones.
- `IntelligenceHub.tsx`, `TrainingProgress.tsx`, `routes/intelligence.py`: measured progress and five sections exist; authoritative stale/disconnected handling and deployment/revision synchronization require further work.
- Existing signed release workflows enforce CI, signatures and Windows integration gates. No signing or updater changes are needed for Phase 1.

This is a scoped source inventory, not certification of all twelve phases. The detailed security, distributed-performance and public-release verification requested in later phases remains outstanding.

## Regression correction

`server/tests/test_workers_v05.py::test_uninstall_leave_revokes_the_worker` reproduced
`IndexError: list index out of range` because it expected a revoked worker in the normal list.
The updated assertion requires an empty list and a preserved revoked database tombstone; the
existing HTTP 401 credential assertion remains. Five focused worker/revocation tests pass.
GitHub log downloads are blocked by the environment's network policy; the error above was
reproduced locally, not copied from inaccessible CI logs.

## Phase 1 — delivered controls

The existing Owner Evolution settings and Training panel reuse five controls:
Automatic Evolution, Training Mode, Cloud Workers, Training Priority and Automatic Model Promotion.
Contribution remains a separate local-device control; its stronger account/device consent model
belongs to Phase 3 and is not claimed complete here.

Mode selection applies CPU-thread and duty-cycle ceilings within existing Owner limits. Eco uses
lower ceilings, Automatic uses intermediate ceilings, and Maximum uses the configured allowance.
Existing installations retain their effective limits until a mode is selected. Stored settings are
merged without destructive migration; changing modes does not overwrite limits or clear pauses.
Existing measured batch autotuning and experiment ranking remain in charge of workload tuning.
Hardware benchmarking, thermal/battery adaptation and measured GPU selection remain Phase 2 work.

Balanced yields GPU training to active inference; Training First permits GPU work within all other
inference, traffic, memory, disk, schedule and budget protections. CPU training always yields to active
inference. Ordinary accounts cannot alter these settings; the existing Owner reauthentication applies.

### Changed files

| File | Necessary change |
|---|---|
| `app/src/features/training/EvolutionControls.tsx` | Shared five-control presentation, sending minimal setting patches. |
| `app/src/features/training/NetworkTraining.tsx` | Use the controls with existing authenticated API; retain separate PC contribution. |
| `app/src/features/owner/evolution.tsx` | Replace low-level settings form and remove duplicate automatic-evolution switch. |
| `server/moth_server/evolution/settings.py` | Validate mode/priority, preserve stored limits and compute bounded runtime policy. |
| `server/moth_server/evolution/engine.py` | Feed runtime policy into existing engine. |
| `server/moth_server/evolution/compute.py` | Apply priority while preserving inference/resource protections. |
| `server/tests/test_evolution_controls.py` | Migration/limits/pause, invalid policy, authorization and inference/budget regressions. |
| `app/src/test/evolution-controls.test.tsx` | Ensure five controls submit minimal patches without silently resuming. |
| `app/src/test/intelligence-hub.test.tsx` | Verify the requested mode control replaces the old CPU switch. |
| `docs/INTELLIGENT-EVOLUTION.md` | Record source findings, scope, evidence and outstanding phases. |

Validation: five focused server policy tests and six frontend tests passed; TypeScript checking passed.
The older UI/progress work also passed real browser and CPU training checks documented in `UI-POLISH.md`.

## Remaining phases

2. Measured hardware optimization (existing detection/admission is a starting point).
3. Separate cloud infrastructure authorization and account/device-bound personal consent.
4. Measured reliability/transfer-aware scheduling.
5. Authoritative live Overview, stale/reconnect behavior and synchronized model identity.
6. Continuous adaptive training integration and inference responsiveness verification.
7. Earned public milestones separated from routine deployed revisions and optimizer steps.
8. Recovery and sanitized diagnostics integration.
9. Cross-account consent, credentials, private-data and promotion security verification.
10. Signed updater caching/backoff and real older-version integration verification.
11. Actual Windows/infrastructure integration and hardware-backed performance evidence.
12. Full regression/migration verification and gated signed publication.

No production model reset, checkpoint replacement, manual production deployment or release-gate bypass occurred.

### Phase 2 progress — Windows memory admission

`worker/moth_worker/hardware.py` now reads both total and available physical RAM from
`GlobalMemoryStatusEx`, checks the API return value, and reports unavailable measurements
conservatively. Previously its Windows fallback used total RAM as available RAM.
`server/tests/test_worker_memory.py` verifies a 16 GB machine with only 2 GB available
reports 2 GB available and that scheduling admission respects that limit (passed).
This is an OS-API simulation; native Windows verification and the remaining adaptive
hardware work are still required. Phase 2 is not complete.

### Consent and live-status integration progress

- `backend/moth/community/participant.py`: explicit enable verifies `/v1/me`, binds the saved enrollment to account ID and local machine ID, and requires an in-memory authorized session. Saved settings alone cannot start compute. Account changes stop the prior runner before re-enrollment; checkpointing must finish first.
- `backend/moth/server/app.py`: changing or clearing the session disables local contribution.
- `server/moth_server/routes/training.py`: the Owner cannot resume another account's paused device.
- `server/moth_server/routes/evolution.py`: Owner bulk start excludes another account's paused devices.
- `backend/tests/test_participant_consent.py`: two startup/session authorization regressions passed.
- `server/tests/test_workers_v05.py`: added cross-account Owner resume rejection; nine worker/control tests passed.
- The existing real CPU test `test_moth_code_contributes_its_computer_to_the_same_experiment` passed after the consent changes (30.11 seconds).
- `IntelligenceHub.tsx` and `IntelligenceView.tsx` clear stale data on failed refresh and show explicit unavailable status. Resource failures also clear the cached resource report.
- `app/src/test/intelligence-hub.test.tsx` verifies a successful model display is cleared after a failed refresh; eight focused UI tests and TypeScript checking passed.

These changes close specific gaps; they do not complete the separate cloud-worker classification,
all personal-device lifecycle controls, earned milestone system, hardware optimization or full
public-release verification. Those remain outstanding. No release is authorized to bypass the gates.
