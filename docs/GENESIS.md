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
| 3 CPU/GPU coordination | Defaults and selection fixes tested; fresh-lineage CPU evidence pending |
| 4 Evolution/growth | Existing real trainer, research planning, growth and promotion/rollback retained; GENESIS lineage reset integration pending |
| 5 Code/Chat workspace | Implemented compact switch, retained mounted workspaces, drafts/files, separate general history and consent-gated project excerpts; focused UI and real local API regressions passed |
| 6 Intelligence control center | Five tabs consolidate existing controls; actual architecture and reported-step activity, selectable layers and timeline; focused UI regressions passed; native Windows verification pending |
| 7 UI consistency | Sidebar consolidation, persistent navigation/layout, keyboard shortcuts, collapsible advanced panels, smaller minimum window and reduced-motion support implemented; native layout verification pending |
| 8 Integration fixes | Worker-body fix tested; signed updater repair in Windows release verification |
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
published 0.5.1-to-0.5.4 test remains unresolved; Desktop 0.5.5 is not yet confirmed published.

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
