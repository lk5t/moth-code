# Changelog

Earlier entries describe historical development/release claims. The current verified status, including
the unverified completion of Foundation training, is recorded in [docs/CONTINUATION.md](docs/CONTINUATION.md).

## 1.0.10 — Says why a run is not shared

- When a run on MOTH Cloud alone is not moved to shared training, Live activity now says exactly why (no other computer online, not enough free memory on the others — naming them, private data in the mix, or almost finished) instead of staying silent.
- A run can be handed over to shared training until 90 % done (was 80 %).

## 1.0.9 — Everyone really trains together; worker actions

- MOTH Cloud always takes part in shared training. An earlier version made a revoke of MOTH Cloud's own worker permanent, which silently left the server out of every shared run ("Shared runs with workers: revoked"); it now enrolls again by itself.
- No switches for it: one experiment at a time is trained by every online computer, sharing its steps. Every online computer joins (GPUs and CPUs alike); each gets a share of steps that matches its measured speed.
- Network → a worker → Actions: Restart, Update now, Run self-check, Show recent logs, Clear cache. The worker picks the action up at its next heartbeat and the result is shown. These are fixed actions, never shell commands, because a worker may be someone else's computer.

## 1.0.8 — Training data keeps its tokenizer

- Fixed "FileNotFoundError: …/models/v00134/tokenizer.json": prepared training data pointed at the tokenizer inside the model folder it was made with, and model retention removed that folder after a newer model was promoted. Prepared data now keeps its own copy of the tokenizer; data prepared earlier recovers it from the base model when it is the same tokenizer (checked by fingerprint).

## 1.0.7 — Bigger models stop getting declined for the wrong reasons

- A successor with its own (BPE) tokenizer failed the release check "not worse than the deployed model" because that check compared loss per token, and a BPE token carries several bytes, so its loss is naturally higher. Models with different tokenizers now skip that per-token check; the promotion gates already compare them fairly, per byte of the same text.
- A declined successor is no longer thrown away: the next attempt of the same size continues from its trained weights (on MOTH Cloud and in shared rounds) instead of starting over from random weights, so each attempt adds to the last.

## 1.0.6 — All computers train one experiment together

- With two or more computers online, MOTH Cloud, every worker and every contributing PC train the same experiment in shared rounds, one experiment at a time, instead of each computer training a different one.
- The participants share the steps (each trains about its share, faster computers more) and are averaged at least every 1,000 local steps, so more computers finish a run sooner instead of each repeating the whole run.
- A run waiting after a handover to shared rounds starts first. `distributed.one_experiment: false` restores the side-by-side mode.

## 1.0.5 — Faster training

- Short context first: long-context runs (the 1,024-token successor) train their first 70 % on 256-token rows cut from the same batches (same tokens, same schedule), then the rest at full length. Attention over 256 instead of 1,024 tokens makes those steps much cheaper; shared rounds and workers do the same.
- Fuller steps: a successor now trains at least 8,192 tokens per step (it was 2,048: two 1,024-token rows left the CPU mostly idle). The token budget is unchanged.
- One training thread per physical CPU core (hyper-threads slowed training down).
- A successor that is resumed (e.g. handed over to shared training) continues from its checkpoint instead of from fresh weights.

## 1.0.4 — Windows installer finds NVIDIA GPUs

- The Windows worker install missed every NVIDIA GPU (e.g. an RTX 3050) and installed CPU-only PyTorch: PowerShell's `-match` on nvidia-smi's list of lines never records the CUDA version. It now joins the lines, also looks in NVIDIA's install folders and Windows' list of graphics cards, and replaces a CPU-only PyTorch from an earlier install with the GPU build.

## 1.0.3 — Everyone trains together; chat data matches real chats

- A run that started on MOTH Cloud alone (nobody else online) moves to shared rounds with MOTH Cloud and the workers as soon as other computers come online, continuing from its latest checkpoint instead of training alone for hours.
- CPU computers (MOTH Cloud included) now join GPU training rounds when they are at least a quarter as fast as the typical GPU; each gets a share of steps that matches its speed.
- Conversation training data now starts with MOTH's system prompt in half of the conversations, like every real chat does. Before, the model never saw that prompt in training.

## 1.0.2 — Windows worker install fix

- Desktop: Network now says clearly that MOTH Code already includes training for this computer (off until you turn on "Contribute this computer"); the install command is only for extra machines without the app.
- The one-command Windows worker install stopped at "import torch" on a fresh PC in Windows PowerShell 5.1 (the default shell): 5.1 turns any program's stderr into a fatal error under the command's "Stop" setting. The installer now checks exit codes instead, probes for PyTorch without printing a traceback, and is plain ASCII (the "▲" showed as "â–²"). CI now runs the install in Windows PowerShell 5.1, exactly as users do.

## 1.0.1 — Server fix: bigger successor could not start training

- Fixed "RuntimeError: no microbatch fits" on MOTH Cloud. The memory check counted only completely free RAM and ignored the file cache (which fills up with downloaded datasets and is freed on demand), so an almost idle server looked full and the 7.2M successor was refused even at batch 1. It now reads the RAM the system can actually hand out, and the smallest batch is always tried for real instead of being skipped on an estimate.

## 1.0.0 — The biggest update: smarter assistant, agent, live app, connections

**Training**
- About 1.5× faster training steps: long runs use compiled training (with a safe fallback), and the optimizer updates all weights at once.
- Learned data quality: each data preparation learns what good text looks like from the curated sources (textbooks, stories, Wikipedia, hand-written conversations) and drops the weakest 15 % of web text.
- Never forget: older data now makes up to 10 % of every training mix (it was a fixed small slice), so new skills don't erase old ones.
- Every run now ends on mostly conversation (the last 15 %), and successors also start with a chat warm-up, targeting the checks that rejected v124 and v125.
- Long chats are compacted: older messages are summarised instead of cut off mid-message, and MOTH says when that happened.
- AMD graphics cards on Linux (ROCm) join NVIDIA as automatic GPU workers.

