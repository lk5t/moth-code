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
