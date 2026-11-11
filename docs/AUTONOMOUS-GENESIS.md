# MOTH 0.6.2 — Autonomous Genesis

Open MOTH Code, go to **AI**, press **Start Evolution**, and follow what MOTH does. Nothing below
requires choosing parameter counts, steps or learning rates; those stay in AI Settings → Advanced.

## Five sections

Chat · Projects · AI · Network · Settings. Older places map onto them (Overview → AI → Evolution,
Data → AI → Data, Activity → AI → History, Training/Models → AI → Evolution/AI Settings). Saved
navigation from 0.6.1 opens the matching section.

## Chats

Rename, delete one, select several and delete them, or clear all (type `DELETE ALL`). Deleting the
open chat clears it; deletion is refused while MOTH is still answering in that chat; partial failures
are reported. Messages are deleted with their conversation. Chats are stored on this computer only —
there is no cross-device chat sync, so there is nothing to synchronise. Optional retention
(Settings → Privacy & AI: 30/90/365 days, measured from the latest message) is off by default.

## Start Evolution (Owner)

One re-authenticated action, each step an existing, tested operation:

1. No model yet → creates the 99,648-parameter seed (byte tokenizer, or the prepared library's
   tokenizer when one exists). It starts untrained; it is not presented as capable.
2. Selects trusted, licensed catalogue sources, coding first, that fit the download budget and free
   disk (`autopilot.PRIORITY`), prepares them (deduplication, decontamination, credential removal).
3. Turns on continuous evolution. Pause stops at the next checkpoint.

Starting again never creates a second model.

## The Evolution Engine's plan (`server/moth_server/evolution/autopilot.py`)

A conventional, measurable controller — the early model is not asked to make decisions. From recorded
experiments and current measurements it:

| Evidence | Decision |
| --- | --- |
| last two runs each improved held-out results ≥ 2 × the gate and did not stop early | train 1.5× longer |
| last two runs improved less than the gate (or stopped early) | halve the learning rate, return to the base steps |
| a run stopped improving at step N | plan ~1.2 × N steps |
| out-of-memory failure, or little free memory now | halve the batch size |
| measured seconds per step would exceed the cycle budget | fewer steps |
| no accepted improvement for 3+ cycles | wait longer between cycles (up to 16×) instead of looping |

Every decision is recorded with its numbers (`plan.adjusted` events) and shown under *Why MOTH changed
its plan*. Architecture growth stays evidence-gated (0.6.1) and every candidate must beat the deployed
model on held-out data and pass every gate; promotion is staged and monitored with rollback.

## Live training and activity

AI → Evolution shows live measurements only: CPU, memory, GPU memory, workers online; the active job's
step/planned steps, tokens, tokens/s, training and validation loss, elapsed time, remaining time (the
trainer's estimate or the measured step rate; otherwise **Estimating**), checkpoint, data mixture and
plan; the held-out evaluation result and the planner's reason. The live activity stream lists the
engine's own events — data prepared/failed, training started/finished, checkpoints, workers
connected/disconnected, plan adjusted, candidate rejected, model promoted, paused/recovered — with
timestamps and expandable details.

## Data and safety

Credentials are removed from all training data (data factory and local preparation) with the same
patterns used for anything leaving the machine; Dataset Quality Studio reports affected examples.
There is no separate safety *training* dataset in MOTH; the safety controls — the content policy, the
safety-baseline refusal flag and the held-out safety evaluation suite — are separate from training
data and are never changed by Evolution (asserted in tests).

## Storage (AI → AI Settings)

Lists model versions, prepared data, download caches and run folders with the reason each item is
kept. Cleanup re-checks every item at deletion time and never removes the deployed model, versions
serving users or available for rollback, data in use, or active work; deleted models keep their record.

## Upgrade from 0.6.1

No database schema change. Accounts, chats, projects, models, datasets, worker enrolments, training
history and settings are kept. New settings (`autopilot`, `chat_retention_days`) have safe defaults.
An upgrade never starts Genesis Reset or creates a model. The desktop release workflow now verifies
the published 0.6.1 installer updating itself to the 0.6.2 candidate on Windows.

## Verified here

Temporary deployment, real CPU training: reset to zero → Start Evolution → seed created, eight sources
downloaded and prepared in ~30 s → cycle trained (200 steps, ~57k tokens/s) → candidate improved
held-out loss by 28.24 %, passed every gate, promoted to a 20 % staged rollout; every step appeared in
the activity stream. No GPU or multi-machine hardware was available: worker assignment and recovery
are covered by the existing automated tests (lease requeue, resume from checkpoint, corrupted
checkpoint fallback, crash and resource-shortage resume), not by physical hardware here.