**Assistant**
- MOTH remembers you: say "remember that …", "my name is …" or "I prefer …" and it keeps it in mind in every chat (Settings → Memory shows and deletes it).
- Project brain: answers about your project also see which files use the ones found, and which they use.
- Plan first: tick "Show me the plan first", edit MOTH's plan, then approve it before anything changes.
- Self-check: before finishing, MOTH checks that every file it changed still parses, and fixes it if not.
- Undo anything: Changes lists MOTH's changes; go back to before any of them in one click (later changes are undone too).
- Fix this: select an error in the terminal (or use the last output) and MOTH finds the cause and fixes it.
- Error watcher: when a command prints an error, MOTH offers to fix it.
- Learns from your fixes: an undone change is remembered so the next task avoids it; 👍/👎 with corrections still feed training (with consent).
- Honest answers: a reply that looks garbled is labelled as such, with "Try again".

**Agent**
- Live preview: when a command starts a local web server, its page opens in a preview that reloads as files change.
- Background tasks: tasks keep running while you chat; a notification arrives when one finishes or its plan is ready.
- Write & run tests in one click.

**The app feels alive**
- New Home screen: a greeting, what MOTH is doing, today's numbers, the learning stage, recent projects and chats, and live activity.
- The moth has moods: it sleeps when nothing happens, cheers after a promotion and looks worried on errors.
- A soft ambient glow that follows what MOTH is doing; code blocks unfold; links glow; cards lift and tilt; pages slide in; empty screens get a moth and a tip.
- Live counters in the status bar (tokens learned, workers online); optional sounds (off by default).

**Network and accounts**
- GitHub connection (Settings → Account → Connections): clone your repositories from Home, and pull, push, open pull requests and invite friends to a shared project from Changes. The token stays in your computer's credential vault and never ends up in git config or logs.
- Two-factor sign-in with any authenticator app.
- Usage page: tokens used per day for the last 30 days.
- Compute marketplace: your own computers now earn credits too (5 per 1,000 trained tokens, within the monthly limit), alongside referral rewards.
- Offline mode (MOTH on your own computer) is part of the Pro and Max plans.
- Faster updates: the app checks every 10 minutes, rollout stages last 30 minutes instead of 6 hours, and MOTH Cloud's update agent checks every 5 minutes. Signatures, health checks and automatic rollback are unchanged.
- Backups: the Owner Dashboard lists MOTH Cloud's verified backups and has "Back up now".

Not included, honestly: AMD/Intel graphics cards on Windows (training there is not reliable enough yet), and live co-editing of the same files at the same moment (shared projects work through GitHub instead).

## 0.10.1 — Successors learn to chat first

- The first right-sized successor (2.9M parameters) was rejected: besides the old speed rule (fixed in 0.10.0), its replies did not end cleanly as often as the current model's. A successor now trains in three phases: a chat warm-up (the first 8 % of its steps on conversations only: who speaks, when a reply ends), the whole curriculum, and a chat-heavy finish (the last 15 %: 70 % conversations). Shared rounds use the same mix on average. It is still promoted only if it passes every check; until then the current model keeps answering.

## 0.10.0 — Bigger, fairer successors, cleaner replies, and a training view you can watch

- **A bigger model is no longer rejected for being bigger.** The speed and memory gates compared a candidate with the model it replaces ("at most 25 % slower"), so any successor or grown model many times larger failed them, however much better it was. Bigger candidates are now held to absolute limits instead: at least 15 tokens/s when chatting, and at most half of the server's memory.
- **Successor sizes come from measured speed.** Before choosing a size, MOTH trains each candidate shape for a few steps on MOTH Cloud and times it, together with the current model's shape, whose real training speed is known; the ratio corrects for whatever else the server is doing (the old "6 × parameters" rule underestimated small models about 3.5×). Workers add speed in proportion. No measurement runs while a successor trains.
- **Successors read 4× more at once:** a 1024-token context (same tokens per step, smaller batch).
- **A new tokenizer for the successor.** A byte-level model reads one letter per token. Its successor now trains on data prepared again with a new 8,192-token BPE tokenizer (about four times fewer tokens per text). Models with different tokenizers are compared fairly: held-out losses in bits per byte of the same text (benchmarks scored before this release are measured again once). If that preparation fails, the successor keeps the byte tokenizer.
- **MOTH Cloud and the workers train a successor together.** A successor goes first in its cycle and is split across MOTH Cloud and every online worker in shared rounds (averaged every 1,000 steps from the same seeded start); the cycle's smaller experiments use what it leaves free. It is never handed to one worker alone. Your choice of what trains MOTH is respected.
- **Cleaner chat replies now:** unlikely tokens are dropped, words used again and again are discouraged, the same phrase is never repeated within a reply, a reply that starts looping is ended, and near the length limit a reply ends at the next sentence end instead of mid-word. Tool calls are left exactly as generated; benchmarks are unchanged.
- **Morning report:** after six hours or more away, AI → Evolution opens with what MOTH did (experiments, tokens read, promotions, self-quiz scores, repairs, problems) and its answer to the same question then and now.
- **Desktop alerts and tray:** a Windows notification when MOTH is promoted or needs a look, and a confetti burst in the app for a promotion. Closing the window keeps MOTH Code running next to the clock (tooltip: what MOTH is doing); quit from the tray icon. Both can be turned off in Settings → Updates & about.
- **Live training you can watch:** a smooth glowing loss curve (best point marked, readout on hover), MOTH's network drawn live with signals flowing as fast as it trains, a learning stage (babbling → letters → words → phrases → sentences → chat) from the measured loss, and what MOTH writes right now — its own answer to the same question at each evaluation, typed out live. Shared successor runs show their rounds too.
- **Owner Dashboard:** a "MOTH right now" header (model, parameters, live status and progress ring), animated tiles and a disk gauge.
- **Referral rewards, re-tuned to the plans:** 5 credits per 1,000 trained tokens (≈ 90k per busy CPU hour, about 10× that for a GPU), at most 50,000 per job and 3 million a month per referrer (60 % of Pro), 30 million in total; rewards are credited after 7 days instead of 14. New: the invited person gets a 100,000-credit welcome bonus once their computer has done its first verified work. Rules the Owner set explicitly are kept.

