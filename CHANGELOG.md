# Changelog

Newest first. Links to design notes of past versions were removed with those notes (1.0.16 clean-up); the
current design is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/EVOLUTION.md](docs/EVOLUTION.md).

## 2.4.0 — Saved prompts, chat tabs, Run code, and MOTH on your phone

**Chat**
- **Saved prompts:** the bookmark next to the paperclip keeps your common requests (four useful ones to start). Use one in a click, or save what you typed. They follow your account.
- **Chat tabs:** the chats you open stay as tabs above the conversation (up to 8). Close a tab with ×; **+** starts a new chat.
- **Run on code blocks:** Python, JavaScript, Bash, PowerShell, Ruby, PHP, Lua and Perl code in an answer can be run on your computer. It runs in an empty temporary folder for up to 15 seconds, and the output shows under the code. You're asked first, and shell code that looks destructive or contacts the network gets a second warning.
- **Ctrl+K finds files** in the open project, as well as chats, projects, actions and settings.

**Home**
- **Top helpers this week:** a leaderboard of whose computers trained MOTH most (MOTH Cloud's own worker is not counted).
- **Test scores across versions:** a small line per skill (coding, maths, conversation…) showing how it changed from version to version.

**Network and workers**
- **Pause while gaming:** on Windows, a worker pauses while a game, video or presentation is full screen, and carries on when it closes. It's on by default and can be switched off per computer in Network. Network shows when it's paused for this. It checks whether the window in front covers the whole screen; a worker running in the background with no screen never pauses.
- **Fixed:** GPU load, GPU memory and temperature from workers now reach Network. MOTH Cloud was keeping only CPU and memory, so the 2.3.1 health line never showed the GPU.

**Phone status page**
- Open **https://mothcloud.ddns.net/status** on your phone. It shows the model, its size, whether MOTH is learning, how many computers are helping and when it last upgraded, and refreshes every 30 seconds. It shows no names or data.

**Report a problem**
- Settings → Updates & about → **Report a problem** (or Ctrl+K). It sends your description with this app's version, recent logs and training status (no chats or files). As Owner you see the reports, with their details, below it.

## 2.3.2 — Training no longer gets stuck waiting for a computer

**Fixed: shared training could stop for good**
- When several computers train MOTH together, each round waits for every computer's part. If a computer took its part and then went to sleep, was paused or got busy (while still checking in), or if nobody picked a part up again after its computer left, the round waited forever. Experiment #65 sat at round 1 with one part done and the other queued at 90%.
- A part with no progress for 20 minutes is now taken back and given to the next free computer (MOTH Cloud included).
- If nobody takes a part for 20 minutes while the round's other parts are done, the round continues with the finished parts. They are combined and checked as usual.
- A part handed to a different computer is resized for it. A GPU's large share handed to MOTH Cloud's CPU used to take that CPU many hours.

**New: AI → Shared training**
- A new tab that shows a shared run as a picture: MOTH in the middle and each computer's part around it, animated while it trains.
- Each part is described in plain words ("done", "training · 40%", "waiting for a computer"), along with whether the last round made MOTH better and who has helped. Network links to it.

**Also in this version (from the 2.4 work)**
- **Attach a folder, a screenshot or photo, or a GitHub link** from the paperclip, or paste a screenshot straight into the message box. MOTH reads text, not pictures: the text in an image is read on your computer (Windows' built-in text recognition) and sent with your message, and the image shows in the chat.
- **Edit** your message (it and the replies after it are replaced), **Branch** a chat from any message, and rate any answer with 👍/👎, including answers from this computer.
- **Themes:** Dark, Midnight, Graphite and Light, plus six accent colours (Settings → Appearance). They follow your account to your other computers.

## 2.3.1 — See what MOTH is doing, and why

**Home (everyone)**
- **This week:** training runs finished, how many made MOTH better and went live, growth in parameters, and how long your own computers trained.
- **How MOTH answers now:** the same questions answered before and after its last upgrade.
- **Train on this PC:** one click lets this computer help train MOTH between your own work. With an NVIDIA GPU, **Use my GPU** opens Network to install the MOTH Worker.

**Promotions**
- Each new version is now checked **side by side** with the current model on the same prompts, and the replies are stored.
- The timeline shows **why a version was or was not promoted** ("Blocked by: …" or "Small trade-offs: …") and its side-by-side replies.
- **A verified backup is requested before every promotion** (MOTH Cloud's agent runs it within minutes, while the staged rollout still serves the previous version).

**Workers**
- **Health in Network:** CPU, memory, GPU load, GPU memory and temperature for each computer, now also on Windows. Warnings for a hot GPU, full memory, mostly failed jobs, or a GPU that sits unused while it trains on the CPU.
- **Training hours:** each computer can train any time or only between chosen hours (overnight windows work). Outside them it takes no new work.

**Alerts**
- A desktop alert when training stalls (no progress for an hour), alongside the existing promoted and worker-offline alerts.

**Fixes (2.3.0 did not ship because of these)**
- **Windows install from Command Prompt:** when Command Prompt was opened from PowerShell 7, the command stopped with "Get-FileHash is not recognized". It now uses the system module path and checks the download's SHA-256 with .NET directly.
- **Shared rounds no longer stall on a lost shard:** only whole experiments wait 10 minutes for the computer that slept. A shard of a shared round goes straight to another computer.

## 2.3.0 — A new look, and MOTH learns everyday conversation

**A cleaner, more compact app**
- **New sidebar:**
  - New chat, Search chats and Chat at the top.
  - **Projects as folders** that open to show their own chats. A **+** starts a new chat in a project.
  - **Chats** (outside projects) below.
  - The other sections as small icons at the bottom, with your account, notifications and Settings.
  - It still collapses to an icon rail.
- **Messages:** your messages sit on the right with a small "You" label. MOTH's replies are plain, full-width text under a "MOTH" label instead of bubbles.
- **Message box:** one card, with the text on top and attach, the answering model and **Send** / **Stop** below. A small status line underneath shows "Connected to MOTH Cloud", "Answering on this computer" or why MOTH can't answer.
- **GPU hint:** "This computer" says when your PC has an NVIDIA GPU. The app trains on the CPU (its built-in PyTorch is CPU-only), so the hint suggests installing the MOTH Worker from Network to use the GPU.

**Better conversation data**
- MOTH answered "Hello! How are you today?" with "You said you love soup." Its conversation data was mostly memory drills (names, favourite foods, shopping lists) with only four fixed greetings, so it learned to repeat facts.
- The data is now about 45 % everyday conversation: greetings, small talk, thanks, "what can you do?" and goodbyes in many wordings, plus short coding answers. Replies that recite facts the user never gave are rejected.
- MOTH Cloud rebuilds its training data with it on the next preparation.

## 2.2.6 — GPUs do the heavy lifting; Windows workers fixed

**Windows workers**
- **GPUs with 4–6 GB are used.** A GPU counted only with at least 8 GB of memory, so a 3050 (laptop or 6 GB), 1650 or 2060 quietly trained on the CPU. The minimum is now 3.5 GB; each job still checks that the model fits.
- **nvidia-smi is found even when a background service's PATH lacks it** (System32 and the NVIDIA folder are checked), so the GPU is detected.
- **The install command works in Command Prompt *and* PowerShell.** It starts Windows PowerShell itself, with scripts allowed for that one process, so pasting it into the wrong window or a locked-down script policy no longer fails. Network shows what it runs. The Windows install test now runs it from Command Prompt.

**Faster training with a GPU**
- **Speed-matched shared rounds.** When computers train one experiment together, each gets steps in proportion to its *measured* training speed, from 0.1× to 25× the base (was 0.25×–4× from a CPU benchmark), so a GPU no longer waits for CPUs every round.
- **A fast GPU is kept for the growth step.** While a bigger model is being trained, a GPU at least 5× faster than MOTH Cloud is not given a smaller parallel experiment; it joins the growth step instead.

**Sleep, restarts and lost connections**
- **Saved progress is used.** When a worker stops responding (sleep, restart, network), its experiment continues from the last progress it sent instead of starting again.
- **Held for the returning computer.** The experiment is held for that computer for 10 minutes, so it usually picks it straight back up.
- **Progress is sent every 5 minutes** (was 10).

## 2.2.5 — No 30-minute wait when nobody is chatting

- A new model is first served to 20 % of chats and watched for 30 minutes, then rolled out to everyone or rolled back. With no users there is nothing to watch, so the wait only delayed MOTH. When nobody has chatted in the last day, monitoring now ends once three health checks have passed (about a minute and a half). With real users the full 30-minute staged rollout applies as before.

## 2.2.4 — Workers see their real free memory; unjudged growth no longer counts

- **Workers on Linux** measured free memory without the file cache that the system frees instantly when needed. A server full of datasets looked 97 % full, and experiments needing 0.6 GB were refused ("no other computer can hold it"). Workers now use the memory the system can actually hand out, including inside containers.
- **Growth attempts that could not be evaluated** (the "KeyError: 'value'" crash fixed in 2.2.2) no longer count as rejected. They were never judged, so they no longer block that model size.

## 2.2.3 — MOTH Cloud installs Node.js by itself

- When Node.js is missing, MOTH Cloud downloads the official Node.js 22 LTS build from nodejs.org into its own data folder. No administrator rights are needed.
  - The download is checked against the published SHA-256 list and unpacked safely.
  - It is put on MOTH Cloud's PATH, so the JavaScript exam runs again and JavaScript skill counts towards promotion.
  - A failed download is retried every six hours. Settings → Advanced → Diagnostics shows the attempt.

## 2.2.2 — Candidates are evaluated again

- Every candidate failed with "evaluation failed: KeyError: 'value'", so none could be judged or promoted. The cause: the JavaScript exam needs Node.js, which MOTH Cloud does not have. It returned "Node.js is not installed" without a score, and the benchmark crashed on the missing score, failing the whole evaluation. A suite that cannot run is now "not measurable", and one suite's error no longer fails the others.

## 2.2.1 — MOTH grows again

- MOTH had stopped growing its parameters. Its gradual growth steps were rejected along with every other candidate (the measurement-noise problem fixed in 2.2.0). After two rejections at one size, that size was blocked forever, and the sizing always chose that same size, so MOTH fell back to "train more first" indefinitely.
  - Only failures on the same base model within the last two days count now. A new base model, or two days, lifts the block.
  - While a size is blocked, MOTH tries a smaller step (at least 1.8×) instead of not growing at all.

## 2.2.0 — Better models get through, clearer training views, tidier app

**MOTH can finally move past its first model**
- Trained candidates far better than the serving model (held-out loss about 1.5 against 5.6) kept being rejected over measurement noise. Two checks are fixed:
  - **Speed and memory.** These were compared against a base benchmarked while MOTH Cloud was idle, while the candidate was benchmarked during training. A candidate with exactly the same architecture does the same work per token, so these numbers are now shown as information instead of blocking.
  - **Small exams.** On a small multiple-choice exam (such as the security exam a young model can only guess at), a drop within chance (three standard errors) no longer counts as a skill getting worse.
- **Worker results are kept.** A whole worker run on a small model can honestly move the byte embedding more than 10× its starting size. That was refused as "update too large (relative norm 11.5 > 10.0)", so Worker #13's work was thrown away. Finished runs are now checked for shapes and finite values; the promotion rule decides whether the result is good. Shared training rounds allow up to 100× (was 10×) and must still lower held-out loss.
- **Stuck promotions are visible.** When the last five or more candidates were all rejected, Evolution's "Holding back progress" line names the checks that blocked them most often.

**Training views**
- **MOTH timeline, redrawn:**
  - Readable version labels (at most about 8) and five gridlines.
  - A far-off point, such as the untrained seed, no longer flattens every other version into a straight line. It is drawn at the edge with its value.
  - Promoted versions, candidates that were not kept and the serving version look different.
  - Hovering a point shows its value.
  - One "Show" menu replaces the 11 buttons.
- **Evolution card:**
  - The Intelligence check names the model the same way as everywhere else ("MOTH 0.0.1 (v150)").
  - The plan line says it is the default for new experiments, so it no longer seems to contradict an exploration's own settings.
  - Exploration objectives are written in plain words.
  - Tokens per parameter below 1 are no longer rounded to "0.0".

**App**
- **"This computer" switch fixed.** It failed with "Could not authorize this device (HTTP 409)" when this computer's saved worker registration had been revoked or removed on MOTH Cloud (for example with Remove in Network, or by a reset). The app now enrolls the computer again and switches on.
- **Home:** "Clone from GitHub" sits with New chat and Open project. Repeated activity lines collapse into one with a count ("×5").
- **Sign-in screens** (Network, MOTH AI) have a Sign in button instead of an unrelated tip. The chat's Sign in and Retry buttons line up with the text.
- **Settings:** the tour and the quick introduction moved from the top of Account to About, under "New here, or need a refresher?".
- **Project chat toolbar:** the conversation picker no longer collapses to an arrow, and the model label no longer truncates to "signed …".
- **Less background work:** panels that refresh on a timer (owner dashboard, Network, models, usage ring, notices, cloud status) pause while the window is hidden or in the tray. Alerts still arrive.

**Clean-up**
- Removed:
  - Test-run output committed by mistake (`server/w/`, 70 files).
  - A stale copy of the worker build (`worker/build/`).
  - The unused "Servers & security" settings page and its test.
  - Unused developer-mode helpers.
  - An unused front-end package (`@tauri-apps/plugin-updater`; updates use the Rust plugin directly).
  - A finished 1.0 planning note.
- `.gitignore` now covers these build and test outputs.
- Server tests stop the training processes they start. Training runs in its own session on purpose so it survives a server restart, so finished tests had left them using whole CPUs for the rest of the suite.

## 2.1.2 — Clear worker status

- "Workers online" counted MOTH Cloud's own built-in worker, so it showed "1" even when none of your computers was connected. It now counts only your workers ("none of N connected" when they are all offline; "+ MOTH Cloud" when the built-in one is helping).
- The live training view says why a run trains on MOTH Cloud alone (for example "no other computer is online" or "it needs about X GB of free memory and your worker has less").

## 2.1.1 — MOTH grows gradually

- **Small growth steps.** A bigger MOTH is at most 3× the current one (100K → about 270K → about 700K …) instead of one jump to ~18M parameters trained from scratch for days. Each step trains in hours, starts from the current model's weights (same tokenizer), and must pass the promotion rule. Small steps keep the byte-level tokenizer; the switch to the BPE tokenizer comes once MOTH passes about 2M parameters.
- A successor already training under the old one-jump plan is stopped and replanned as a gradual step.
- **Checkpoints at least every 15 minutes**, so a restart never loses more than that (before, a long run could go hours without one).

## 2.1.0 — Security in chat, smarter training, dedicated workers

**Security, right in chat (no separate page)**
- "Audit my code": secrets and risky code (eval, shell injection, SQL built from strings, unsafe deserialisation, HTML injection, disabled TLS checks, debug mode…) in Python, JavaScript/TypeScript, PHP, Go, Java, C/C++, Ruby and shell. Secrets are never shown in full.
- "Check my dependencies": requirements, pyproject and package files against a built-in list of well-known vulnerable versions (not exhaustive, and it says so).
- "Is my nginx/SSH/Docker config secure?": the open project's configs or files you attach.
- "Test my website https://…": after your Yes, MOTH reads the site and tries harmless test values (GET only, never submits forms or changes data) for unencoded reflection (XSS), database errors (SQL injection), open redirects and forms without CSRF tokens, plus the header, TLS and exposed-file checks.
- Every finding has **Ask MOTH**, which asks for an explanation and a step-by-step fix.
- The Security page and Settings → Servers & security are gone; results live in the chat.

**Promotion rewritten: better overall, and nothing broken**
- Before, every single check had to pass, so a model that was better overall was thrown out when one test wobbled. MOTH never got past 0.0.4 because of this.
- Now a new model takes over when it is **better overall** (at least +0.2 %, was +0.5 %: the training data's held-out text counts twice, every skill group, retained data and the general evaluation text) and **nothing is broken**: it loads and generates, no single area is more than 25 % worse (was 10 %), no accuracy drops more than 15 points or 3 standard errors (was 10), no whole skill group (conversation, coding, security) is more than 10 % worse (was 5 %), and speed and memory stay within limits.
- Being a little worse on the general evaluation text no longer blocks on its own; it is part of the overall score.
- Smaller drops are shown as **allowed trade-offs** in Candidates vs the live model. Old default limits stored in settings move to the new ones once; values you set yourself stay.

**MOTH learns faster**
- Self-quiz on code: MOTH writes Python, SQL and JavaScript answers that are run; only answers that work are kept (wrong ones become corrections).
- New self-checked security dataset: vulnerable code and its fix (MOTH's own audit must flag the first and pass the second), what each finding means and how to fix it, and risky configuration lines.
- Bigger successors read 2,048 tokens at once (was 1,024).
- Young models (the foundation stage) start each run on short rows when longer rows are configured.

**App**
- Settings sync: app size, animations, quiet alerts and sounds follow your account to your other computers.
- Guided tour on first start (Settings → Account → Take the tour).
- "MOTH is learning" on Home for everyone while a training run is going.

**Workers**
- Standalone workers are dedicated training servers: every CPU core and 95 % of GPU memory, always on (they still pause above 85 °C or on low battery). The desktop app's "contribute this computer" stays gentle (about 90 %).

## 2.0.0 — MOTH 2.0: a coding and security-testing assistant that acts

**App**
- **Compact by default**, with an *App size* setting (Compact, Normal, Large); Ctrl + / Ctrl − / Ctrl 0 change it anywhere. Everything, including the editor and terminal, scales together.
- **More, smoother animations**: springy dialogs, sliding lists, hover lift and press bounce, a shimmering "Thinking…", findings that pop in. A switch turns them off, and they are always off when Windows has animations off.
- **Ctrl+K command bar**: actions, chats (titles *and* message text, with the matching words), projects, sections and every Settings tab.
- **Drag and drop** files or folders into chat (or use the paperclip). Text files only; keys, `.env` and credential files are never read; size limits apply. Attached files show as chips you can open.
- **Better messages**: syntax highlighting, headings, lists and quotes, a Copy button on every code block, and **Apply** on code that names a file.
- **Before/after review**: Apply and every agent edit (when auto-write is off) show a side-by-side diff with **Apply** and **Reject**.
- **Notification centre** (the bell) for everyone, with **quiet alerts**: only promotions and problems pop up; finished tasks, scans and smaller news wait in the centre.
- **Starter prompts** in an empty chat; faster long chats (off-screen messages are not drawn, finished messages no longer re-render while a reply streams).

**Security testing from chat**
- Ask "check 10.0.0.5:8080 for vulnerabilities" (or "scan 192.168.1.0/24 ports 22, 80 and 443"). MOTH shows exactly what it will scan and waits for **Yes**. Nothing is contacted before that.
- The scan runs from **your computer**: TCP connect scan, banners, HTTP and TLS checks, known-vulnerable versions (for example Apache 2.4.49/2.4.50, regreSSHion-range OpenSSH, vsftpd 2.3.4), services that should not be exposed (Telnet, SMB, RDP, databases, Redis without a password, open Docker API), exposed `/.git` and `/.env`, directory listings, missing security headers, expired/self-signed certificates and old TLS. It only looks; nothing is changed.
- Anything stronger (anonymous FTP login) asks for its own Yes. Live progress, a Stop button, a speed limit, one host or a small private network per scan, every step logged.
- New **Security** page with every scan, its findings, fixes and full log; a finished scan's summary is saved into the chat so you can ask about it.

**Agent**
- **Write → run → fix**: when the project's tests fail, MOTH gets the real output and fixes the code (up to three times) before finishing.
- Self-checks for JavaScript, shell, Go, C/C++, PHP, Ruby, Perl, Lua, TOML and YAML as well as Python and JSON (syntax only; project code is never run by the check).
- Fixed: a fix written in the same second as the broken version could run from Python's stale cache.

**MOTH itself**
- New self-checked training data: **SQL** (every query run in SQLite), **JavaScript** (run with Node.js) and **Bash** (run on prepared files). Added automatically where generated data is already used.
- New held-out **SQL exam**; it counts toward promotion with the other coding exams.
- **Calculator**: arithmetic in a question is computed exactly and given to MOTH as a fact.
- MOTH **checks the code in its answers** (syntax) and shows "✓ code checked" or the problem.
- **Apply and Reject teach MOTH** (as feedback, when training use is allowed).
- Workers use about **90 %** of the computer (one core always stays free; up to 90 % of GPU memory) unless you set a limit.
- The live model keeps serving until a new one passes every check; training progress and the successor in training are kept (its context length is unchanged so it does not restart).

## 1.1.0 — Big update: faster, steadier training and a coding/security exam

- **Continuous model.** A run that is not promoted is no longer thrown away: the next run keeps training the newest such candidate (same shape, verified checkpoint, validation loss at most 5 % above the live model's). It still has to pass every check against the live model.
- **Mistakes first.** After each evaluation, the skill areas with the highest validation loss get more of the next steps (each area's share changes by at most ±50 %).
- **Learning-rate probe.** Before a fresh run, MOTH tries 0.5×, 1× and 2× the planned learning rate for a few steps and keeps the best.
- **Bigger models start from the current one.** A larger successor with the same tokenizer starts from the current model's weights where the shapes overlap, instead of random weights.
- **Fairer promotion.** A quick pre-check rejects clearly worse candidates before the full benchmark; bigger, steadier benchmark samples.
- **New exams:** 12 JavaScript tasks run under Node.js, and a 30-question security exam (vulnerability classes, ATT&CK, protocols, shell and defensive practice). Both count toward promotion.
- **Owner dashboard:** *Candidates vs the live model* shows every recent candidate with its loss change and exactly which checks it passed or failed; *Where training time goes* splits recent experiments into preparing, waiting, training and evaluating.
- Sequence packing was already on; no change.

## 1.0.22 — Big update, stage 1: more learning per hour

- **DiLoCo shared training.** Each shared round's averaged change becomes the outer gradient of a Nesterov-momentum step carried across rounds (outer learning rate 0.7, momentum 0.9), which learns more per round than applying the plain average. If that step does not lower the held-out loss, the plain average is tried, and if neither helps the round is discarded as before.
- **Warm-up / stable / cool-down learning rate (WSD)** for every run: full learning rate for most of the run and a linear cool-down over the last 20 % (it was a cosine curve that started shrinking almost at once). This is the schedule continuous training needs.
- **One experiment at full power.** A cycle runs one experiment on every computer instead of two splitting them (applied once to existing installs; the Owner can raise it again).

## 1.0.21 — Training data trimmed for coding and security

Retired (no longer offered, approved or added automatically; data prepared earlier stays readable): TinyStories and TinyStories (full set), Cosmopedia stories, Cosmopedia web-seeded articles, FineWeb-Edu, Simple English Wikipedia, SmolTalk Magpie-Ultra conversations, SmolTalk constraints/rewriting/summaries, MetaMathQA and Cosmopedia math texts. They were general reading that took training time from code and security.

Kept: every code and security source, Cosmopedia textbooks (including computer science), OpenAssistant 1 and 2, Dolly and the verified conversations (so MOTH can still explain and ask), GSM8K, ARC and the small verified sets. The library now grows through cybersecurity instructions, multi-language GitHub code, CVE/CWE, OpenAssistant 2, SmolTalk code, OpenCoder and Cosmopedia textbooks.

## 1.0.20 — A coding and security-testing AI

- CVE/CWE and MITRE ATT&CK now count as code, so with the cybersecurity instructions, bash and multi-language code they share the largest part (55 %) of every training mix instead of the 4 % knowledge share.
- MOTH's system prompt describes it as a coding and security-testing assistant: it writes and fixes code, works with servers and the command line, helps with authorized penetration testing, explains what it is doing and asks when something is unclear.

## 1.0.19 — Security datasets and code in many languages

Five new training sources, each openly licensed and pinned to an exact upstream version with the size and SHA-256 of every file:

| Source | What MOTH learns | Licence |
| --- | --- | --- |
| CVE and CWE descriptions (1999-2025) | every published vulnerability: what it is, its severity (CVSS) and weakness class (CWE) | CC0 |
| MITRE ATT&CK tactics and techniques | the attack-technique framework: tactics, techniques, detection and mitigation | MIT |
| Cybersecurity instruction tuning | security questions answered in depth: defence, analysis, hardening, testing methodology | Apache-2.0 |
| Natural language to bash | everyday shell tasks and the command that does them | MIT |
| GitHub code (github-code-clean) | real, permissively licensed code in ~30 languages (C, C++, Go, Rust, Java, JavaScript, TypeScript, PHP, Ruby, shell, SQL…) | Apache-2.0 |

The small ones join the data library first; the larger ones lead the list the library grows through.

## 1.0.18 — Servers and engagements

- **Servers.** Save SSH profiles (name, host, user, port, optional key file) in Settings → Servers & security. MOTH's agent can run commands on them with the new `ssh_run` tool; every command is shown to you and needs your approval, and output streams live. No passwords are stored: the system's ssh uses your own keys or SSH agent; new host keys are pinned on first use.
- **Engagements** for authorized security testing: name the scope (hosts, IPs, CIDR ranges, domains, `*.example.com` for subdomains) and an optional end time. While an engagement is active, MOTH refuses any command, local or over SSH, that names a target outside the scope or runs outside the time window, and logs every command it runs (Log button) as the record for the report. With no engagement active, coding and server work run as before.
- The agent can list saved servers and the active scope (`list_servers`).

## 1.0.17 — Coding first

- MOTH becomes a coding and systems AI first: the main training mix is now 55 % code (including shell and server work) and 28 % conversation (it was 42 % conversation, 40 % code); the skills stage gives code 38 %. Each run's final part is 50 % conversation and 30 % code, so replies end cleanly and still explain the code.
- MOTH's default system prompt describes it as a coding and systems assistant that explains what it is doing and why.

## 1.0.16 — Promotion 2.0

- **New promotion rules.** A candidate is judged on its *overall* change: the training data's held-out gain (counted twice), every capability group's mean change and the retained data's mean change, averaged; it must improve by at least 0.5 %. A single test only fails on a real collapse (more than 10 % worse; accuracy more than 10 points or 3 standard errors), and a capability group's mean may drop at most 5 %. Before, any one small, noisy test moving by 2 % rejected the whole model (v139 and v140). Safety checks (loads, generates, speed, memory, fair per-byte comparison across tokenizers) are unchanged.
- **Weight averaging.** When a cycle has two or more candidates trained from the same model, their weights are averaged and the average is judged by the same gates; it becomes the cycle's candidate only if it scores higher than every passed candidate.
- **Long runs finish.** When a cycle's time budget runs out, a successor or a run at least half done finishes (up to twice the budget) instead of being thrown away; experiment #8 lost about 10 hours this way.
- **Stopped successors keep their training.** The next successor of the same size continues from a stopped attempt's saved weights, not only from a rejected one's.
- Clean-up: 20 design and evidence notes of past versions and one unused app component removed.

## 1.0.15 — GPU work on a new successor is no longer thrown away

- Shared-round updates for a successor trained from scratch were refused as "update too large (relative norm 12.9 > 10.0)": some of its layers start with deliberately tiny weights, so a fast GPU's honest update is many times their size. Successor updates now have a much looser size limit; every round still has to lower the loss on held-out text, and non-finite updates are always refused.

## 1.0.14 — Every computer joins; Windows workers update themselves

- The "Use cloud workers" switch is gone: when it was off it silently left every cloud-type computer out of training, including worker "serv 1" and MOTH Cloud's own worker ("no other computer can hold it"). Every connected computer now always takes part; single workers can still be paused or removed in Network.
- Windows workers can update themselves: switching to a new version used symbolic links, which Windows only allows with administrator rights or Developer Mode, so updates failed and were retried with growing delays. Windows now uses small pointer files, restarts the worker as a fresh background process, and the restarted worker waits for the old one to exit.

## 1.0.13 — Workers always join

- A run training on MOTH Cloud alone moves to shared training with the workers at any point while it has at least 100 steps left (no percentage cut-off, no minimum number of rounds).
- A run that cannot be shared (private data) keeps MOTH Cloud, and the idle workers train other experiments of the cycle instead of waiting.

## 1.0.12 — Usage ring, 5-hour and weekly limits, Owner-only AI

- Usage limits like Claude's: every plan has a rolling 5-hour and a rolling weekly allowance (Free 20k / 80k tokens, Pro 250k / 1.25M, Max 1M / 5M), on top of the monthly allowance. When one is reached, chat continues with credits or when it frees up, and the message says which limit and when.
- Usage ring next to the chat box: how much of the plan is used, in percent (never tokens). Click it for the 5-hour and weekly percentages and when each frees up. The Owner is unlimited.
- Security: the AI section (MOTH's training, data, models and their controls) is Owner-only. It is hidden from other accounts' menu, search and shortcut, and does not open for them even if opened directly; the Home screen's live-training link is Owner-only too. MOTH Cloud already refuses that data to non-Owners.

## 1.0.11 — No worker is left out

- A worker whose job was taken back before it made progress got a speed of about 0 tokens/s recorded, and placement then never gave it work again, so it could never be measured again (worker #9: "0.0× this server's speed", no finished runs). A take-back without progress no longer records a speed, near-zero readings are ignored (the worker is judged by its hardware benchmark until its next real job), and existing near-zero readings are cleared automatically.

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
- Measured: see docs/COGNITIVE-EVOLUTION.md.

## 0.7.2 — The whole network works on MOTH

- Workers prepare data: dataset chunks are tokenized and hashed on workers; MOTH Cloud re-encodes sample records of every chunk and refuses any mismatch, takes unclaimed or late chunks itself, and removes exact duplicates when merging (the result is byte-identical to preparing everything on MOTH Cloud). Feedback data never leaves MOTH Cloud.
- MOTH Cloud trains together with the workers: the server enrolls its own built-in worker ("MOTH Cloud server") and joins distributed training rounds, data preparation and evaluations under the same verification. It pauses during its own local experiments and follows AI Settings → What trains MOTH.
- Evolution stops repeating what does not work: a strategy with 4+ runs and no accepted improvement is suspended while another strategy is producing improvements.
- New verified synthetic sources: reasoning (sequences, orderings, multi-step problems) and language (plurals, opposites, alphabetical order, word counts, sentence casing).
- Interface: view and tab transitions, skeleton loading states, consistent button press and focus feedback (reduced motion respected).
- Details: docs/GENESIS-ASCENSION.md.

## 0.7.1 — GENESIS ASCENSION, continued

- AI → Model: the active MOTH model in one place: an animated core drawn from its real layers and heads, verified parameters, architecture, checkpoint, tokenizer, deployment, held-out capabilities compared with the rollback model, lifecycle and compact history. The numbered-circle diagram and the separate Cloud model registry section are gone (the registry API stays).
- Minimum monitored requests is 0 (migrated once): zero user traffic never blocks a promotion; health checks are the evidence.
- One active + one rollback model, shown in the Model tab; older packages are removed after each verified promotion.
- Owner-only notifications, enforced by the server, with a bell for the Owner.
- AI Settings → What trains MOTH: MOTH Cloud server, workers and this computer, in any combination.
- Workers update at once: the heartbeat announces new worker releases, every worker gets them immediately, failed installs back off.
- Updaters: the cloud agent uses conditional GitHub requests and respects rate limits; the desktop checks hourly and treats a staged rollout as a wait.
- Details and limitations: docs/GENESIS-ASCENSION.md.

## 0.7.0 — GENESIS ASCENSION

- One model identity: MOTH 0.0.1, 0.0.2, … — the public version advances only on verified upgrades; earlier labels are renumbered once without touching weights; the active version is shown in every section.
- Incoherent replies are diagnosed from the model's own output (tokenizer, decoding or training); a tokenizer problem blocks growth.
- Verified synthetic foundation data: arithmetic, simple instructions and Python functions, each checked before use.
- AI page: compact MOTH Intelligence panel; the architecture diagram moved to AI Settings → Advanced → Model Architecture.
- Self-repair: a training process that stops advancing is restarted from its last checkpoint.
- Details and limitations: docs/GENESIS-ASCENSION.md.

## 0.6.4 — One computing network

- One computing network: MOTH Workers 0.6.4 now train conversation data too (the loss mask travels with the job), placement follows measured speed, untaken work moves back to MOTH Cloud, and AI → Evolution shows every machine. The manual Training Jobs controls are retired.
- Fixed a MOTH Worker restart loop after a second automatic update.
- Details: docs/DISTRIBUTED-EVOLUTION.md.

## 0.6.3 — DISTRIBUTED EVOLUTION

- Parallel experiments: while one experiment trains, free compute (MOTH Cloud or an online worker) starts the next one. Measured 1.23× faster on one shared 4-core machine.
- Evolution 2.0: remembers which strategies and data mixtures improved held-out results and runs the promising ones first; grows its data when the model has outgrown it.
- Automatic promotion verifies health even when cloud answering is off, keeps the previous working model for rollback and removes older versions' files.
- Three more licensed coding datasets (Magicoder OSS-Instruct, CodeFeedback, Glaive Code Assistant) with pinned checksums; streaming JSON parsing.
- Evolution command center: objective, active and rollback models, parallel experiments, workers and their tasks, and what is holding progress back — from server records only.
- Continuous evolution: rounds run back to back with no timer; only a failed round waits briefly before retrying.
- Every parameter count is counted from the saved weights; older releases are measured automatically and the app says when a count is verified.
- Capability-based growth: MOTH grows its architecture only when measured capabilities (arithmetic, reasoning, coding, instruction following, language) stall and other causes are ruled out; larger candidates must improve those capabilities before they are kept.
- Details and limitations: docs/DISTRIBUTED-EVOLUTION.md.

## 0.6.2 — AUTONOMOUS GENESIS

- Five sections: Chat, Projects, AI, Network, Settings. AI holds Evolution, Data, History and AI Settings.
- Chats: rename, delete one, delete selected, clear all; optional automatic retention (off by default).
- Start Evolution: one click creates the first model if needed, selects trusted coding-first data, prepares it and keeps MOTH improving within your budget. Pause at any time.
- The Evolution Engine adapts steps, learning rate, batch size and pace from measured results and explains every change.
- Live training telemetry (compute, memory, workers, losses, speed, elapsed, honest remaining time) and a live activity stream of what the engine did.
- Credentials are removed from all training data; Dataset Quality Studio reports them.
- AI Settings in plain words; storage view and safe cleanup on MOTH Cloud.
- Details: docs/AUTONOMOUS-GENESIS.md.

## 0.6.1 — Genesis Reset, fresh genesis and growth clarity

- Genesis Reset moved to Settings → Advanced: review the real deletion inventory, type `RESET GENESIS`, confirm once more. MOTH Cloud still accepts the phrase the published 0.6.0 desktop sends. Optionally also deletes the native AI data stored on this computer.
- "No Model — Ready for Genesis": a guided fresh start with a choice of tokenizer and model size (real parameter counts from the server) replaces the empty Overview.
- Model size and growth: plain explanation of why the parameter count is unchanged, the planner's evidence, and an Owner-requested growth experiment that is evaluated like any other candidate.
- Gated Hugging Face datasets no longer fail as "not found": the message says the dataset is gated and how to get access.
- Interface: no-model states say what to do next; Network no longer repeats its switch and heading; Project Intelligence and Dataset Quality Studio use the app's controls; History states a single measurement instead of drawing an empty chart.
- Details: docs/GENESIS-RESET.md.

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

Normal updates preserve existing data. Reset testing is isolated only. Foundation training completion and physical GPU execution are not claimed. Phase evidence and limits: LIVING-INTELLIGENCE.

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

**EVOLUTION 2.0** (docs/EVOLUTION2.md)
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
ASCENSION releases (see docs/ASCENSION.md).

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
