# 1.0.0 plan — built and shipped as one release (see CHANGELOG 1.0.0 for what was delivered)

Agreed with the Owner. Build order (each part tested before the next): training → assistant → agent → app alive →
network & accounts. Published together as one release.

## Safety and trust (agreed)
- **Honest answers** — if a MOTH reply looks broken (gibberish, loops, empty), the app says so and offers to retry.
- **Two-factor sign-in** — authenticator-app codes (TOTP) for accounts, recommended for the Owner.
- **Visible backups** — MOTH Cloud's backups listed with a "restore" action for models and settings.

## App
- **Home screen** — recent projects and chats, MOTH's status and today's progress.
- **Offline mode, paid plans only** — a downloaded MOTH that works without internet; free plans stay online.
- **"Fix this"** — select an error (terminal or editor) and MOTH explains and fixes it.
- **Connections, GitHub first** — sign in through the browser; clone, branch, commit, push and open pull
  requests with the user's approval; per-connection permissions. Others (e.g. GitLab, Google Drive) later.
- **Agent mode** — give MOTH a task; it plans, writes, runs and fixes the code while the user watches.
- **Live preview** — the website being built updates as MOTH edits it.
- **Explain this code** — hover a function for a plain-English explanation.
- **Auto tests** — MOTH writes and runs tests for the user's code.
- **Shared projects** — invite someone to the same project; both work with MOTH together.
- **Usage page** — tokens used and left on the plan, with a chart.

## MOTH as a smarter assistant (agreed)
- **MOTH remembers you** — notes on your projects, preferences and past fixes, used in every chat; viewable and deletable.
- **Project brain** — reads the whole project once and understands how files connect.
- **Undo anything** — every change MOTH makes is a checkpoint; one click rolls it back.
- **Plan first** — big tasks start with a step-by-step plan the user approves or edits.
- **Background tasks** — long jobs run while the user keeps chatting; notification when done.
- **Self-check** — MOTH runs the code it wrote and fixes its own mistakes before answering.
- **Error watcher** — notices crashes in the running app and offers a fix.
- **Learns from your fixes** — user corrections to MOTH's code become (consented) training data.
- **Compute marketplace** — people rent out their computer's time to train MOTH and earn credits automatically
  (builds on referrals and worker rewards; credits only, never cash).

## The app feels alive
- **Living moth** — reacts: flutters while thinking, sleeps when idle, cheers on improvements, worried on errors.
- **Ambient background** — a soft glow that follows what MOTH is doing (calm when idle, pulses while training).
- **Typing feel** — smooth streaming cursor, code blocks unfold, links glow.
- **Micro-sounds (optional, off by default)** — soft clicks, a chime when a task finishes, a flourish on promotions.
- **Live counters** — tokens learned today, workers online, ticking in place.
- **Activity feed** — a live strip: "your worker trained 2M tokens", "MOTH fixed a bug".
- **Greetings** — "Good evening — MOTH learned 40M tokens while you were away."
- **Hover life** — cards tilt slightly, buttons glow, icons animate.
- **Smooth page changes** — pages slide and fade.
- **Empty screens with personality** — a moth animation and a friendly tip instead of "nothing here".
- All motion respects "reduce motion".

## Training (agreed)
- **Smart data cleaning** — MOTH scores every training text for quality and drops the junk automatically.
- **Longer memory in chats + compaction** — train on long conversations; when a chat grows past the context,
  MOTH summarises the earlier part itself and keeps going (like Claude Code's compaction), so long chats never
  "forget" or break.
- **Never forget** — replay a slice of older data in every run so new skills don't erase old ones.

## AI (agreed)
- **GPU support for workers** — any worker with a graphics card is detected and trains 10–50× faster.
- 2–3× faster training (sequence packing, faster CPU maths, fused optimizer) — part of "Training" above.

## Much faster updates (agreed)
Today: desktop checks hourly, staged rollout 10 % → 50 % → 100 % with 6 h between stages, server agent
checks every 15 min. Make it much quicker, keeping signatures, health checks and automatic rollback:
- MOTH Cloud tells signed-in apps about a new version right away (through the alerts feed); no waiting for the hourly check.
- Shorter rollout stages (e.g. minutes, not 6 hours) that advance as soon as early installs report healthy.
- Server agent checks far more often; workers update immediately (already) .
- Quiet install: download in the background and swap in when the app is idle, no restart prompt.

## Rule: improve what exists, never duplicate
Before building each item, check what is already there and replace or extend it instead of adding a second
version. Already present today (to be upgraded, not rebuilt):
- **Agent mode / Plan first** → `backend/moth/agent/engine.py` already plans, uses tools and asks for approval;
  upgrade it (editable plans, background runs, self-check, better UI) instead of a new agent.
- **MOTH remembers you** → `agent/memory.py` (per-project memory, FTS) + `MemoryPanel.tsx`; extend to
  per-user memory and show it everywhere.
- **Project brain** → `agent/project_intelligence.py` + `agent/retrieval.py` + `ProjectIntelligencePanel.tsx`;
  deepen (dependency map, file relationships) instead of a new indexer.
- **Undo anything** → `ChangesPanel.tsx` (agent changes) ; turn into full checkpoints with one-click restore.
- **Learns from your fixes / 👍👎** → the 0.5.1 feedback engine (`intelligence/feedback.py`); extend it.
- **GPU workers** → workers already train on NVIDIA CUDA; add automatic GPU setup, AMD/Intel, routing.
- **Never forget** → replay already exists (`v2._replay_source`); make it stronger and measured.
- **Smart data cleaning** → `datafactory/clean.py` quality filters; add learned quality scoring.
- **Usage page** → `UsageSection.tsx`; upgrade with charts.
- **Compute marketplace** → referral/worker rewards; extend to self-contributors.
- **Home screen / activity feed / living moth** → `ActivityPanel`, `CloudActivity`, `MothEmblem` motion states.

## Not confirmed (ask before building)
Size ladder, memory lookup, tools (calculator/code runner), 👍/👎 on replies, version timeline, old vs new.

## Not included
Daily streak, personalities, chat export, prompt library, voice, day/night theme, milestone celebrations
(unless asked).