## 0.9.2 — MOTH outgrows the seed

- **Why MOTH could not write sentences:** One-click Start (and every Genesis Reset) begins with the "Seed" model — 99,648 parameters, 64 wide and 2 layers deep, described in the code itself as "learns very little; useful to verify the pipeline". Growth could only add layers or FFN width (never width of the model itself) by at most 50 % per step, behind several waiting gates, so after a night of training MOTH was still the same size. No amount of training makes a 100k-parameter model fluent; models that write simple coherent English start at a few million parameters.
- **Right-sized successor (new):** each cycle MOTH computes the size its *measured* compute (MOTH Cloud plus workers) can train properly in about a day (≈ 20 training tokens per parameter). When the model is at least 4× smaller than that, MOTH trains a successor of that size from scratch on MOTH Cloud — wider and deeper, same tokenizer and curriculum — and promotes it only if it passes every gate against the current model (held-out loss, release check, retention, benchmarks). A rejected successor is retried once with twice the training; the Owner's parameter ceiling is respected and `growth.rebirth: false` turns it off. On a server like yours (≈ 50,000 tokens/s on the seed) that is a model of about 4–5 million parameters.

## 0.9.1 — Faster and smoother

No new features: the same MOTH, measured faster and with a motion pass.

- **App starts with ~90 % less code.** The code editor and terminal (several MB) load only when a project is opened, Settings and the Owner dashboard load on first use, and React, UI, icon and Tauri libraries sit in separate long-cached chunks. The startup bundle went from 5.1 MB (1.33 MB compressed) to about 0.6 MB (≈ 180 kB compressed).
- **Data preparation 2.65× faster** (a 21,000-record build: 20.7 s → 7.8 s): near-duplicate and benchmark-overlap detection hash each distinct word once and combine word hashes with vectorised arithmetic; overlap checks search a sorted array in bulk; credential scrubbing skips patterns whose required text is absent (identical output); a record's words are split once instead of four times. It matters most for 0.9.0's much larger datasets.
- **Motion:** views glide in, lists and cards enter one after another, live progress bars carry a light sweep, step and token counters count up and glow when they change, working machines pulse, dialogs pop, chat messages slide in, loading placeholders shimmer, buttons press in. Everything respects the system's "reduce motion" setting.

## 0.9.0 — Autonomous MOTH: bigger data, self-repair, self-training

- **Much bigger training data, added by MOTH itself.** 13 large, openly licensed sources (about 90 GB, every file pinned by revision, size and SHA-256): Cosmopedia (stories, textbooks, maths, web-seeded articles), FineWeb-Edu, SmolTalk (conversations, constraints, rewriting, summaries, code), OpenCoder code instructions, MetaMathQA, OpenAssistant oasst2 and the full TinyStories set. Sharded sources are downloaded one file at a time, only as far as the current budget needs, and a build stops reading a source once it has enough. Whenever MOTH has trained on its data three times over, the library doubles each source's budget (now up to 2 billion characters per source) and adds the next large source, conversation and code first. Downloads may use half of the free disk; a budget the disk cannot hold is halved until it fits. MOTH's own verified generators produce up to 100 times more examples as the library grows. The Owner can turn automatic sources off (`autonomous_sources`); a revoked source is never added back.
- **MOTH teaches itself.** Every hour the serving model answers about 160 fresh problems from MOTH's verified generators. Every answer is checked automatically: correct answers are kept as self-verified examples, mistakes are kept with the checked answer as corrections, and both join the next data preparation. The pass rates are MOTH's measured weaknesses on new problems and steer the curriculum where no benchmark exists yet.
- **Self-repair.** A supervisor checks MOTH Cloud every minute and fixes what it knows: a stopped Evolution loop or model pipeline, no serving model, MOTH Cloud's built-in worker failing, a nearly full disk (removing only removable files), a cycle stuck for hours, a data preparation without progress. Each repair is recorded; a problem that comes back three times in an hour is reported as needing attention.
- **Diagnostics page** (Settings → Advanced): loops, serving, the built-in worker, disk, recent self-repairs and recent server warnings and errors (credentials redacted), with "Check now" and "Copy report".
- **Taken-back work is no longer lost.** Workers send a verified progress snapshot every 10 minutes and whenever they pause. When a job is taken back, the experiment continues from that snapshot for the remaining steps on whichever compute takes it next, instead of restarting from step 0.
- **You can see what a worker is doing.** Workers report their phase (downloading the model or data, loading, measuring the batch size, training, uploading), and the live view now shows a worker's real step, tokens and loss (it showed "Not reported" before). A take-back says where the worker was stuck.
- **Honest status.** MOTH Cloud's health says whether it is loading its model or training its first one, and the app shows that instead of "unreachable"; a single slow health answer is retried before the app reports MOTH Cloud as unreachable.

## 0.8.3 — Training runs finish, and MOTH Cloud and workers train together

- Runs finish: early stopping no longer ends a run just because held-out loss stopped improving for a few evaluations (that cut most runs at around a tenth of their steps). A run now stops early only when held-out loss clearly rises (overfitting); stopping on a plateau is an opt-in setting (`early_stopping.plateau`).
- MOTH Cloud's built-in worker no longer pauses in the middle of a job when MOTH Cloud starts a local experiment, which made the job stall, get taken back and restart from zero. It finishes the job and only then waits.
- MOTH Cloud and the workers train the same experiment: shared training rounds now carry the conversation data's loss mask (checked by SHA-256 like the shard), so mixtures with conversation data no longer have to be split into separate experiments. Private training data still never leaves MOTH Cloud.
- MOTH Cloud's built-in worker enrolls again when its registration was lost some other way than an Owner revoke, instead of staying out of shared training for good. Only a revoke in Network stops it. The computing network shows whether MOTH Cloud joins shared runs, and why if not.
- A worker whose computer is already busy with other programs no longer wins placement on its benchmark alone: placement counts only the CPU it has to spare (and halves it when memory is nearly full) until a real job measures it. While MOTH Cloud has nothing to train, a worker that has not made its first training step after 3 minutes (instead of 10) gives the experiment back, so MOTH Cloud trains it instead of sitting idle.
- MOTH Cloud always serves a model when it can: after a restart, or when the deployed model cannot be loaded, it loads the deployed version again or falls back to the rollback model of the same model line, and keeps retrying. It never brings back a model from before a Genesis Reset or from another model line.

