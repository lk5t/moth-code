# Next big update — plan (not built, not published)

Agreed with the Owner. Nothing here is started until the Owner says go.

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

## Not confirmed (ask before building)
Size ladder, memory lookup, tools (calculator/code runner), 👍/👎 on replies, version timeline, old vs new.

## Not included
Daily streak, personalities, chat export, prompt library, voice, day/night theme, milestone celebrations
(unless asked).
