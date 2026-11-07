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