## 0.8.2 — Stalled workers lose their job within minutes

- A worker that holds an experiment but makes no training progress (for example while paused because its computer is busy) kept it — and the whole Evolution cycle — waiting indefinitely. MOTH Cloud now takes the job back after 2 minutes without progress once training has started (10 minutes to start: downloading the model and data), tells the worker to stop, records its real pace so placement prefers faster compute, and places the experiment again.

## 0.8.1 — Evolution never runs dry

- Evolution no longer stalls once every planned configuration was tried on the current model: it explores new learning rates around the best known one, longer runs, the other curriculum and fresh data samples (never repeating a configuration), and asks the data library to grow. Every candidate still passes the same gates.
- A cycle that genuinely cannot plan anything (for example while data is prepared) checks again after 5 minutes instead of looping.
- Elapsed time is measured by MOTH Cloud from when the compute actually took the work (a worker job can wait in the queue first), never from the viewer's clock — fixing hours-long "Elapsed" values for experiments that had run for minutes.
- The built-in conversation and coding benchmarks are a setting (`evaluation.builtin_suites`, on by default).

## 0.8.0 — COGNITIVE EVOLUTION

- Conversation: verified multi-turn conversations that depend on earlier turns, conversation quality filters, and a held-out multi-turn benchmark scored per skill (context retention, follow-ups, clarifying questions, "I don't know", end of turn, repetition).
- Coding: verified debugging, code-explanation and test-writing curricula; held-out code-generation and debugging benchmarks executed in an isolated, resource-limited process.
- Evolution 4.0: 50 % conversation / 40 % coding / 10 % other as the starting focus, weakness targets for the new benchmarks, and a gate that rejects candidates whose conversation or coding group gets worse overall.
- Knowledge 2.0 (category, project, confidence, verification, review dates, near-duplicates) and an extractive, cited Research Engine.
- AI → Model: benchmark history across promoted versions; measured serving performance with thread tuning kept only when faster with identical output.
- Measured: see [docs/COGNITIVE-EVOLUTION.md](docs/COGNITIVE-EVOLUTION.md#measured-results-in-this-releases-development-environment).

## 0.7.2 — The whole network works on MOTH

- Workers prepare data: dataset chunks are tokenized and hashed on workers; MOTH Cloud re-encodes sample records of every chunk and refuses any mismatch, takes unclaimed or late chunks itself, and removes exact duplicates when merging (the result is byte-identical to preparing everything on MOTH Cloud). Feedback data never leaves MOTH Cloud.
- MOTH Cloud trains together with the workers: the server enrolls its own built-in worker ("MOTH Cloud server") and joins distributed training rounds, data preparation and evaluations under the same verification. It pauses during its own local experiments and follows AI Settings → What trains MOTH.
- Evolution stops repeating what does not work: a strategy with 4+ runs and no accepted improvement is suspended while another strategy is producing improvements.
- New verified synthetic sources: reasoning (sequences, orderings, multi-step problems) and language (plurals, opposites, alphabetical order, word counts, sentence casing).
- Interface: view and tab transitions, skeleton loading states, consistent button press and focus feedback (reduced motion respected).
- Details: [docs/GENESIS-ASCENSION.md](docs/GENESIS-ASCENSION.md#072).

## 0.7.1 — GENESIS ASCENSION, continued

- AI → Model: the active MOTH model in one place: an animated core drawn from its real layers and heads, verified parameters, architecture, checkpoint, tokenizer, deployment, held-out capabilities compared with the rollback model, lifecycle and compact history. The numbered-circle diagram and the separate Cloud model registry section are gone (the registry API stays).
- Minimum monitored requests is 0 (migrated once): zero user traffic never blocks a promotion; health checks are the evidence.
- One active + one rollback model, shown in the Model tab; older packages are removed after each verified promotion.
- Owner-only notifications, enforced by the server, with a bell for the Owner.
- AI Settings → What trains MOTH: MOTH Cloud server, workers and this computer, in any combination.
- Workers update at once: the heartbeat announces new worker releases, every worker gets them immediately, failed installs back off.
- Updaters: the cloud agent uses conditional GitHub requests and respects rate limits; the desktop checks hourly and treats a staged rollout as a wait.
- Details and limitations: [docs/GENESIS-ASCENSION.md](docs/GENESIS-ASCENSION.md#071).

## 0.7.0 — GENESIS ASCENSION

- One model identity: MOTH 0.0.1, 0.0.2, … — the public version advances only on verified upgrades; earlier labels are renumbered once without touching weights; the active version is shown in every section.
- Incoherent replies are diagnosed from the model's own output (tokenizer, decoding or training); a tokenizer problem blocks growth.
- Verified synthetic foundation data: arithmetic, simple instructions and Python functions, each checked before use.
- AI page: compact MOTH Intelligence panel; the architecture diagram moved to AI Settings → Advanced → Model Architecture.
- Self-repair: a training process that stops advancing is restarted from its last checkpoint.
- Details and limitations: [docs/GENESIS-ASCENSION.md](docs/GENESIS-ASCENSION.md).

## 0.6.4 — One computing network

- One computing network: MOTH Workers 0.6.4 now train conversation data too (the loss mask travels with the job), placement follows measured speed, untaken work moves back to MOTH Cloud, and AI → Evolution shows every machine. The manual Training Jobs controls are retired.
- Fixed a MOTH Worker restart loop after a second automatic update.
- Details: [docs/DISTRIBUTED-EVOLUTION.md](docs/DISTRIBUTED-EVOLUTION.md#one-computing-network-moth-cloud--workers).

## 0.6.3 — DISTRIBUTED EVOLUTION

- Parallel experiments: while one experiment trains, free compute (MOTH Cloud or an online worker) starts the next one. Measured 1.23× faster on one shared 4-core machine.
- Evolution 2.0: remembers which strategies and data mixtures improved held-out results and runs the promising ones first; grows its data when the model has outgrown it.
- Automatic promotion verifies health even when cloud answering is off, keeps the previous working model for rollback and removes older versions' files.
- Three more licensed coding datasets (Magicoder OSS-Instruct, CodeFeedback, Glaive Code Assistant) with pinned checksums; streaming JSON parsing.
- Evolution command center: objective, active and rollback models, parallel experiments, workers and their tasks, and what is holding progress back — from server records only.
- Continuous evolution: rounds run back to back with no timer; only a failed round waits briefly before retrying.
- Every parameter count is counted from the saved weights; older releases are measured automatically and the app says when a count is verified.
- Capability-based growth: MOTH grows its architecture only when measured capabilities (arithmetic, reasoning, coding, instruction following, language) stall and other causes are ruled out; larger candidates must improve those capabilities before they are kept.
- Details and limitations: [docs/DISTRIBUTED-EVOLUTION.md](docs/DISTRIBUTED-EVOLUTION.md).

## 0.6.2 — AUTONOMOUS GENESIS

- Five sections: Chat, Projects, AI, Network, Settings. AI holds Evolution, Data, History and AI Settings.
- Chats: rename, delete one, delete selected, clear all; optional automatic retention (off by default).
- Start Evolution: one click creates the first model if needed, selects trusted coding-first data, prepares it and keeps MOTH improving within your budget. Pause at any time.
- The Evolution Engine adapts steps, learning rate, batch size and pace from measured results and explains every change.
- Live training telemetry (compute, memory, workers, losses, speed, elapsed, honest remaining time) and a live activity stream of what the engine did.
- Credentials are removed from all training data; Dataset Quality Studio reports them.
- AI Settings in plain words; storage view and safe cleanup on MOTH Cloud.
- Details: [docs/AUTONOMOUS-GENESIS.md](docs/AUTONOMOUS-GENESIS.md).

## 0.6.1 — Genesis Reset, fresh genesis and growth clarity

- Genesis Reset moved to Settings → Advanced: review the real deletion inventory, type `RESET GENESIS`, confirm once more. MOTH Cloud still accepts the phrase the published 0.6.0 desktop sends. Optionally also deletes the native AI data stored on this computer.
- "No Model — Ready for Genesis": a guided fresh start with a choice of tokenizer and model size (real parameter counts from the server) replaces the empty Overview.
- Model size and growth: plain explanation of why the parameter count is unchanged, the planner's evidence, and an Owner-requested growth experiment that is evaluated like any other candidate.
- Gated Hugging Face datasets no longer fail as "not found": the message says the dataset is gated and how to get access.
- Interface: no-model states say what to do next; Network no longer repeats its switch and heading; Project Intelligence and Dataset Quality Studio use the app's controls; History states a single measurement instead of drawing an empty chart.
- Details: [docs/GENESIS-RESET.md](docs/GENESIS-RESET.md).

## 0.6.0 — LIVING INTELLIGENCE (release candidate; not published)

- Eight workspaces with focused pages, progressive controls, keyboard feature search and optional guidance.
- Shared account-scoped live model status and real simultaneous activity animations with reduced-motion/visibility handling.
- Searchable/paged Chat, copy/regenerate, recent projects and response-order protections for unsaved editor changes.
- Private incremental Project Intelligence reusing existing retrieval/memory, explicit Cloud sharing and refresh/delete controls.
- Dataset Quality Studio with non-destructive previews, source/license/import evidence, compatibility and prepared artifact checks.
- Existing evolution lifecycle extended with capability-labeled reference suites and bounded paired consistency scoring.
- Owner-only full native AI reset: inventory, reauthentication, typed confirmation, worker fencing/acknowledgement, retryable failures, verified empty state and separately confirmed backup scope. Never triggered by upgrades.
- Unified filtered activity/history and quiet deduplicated notices.
- Release workflows retain signing/tests and default to verified candidate artifacts; publishing requires an explicit dispatch choice and Owner approval.

Normal updates preserve existing data. Reset testing is isolated only. Foundation training completion and physical GPU execution are not claimed. Phase evidence and limits: [LIVING-INTELLIGENCE](docs/LIVING-INTELLIGENCE.md).

## 0.5.4 — ASCENSION, milestones 3–5: FOUNDATION, EVOLUTION 2.0, EXPERIENCE

MOTH Cloud, MOTH Code and MOTH Worker 0.5.4. Milestones 0.5.2 (FOUNDATION), 0.5.3 (EVOLUTION 2.0) and 0.5.4
(EXPERIENCE) were developed and tested one after another; they are published together as 0.5.4 because
all three were complete before the first could be released (the MOTH 0.1 training run gated 0.5.2).

**FOUNDATION** ([docs/FOUNDATION.md](docs/FOUNDATION.md))
- MOTH 0.1 — Foundation: a 49.3M-parameter MOTH transformer with its own 16k BPE tokenizer, trained on the
  approved dataset library (released separately as the signed model release `model-v0.1`).
- Official model releases (`kind: model`), signed with the MOTH release key; the update agent relays them,
  MOTH Cloud re-verifies, evaluates and deploys them. A model that fails its release criteria is never
  published (the release workflow re-runs the benchmarks itself).
- Model identity independent of app versions (MOTH 0.1, 0.2 …).
- MOTH on this computer: MOTH Code downloads the deployed model (signature and SHA-256 verified) and answers
  without the internet, automatically when MOTH Cloud cannot be reached.
- Checkpoint retention with milestones; capability benchmarks and release criteria.

**EVOLUTION 2.0** ([docs/EVOLUTION2.md](docs/EVOLUTION2.md))
- Continuous improvement from the development checkpoint (weights + optimizer), curriculum mixtures,
  research variants, duplicate-free experiments, early stopping, capability regression gates.
- Distributed training rounds across CPU and GPU workers with verified, token-weighted averaging,
  speed-proportional workloads, recovery from disconnections; CPU workers evaluate candidates (two
  agreeing results).
- Unified training: MOTH Code contributes its computer to the same experiments; Use cloud workers (on by
  default); per-participant contributions.
- Adaptive Parameter Growth: function-preserving depth/FFN expansion sized by evidence and budget, tested as
  a candidate, Owner approval above +25%.
- Staged rollout (20% first), version pinning, server-signed model manifests, automatic model versions.

**EXPERIENCE**
- One navigation: Chat, Code, Intelligence, Evolution, Network, Settings (plus Owner tools).
- Chat: full-page conversations with the active model and its measured capabilities.
- Intelligence: progress dashboard and the MOTH timeline, from measurements only.
- Evolution: one switch for automatic evolution, start / pause / resume, the training network.
- Settings in five tabs; new onboarding.

MOTH Worker 0.5.4 runs evaluation jobs; MOTH Cloud's schema stays 5 (no migration).

## 0.5.1 — ASCENSION, milestone 2: INTELLIGENCE

MOTH Cloud and MOTH Code 0.5.1. Details: [docs/INTELLIGENCE.md](docs/INTELLIGENCE.md).

- **Intelligence Router:** every chat request goes to the best available model for what it needs
  (benchmarked per capability, then latency), with fallback when a model fails and plain-language
  errors when none can answer. External (OpenAI-compatible) providers are supported but **off by
  default**, and used only for users who allow them.
- **Real streaming chat on MOTH Cloud** (`/v1/chat`): tokens stream as they are generated; optional cloud
  conversation history with delete controls (MOTH Code keeps its history on the computer and asks the
  cloud not to store it).
- **Knowledge Engine:** shared (Owner-approved) and private documents, versioned and deduplicated, BM25
  search, cited answers. Private knowledge is isolated per user.
- **Feedback learning with consent:** rate answers and report what went wrong. Prompts and answers are
  stored only with the user's opt-in; Owner-approved feedback becomes training data.
- **Smart Dataset Library & Data Factory:** eight approved, licensed datasets (TinyStories, Dolly 15k,
  OpenAssistant, Simple English Wikipedia, GSM8K, ARC, MBPP, Python standard library), pinned to exact
  revisions and SHA-256, downloaded once and reused; cleaning, PII scrubbing, quality scoring, benchmark
  decontamination, exact and near-duplicate removal, reproducible manifests, Owner-approved dataset
  updates.
- **Curriculum and Weakness Detection:** staged curriculum with replay and epoch caps; capability
  benchmarks on held-out data (maths, reasoning, executed code, instruction following, held-out loss per
  domain, safety); weaknesses, regressions and recommendations; candidate models must not regress beyond
  sampling noise.
- **Training integrity:** checkpoints carry SHA-256 sidecars; resuming verifies them and falls back to the
  newest intact checkpoint; one trainer per run directory (lock); bf16 training on CPUs with AMX.
- **Safety baseline** on MOTH Cloud (Owner toggle).
- Database schema 5 (new tables only; nothing existing is changed).
- MOTH Code: Settings → Intelligence & privacy (consent switches, models, my knowledge); sources and
  ratings under cloud answers; Owner Dashboard → Intelligence (dataset library, builds, weaknesses and
  curriculum, feedback review, shared knowledge).

## 0.5.0 — ASCENSION, milestone 1: EasyConnect workers, CPU workers, Rewards 2.0

MOTH Cloud, MOTH Code and MOTH Worker 0.5.0 are released together. This is the first of the staged
ASCENSION releases (see [docs/ASCENSION.md](docs/ASCENSION.md)).

- **EasyConnect worker installation:**
  - MOTH Code → Training & Referrals → **Add a computer** gives one command for Linux/macOS and one
    for Windows (PowerShell)
  - it downloads MOTH Worker from your MOTH Cloud, verifies the pinned SHA-256, installs Python
    packages and the right PyTorch (CUDA or CPU), enrolls with a single-use 15-minute token, and
    starts the worker automatically: systemd, cron without sudo, a Windows scheduled task, or launchd
  - crash restarts, a single running instance and a rotating log
  - re-running the command on the same computer replaces its old registration
  - `moth-worker uninstall` removes everything and revokes the worker
  - Windows needs no administrator rights; Python is installed with winget if it is missing
- **Fix:** MOTH Cloud now serves the worker bundle that its update agent relays from signed releases
  (`/downloads/worker/…` returned 404 on 0.4.0 servers).
- **CPU workers are production workers:**
  - no experimental flag (the old "Allow CPU workers" setting is retired)
  - workers report a measured benchmark (GFLOP/s), their CPU and memory
  - jobs are assigned by capability: a worker only gets jobs that fit its memory, and jobs that
    benefit from a GPU wait briefly for an online GPU worker
  - CPU workers use all but one core by default, adjustable per worker in MOTH Code
- **Referral Rewards 2.0:**
  - compute rewards are proportional to the tokens a referred worker actually trained, per verified
    job, after a minimum number of verified jobs
  - signing up, idle workers, failed jobs and repeated claims earn nothing
  - rewards are held for Owner review when a worker is unreliable or its computer is enrolled under
    another account (privacy-preserving machine ids)
  - rewards for a referred user's payment are off by default
  - users see the rules in plain words and each referred worker's contribution and earnings; the
    Owner can approve or reject held rewards
- **Database:** migration 4 (additive): `workers.machine_id`, `workers.trained_tokens`.
- **Tests:** end-to-end worker installation on Linux (CPU-only, cron start, crash recovery, uninstall)
  and on Windows (CI), Rewards 2.0 rules, and an upgrade test from the release production runs
  (server-v0.4.0), including existing worker credentials.

## 0.4.0 — EVOLUTION

MOTH Cloud can now improve its own model, safely and unattended. See [docs/EVOLUTION.md](docs/EVOLUTION.md).

- **Automatic model evolution:**
  - continued training from the deployed model's weights, with its exact architecture; never from
    scratch unless explicitly configured
  - candidates are new versions; the active model is never overwritten
  - resumable, checkpointed training jobs
  - one cycle at a time, scheduled automatically with back-off; evolution pauses itself after
    repeated failures
  - state survives restarts and upgrades
- **Approved training data only:**
  - training uses only datasets the Owner approved, each with a declared license
  - data containing user data needs explicit confirmation that the users gave permission
  - secret-looking files are skipped
  - only hashes, licenses and counts are recorded
  - revoking a dataset stops unfinished experiments that use it
- **Training memory:**
  - runs, reproducible configurations, data used, results, regressions, weaknesses, resource use,
    duration and model lineage are kept in the database
  - experiment planning uses this history: new data first, then measured weaknesses, then learning
    rates that worked before
  - an exact configuration is never run twice
  - event retention is configurable
- **Smart compute manager:**
  - detects CPU, RAM, disk, GPUs and VRAM, and the GPUs of MOTH workers
  - trains on a local GPU, a MOTH GPU worker (existing worker software, new `evolve_train` job), or
    the server's CPU only if enabled
  - only during low activity, within thread, memory, disk and daily-budget limits
  - pauses with a checkpoint when MOTH Cloud gets busy or resources run low, and resumes later
  - without suitable hardware, training waits and says why
- **Experiment laboratory and evaluation gates:**
  - the candidate and the deployed model run the same deterministic benchmarks: held-out score on
    the training data, retention on everything learned before (catastrophic forgetting), Python
    completion validity, optional Owner task suites (reasoning, instruction following, accuracy),
    speed and memory
  - every gate must pass; a lower training loss never counts as an improvement
- **Safe promotion:**
  - the existing checksum and inference health check, then an atomic switch
  - post-deployment monitoring of real error rate and latency, plus health probes
  - automatic rollback to the previous stable model
  - Owner rollback to any earlier compatible version
- **Evolution dashboard** (Owner Dashboard → Evolution):
  - status, active and stable model, cycle and experiments with real progress, evaluation
    comparison, version history with lineage, compute, training data, activity and warnings, and
    settings
- **Database:** migration 3 (additive) adds `training_datasets`, `evolution_cycles`,
  `evolution_experiments`, `evaluation_reports`, `model_lineage` and `evolution_events`; existing
  releases get their lineage recorded.
- **Update agent:** the server's own update and rollback now run before relaying desktop/worker files,
  so a slow download can no longer delay a server update.
- **Fix:** the training network no longer cancels queued jobs of other kinds when a new round starts.

## Server 0.3.2 — reliable release downloads

- **Fix: the update agent could not relay Desktop 0.3.1 to clients.** The VPS logged *“could not fetch
  desktop 0.3.1: MOTH.Code_0.3.1_x64-setup.exe does not match the SHA-256 in the signed manifest”*.
  The release was correct: the signed manifest, GitHub's own digest of the uploaded file, and the
  release workflow's checksums all agree (`19bd549b…`). The agent's download was the problem. When a
  connection dropped part-way through the 129 MB installer, Python's `urllib` returned the partial
  body without an error. The agent then correctly rejected the short file, deleted it, and started
  over 15 minutes later.
- Downloads are now checked against the announced length and the size in the signed manifest, and
  interrupted downloads resume with HTTP Range requests (up to 10 attempts). The SHA-256 and
  signature checks are unchanged. A complete file with different bytes is still refused, and the
  error now reports the received size and hash.
- All components are now version 0.3.2. Desktop 0.3.1 stays the current desktop release: its signed
  artifacts are correct and were not replaced.

## Desktop 0.3.1 / Server 0.3.1 — connection and updates

Fixes *“MOTH Cloud unavailable”* and makes desktop updates work end to end.

- **Editable MOTH Cloud address (Settings → Connection).** Enter any address and choose *Test & use*.
  MOTH Code checks that it really is a MOTH Cloud server before switching. If the same server is
  reachable at the new address, you stay signed in. *Use default* goes back to the built-in address,
  and changing the address never needs a new build. The sign-in dialog shows the address in use. No
  temporary address is built into the release.
- **Clear cloud status.** The status bar says why nothing is served:
  - unreachable (retrying)
  - not a MOTH Cloud server
  - no model deployed yet
  - inference turned off

  Tunnel errors (HTTP 52x) are explained. `/v1/health` now returns `status` and `message`.
- **Server behind a tunnel or proxy.** Download and update links follow the address the client used
  (trusted `X-Forwarded-*` headers), so they work through Cloudflare tunnels. The Owner can set the
  server's public address in the dashboard (Server → Public address). Emails and referral links use
  that address.
- **Model uploads.** Interrupted chunk uploads are retried, with a visible notice (*“HTTP 524 …
  retrying in N s”*). Paused uploads resume by themselves every minute. The upload percentage and size
  are shown. Errors from proxies (HTML pages, 413, 52x) are turned into readable messages.
- **Desktop updates, verified end to end:**
  - the update endpoint follows the configured server address
  - checks run at start-up (not only after the local backend is ready) and every 6 hours
  - the download is verified with the updater key, and downgrades are blocked
  - *Restart now / Later*, installing on close if postponed
  - the local backend is stopped before the installer runs
  - an update log for support
- **Separate desktop and server releases** (`desktop-vX.Y.Z` / `server-vX.Y.Z`, manifest `kind`).
  The update agent installs only server releases on the VPS and relays desktop releases to clients.
- Update agent: stale (zombie) process detection and a single-instance lock.

## 0.3.0 — SIMPLIFY

MOTH becomes self-managing: install once, sign in, code; everything else updates itself.

- **Automatic connection:**
  - the official MOTH Cloud HTTPS endpoint is built into release builds (no server address, SSH
    tunnel or port on first launch), with production, staging and development environments
  - a developer-only override, hidden under Settings → Advanced
  - background reconnects with exponential backoff, request timeouts and retries
  - a quiet connection status that never pops up
- **Sessions:** session restore, automatic token rotation, clear expiry handling, and version
  compatibility checks (HTTP 426 for outdated clients; older clients can still update).
- **Automatic updates for the whole ecosystem:**
  - Desktop: Tauri updater served by MOTH Cloud with staged rollouts, background download, install
    on restart or exit, and outcome reporting.
  - MOTH Cloud: a standalone update agent with signature verification, verified backups, migration
    checks, health checks, automatic rollback (including database restore), crash and reboot
    recovery, and self-update.
  - Workers: verified self-update between jobs, with automatic revert on failure.
  - Releases: one signed release workflow for every component, release channels, rollouts that halt
    automatically, and deployment history.
- **One-time server installation** (`deploy/install-server.sh`):
  - adopts the existing VPS in place, with no data moved and a backup first
  - works without sudo, listing the administrator steps separately
  - systemd or cron supervision, daily verified backups, Caddy HTTPS with internal endpoints blocked
- **Owner Dashboard:** Server (CPU, RAM, disk, API health, active users, errors), Updates (versions,
  rollouts, deployment history, pause, retry, approve migrations, rollback), AI models (lifecycle,
  evaluation, publish, deploy, rollback, evaluation data) and Workers (CPU/GPU, versions, progress).
- **Model publishing fixed:**
  - *"no evaluation set is configured"* no longer blocks publishing. Evaluation datasets can be
    uploaded and validated in the dashboard, and a built-in held-out text set is always available.
    Text datasets are scored in bits per byte, so models with any tokenizer can be evaluated.
  - Releases rejected for missing data (including v0.2 rejections) are re-evaluated automatically
    without re-uploading.
  - Persistent lifecycle states. Local validation before upload. Resumable, checksummed chunked
    uploads with duplicate detection.
  - Evaluation runs in an isolated process with real inference. Deployment checks resources and runs
    an inference health check first.
  - Interrupted work is recovered after restarts.
- **Desktop UI:** a first-launch flow (sign in → open a workspace → code), one Owner entry in the
  navigation, simpler settings, and a guided Validate → Publish view with live upload progress.
- **Tests:** the new evaluation, publishing, update-service and worker-update suites, plus a real-process
  end-to-end test of installation, adoption, updates, rollback, recovery and reboot.

## 0.2.1

- **Fix: signing in failed with "Not Found"** when the MOTH Server address was typed without `https://`. Addresses
  are now normalised (`moth.example.com` → `https://moth.example.com`, `localhost:8900` → `http://localhost:8900`,
  pasted `/v1/...` paths dropped), and an address that isn't a MOTH Server shows a clear message.
- **Fix:** the desktop app's content security policy only allowed connections to `127.0.0.1`, so an HTTPS MOTH Server
  (and avatars served from it) was blocked in the installed app.

## 0.2.0 — CONNECT

MOTH becomes a cloud service with accounts, usage plans, referrals and a GPU training network.

- **MOTH Server** (new, owner-operated):
  - accounts: Argon2id, email verification and recovery, rate limits, no enumeration, sessions and revocation
  - LK5T Owner with one-time interactive setup and re-authentication for sensitive actions
  - plans with atomic token metering and a credit ledger
  - Stripe subscriptions with verified webhooks (checkout disabled until configured)
  - referrals with pending, capped and reversible rewards
  - training coordinator with worker enrollment, leases and verified contributions
  - model registry with an evaluation gate, deployment and rollback
  - metered MOTH Cloud inference
  - Owner-only server-side content policy, Owner Dashboard API and audit log
- **MOTH Worker** (new): one-command, checksum-pinned Linux GPU enrollment; resumable, resource-limited training;
  systemd service.
- **Desktop:**
  - cloud-only chat and agent with a MOTH account and per-workspace consent
  - Windows Credential Manager sessions, saved accounts and switching
  - Settings → Account, Plan & usage, Referrals
  - Training & Referrals view
  - Owner Dashboard; Owner-only model tools with "Publish to MOTH Cloud"
  - MOTH Cloud status and outage handling
- **Removed** (cloud-only architecture): local inference and model loading, local/auto inference modes, the
  local content-policy editor (now server-side), and the v0.1 Community view (replaced by Training & Referrals).
- **Deployment:** Dockerfile, Compose (PostgreSQL + Caddy TLS), systemd unit, encrypted off-host backups with
  verified restore.
- **CI:** server tests on SQLite and PostgreSQL, Linux worker-install test, Windows Credential Manager test.

## 0.1.0 — Foundation

First release of MOTH Code: the complete pipeline from an empty, randomly initialised network to a desktop coding
agent, with every subsystem implemented and tested. No pretrained model is included.

- Desktop app (Tauri 2, React, TypeScript, Tailwind, shadcn-style UI) with MOTH branding: workspace with chat and
  agent modes, explorer, Monaco editor, terminal, Git changes, activity and memory; training dashboard; models and
  inference; learning network; settings.
- MOTH Model: original decoder-only Transformer, presets up to 400M parameters, MOTH-50M at 49.3M; custom byte-level
  BPE tokenizer.
- Training: license-tracked data, mixed precision on CUDA with CPU fallback, checkpoints with exact resume,
  evaluation, export.
- Owner-defined content policy, separate from always-on operational security.
- Autonomous coding engine with permissions, approvals, verification, memory, retrieval, cancel/resume/revert, and
  honest capability reporting.
- Opt-in community learning protocol with validation and aggregation; hybrid local/cloud inference with consent and
  redaction.
- CI on Windows and Linux; Windows installer with bundled backend; signed in-app updates.

See [docs/LIMITATIONS.md](docs/LIMITATIONS.md) for what is not finished.
