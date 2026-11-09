# MOTH Code 0.6.0 — LIVING INTELLIGENCE

## Phase 1: source-based usability inventory

Baseline: c61d52b on claude/jolly-darwin-2qeihd; signed0.5.9 release verified previously. Preserve the current engine, inference/router, workspace permissions, dataset pipeline, updater and branding.

| Existing feature/source | Current problem | Primary home |
|---|---|---|
| NavRail / WorkspaceShell | Icon-only combined Code/Chat entry hides two everyday workflows | Separate labelled Chat and Code entries sharing the existing mounted workspace |
| IntelligenceHub / IntelligenceView | Overview, metrics/history and training on one nested hub; Data/Network hidden behind it | Overview for deployed status; Intelligence for Training/Evolution; Data and Network as direct workspaces |
| NetworkTraining / TrainingView / Owner evolution | Local TrainingView embeds NetworkTraining although hub already shows it | One default training panel; focused advanced local experiment tools |
| TrainingView / Owner IntelligencePanel / Owner evolution datasets | Tokenizers, local data, licensed cloud library and approved datasets are scattered | Data with local preparation/quality and cloud library sections |
| NetworkView / Owner WorkersPanel / ParticipantSwitch | Enrollment, personal consent and worker administration are split | Network default personal consent/worker list; administration/diagnostics in Advanced |
| IntelligenceView / Owner evolution events / Workspace ActivityPanel | History is scattered across model timeline, cloud events and local jobs | Activity with one filtered history; project execution remains visible in Code |
| OwnerDashboard | Platform administration shares navigation with ordinary AI workflows | Settings → Administration, owner-only; preserve legacy owner route |
| SettingsView | Existing grouped tabs reset selection on remount | Persist selected settings section; keep advanced permissions and destructive controls distinct |
| Welcome | Optional/skippable introduction exists but cannot be reopened; model/tools guidance incomplete | Reopenable brief guide from Settings and feature search |
| ChatPanel / WorkspaceView | Existing streaming, history, editor, terminal and approvals work | Reuse; add search/regeneration and project context without duplicate tools |
| backend workspace/files/scanner, agent memory | Authorized filesystem primitives exist; no unified incremental project graph | Project Intelligence inside Code, using those permission/scanner primitives |
| datafactory / training sources/data | Real parsing, licensing, masks, deduplication and tokenizer identity exist; no unified inspection/preview workflow | Dataset Quality Studio inside Data |
| evolution/genesis.py / GenesisPanel | Existing reversible fresh-lineage reset deliberately retains old models/backups | Keep legacy recovery accessible; add explicit full native-AI deletion preview/confirmation under destructive operations |
| MothEmblem | Existing reduced-motion wing animation has only idle/working | Extend shared emblem states from real activity, pause hidden decoration, no invented neural metrics |

Navigation target: Overview, Chat, Code, Intelligence, Data, Network, Activity, Settings. Keyboard-accessible feature search links to the same authoritative screens. Preserve legacy view/tab identifiers through adapters. Do not multiply backends or create duplicate forms.

## Safety boundaries for the new update

- Build/test all new destructive-reset behavior only in isolated deployments.
- Production reset and0.6.0 publication/deployment require separate explicit Owner authorization under the new brief; do not execute them during implementation.
- Full reset previews owned AI storage/DB categories and retained backups. Never traverse user-provided paths or remove accounts, projects, chat, billing, consent, binaries or platform security configuration.
- Existing reversible GENESIS is not evidence of complete deletion. New reset must invalidate outstanding jobs, block automatic reinitialization, verify cleanup and disclose retained/offline copies.

## Implementation record

Phase1 completed: inspected navigation/view state, workspace, onboarding/settings, training/data/network/Owner panels, existing reset and backend storage/table structure. Existing regression tests validate the baseline navigation contracts before adapters change. Subsequent phases must update this record with actual tests and limitations.
