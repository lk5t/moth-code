# Intelligent Evolution verification

Branch: `claude/jolly-darwin-2qeihd`. This report distinguishes implementation from hardware and release verification. Foundation training is not complete or claimed.

| Phase | Implementation and verification |
|---|---|
| 1 Settings | Shared five Owner controls; backend validation, modes, priority and separate personal opt-in. Cloud toggle now applies to explicitly Owner-enrolled infrastructure. |
| 2 Hardware | Available Windows RAM, bounded cached CPU/GPU throughput selection on workers, existing adaptive batch sizing and inference admission; optional Linux thermal/battery and Windows battery signals pause work under measured pressure. Physical GPU/Windows sensor behavior still requires hardware verification. |
| 3 Network | Verified account/device consent, separate cloud registration, local pause/stop/revoke, account-scoped checkpoint directories, immutable server-assigned worker kind, claim-time revocation check. |
| 4 Reliability | Existing leases, stale-result rejection, verified contributions and heterogeneous shards retained. New measured worker compute profiles are cached. Transfer-aware scheduling and representative multi-machine performance certification remain incomplete. |
| 5 Intelligence | Five sections, deployed model identity, revision/tokenizer fields, explicit unavailable state, measured loss history and rate-based ETA. Existing evaluation timeline retained. Complete deployment-event visualization remains outstanding. |
| 6 Data/training | TXT streaming, JSONL text/prompt-answer/messages including tool results, actionable record errors, duplicate exclusion before splitting, tokenizer-bound API imports and real CPU optimizer tests. HF dependency included in desktop/server packaging; gated/download errors categorized without access bypass. Production all-v1 traceback remains unavailable. |
| 7 Versions | Routine promotions inherit public version; deployment assigns internal revision. Public milestones require two independent practical capability gains and two fresh repeated evaluations with compute/retention guards. Positive milestone orchestration is unit tested; no trained-model milestone is claimed. |
| 8 Recovery | Existing atomic checkpoint/integrity/resume/rollback paths preserved. Live engine swap now occurs after deployment DB commit. Failure-injection regression checks old engine remains usable. |
| 9 Privacy | User datasets excluded from worker scheduling and downloads, including previously queued experiments. Feedback-containing evaluation libraries stay local. Owner cannot resume another account's personal device or enlarge its limits. Registration diagnostics redact recognized credentials. |
| 10 Updates | Existing signed updater and rollout workflow preserved. No updater code changed in this continuation. Earlier installed Desktop upgrade was confirmed by user; this candidate release is not yet published. |
| 11 Testing | CPU training/imports, permission boundaries, milestone guards and UI regression tests run locally. Full first server run: 169 passed, 6 failed; three obsolete version expectations corrected, worker fixture learning rate corrected after deduplication, crash/resume timeout under investigation/retest. Windows and physical GPU verification pending. |
| 12 Release | Integration remains gated by full regression and signed Windows release workflows. Do not treat this report as public-release certification. |

## Changes in this continuation

- `backend/moth/training/{sources,data}.py`: fix the reported import/token-production failures, preserve existing conversation/tool formats, deduplicate before split.
- `backend/pyproject.toml`, `backend/packaging/moth-backend.spec`, `server/pyproject.toml`: include the actual HF loader dependency and its dynamically imported packaged modules.
- `server/moth_server/evolution/datasets.py`: unique registration directories preserve earlier dataset copies.
- `server/moth_server/intelligence/library.py`: retain per-domain registration failures and sanitize persisted errors.
- `backend/moth/community/participant.py`, `backend/moth/server/routes_hybrid.py`: explicit account-authorized device controls and checkpoint isolation.
- `backend/moth/training/resources.py`, `worker/moth_worker/runner.py`, `server/moth_server/evolution/compute.py`: measured supported pressure safeguards, scheduling separation.
- `server/moth_server/{training.py,routes/training.py}`, `evolution/{settings,distributed,remote_eval,backends}.py`: cloud/personal authorization, revocation race check and private-source protection.
- `server/moth_server/evolution/{milestones,v2}.py`, `models.py`: earned public identities, internal revisions and post-commit live model swap.
- `server/moth_server/routes/intelligence.py`, `app/src/features/intelligence/{IntelligenceHub,TrainingProgress}.tsx`: authoritative identity fields and measured loss/ETA display.
- `app/src/features/network/NetworkView.tsx`, `app/src/features/training/{EvolutionControls,NetworkTraining}.tsx`: cloud enrollment and device controls.
- Tests changed only for these requirements, real import/training regressions, privacy/permission checks and revised public-version semantics. Distributed test fixtures use a smaller learning rate because deduplication reduces the tiny corpus; production acceptance gates are unchanged.

No model weights, existing checkpoints, accounts or production data were reset. No production deployment or signing bypass was performed.
