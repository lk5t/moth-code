# MOTH Code 0.8.0 — COGNITIVE EVOLUTION

0.8.0 points MOTH's autonomous evolution at its two priorities, **conversation** and **coding**, and makes
progress on both measurable. Code changes do not make the model smarter by themselves: training does.
This release adds the data, curricula, benchmarks and promotion rules that steer training there, and
reports what was measured.

## Phase 1 — Conversation intelligence

* **Verified multi-turn conversations** (`moth/datafactory/dialogue.py`, source `synthetic-dialogue`,
  30,000): conversations whose last answer depends on earlier turns — remembering a stated fact (also
  across an unrelated turn), corrections, list recall by position, arithmetic follow-ups on the previous
  answer, a clarifying question for an ambiguous request, "I don't know" for facts never given,
  greetings and numbered-list formats. Every answer is re-derived from the earlier messages before use.
* **Conversation filters** (`clean.conversation_issue`): roles must alternate, no repeated replies, no
  looping replies.
* **Benchmark** (`capability:dialogue:builtin`, 48 conversations): scored per skill, plus context
  retention, end-of-turn and repetition. Its names, cities, items, colours and foods are **disjoint**
  from the training lists (tested), so answers cannot be memorised.

## Phase 2 — Coding intelligence

* **Verified coding curriculum** (`moth/datafactory/coding.py`): debugging exercises (a planted bug
  that parses but fails the function's tests; the fix passes them), code explanations with an example
  computed by running the function, and test writing whose assertions are executed.
* **Benchmarks**: `capability:codegen:builtin` (write the function) and `capability:debugging:builtin`
  (fix a planted bug), ten held-out functions each that never appear in training. Replies are executed
  in a separate Python process with CPU, memory and file-size limits; a task counts only when every
  test passes. Python only for now: other languages are not executed.

## Phase 3 — Autonomous Evolution 4.0

* The steady-state curriculum starts at **50 % conversation, 40 % coding, 10 % other** foundations.
  Measured weaknesses still shift it (a weak capability gets up to 2.5× more weight), replay floors
  protect what was learned and repetition caps apply.
* The new benchmarks are evaluation suites with weakness targets (`dialogue` 70 %, `codegen` and
  `debugging` 30 %), so Evolution aims training at whichever is weakest.
* A new **balanced_capabilities** gate: a candidate is rejected when the mean change of its
  conversation group (multi-turn, instruction following, conversation held-out loss) or coding group
  (code generation, debugging, MBPP, code held-out loss) is worse than the task tolerance — a better
  loss elsewhere never hides a regression. Per-suite gates, monitoring and rollback are unchanged.
* On start, installations whose Evolution already uses MOTH's generated data adopt the new generated
  sources once (Owner choices afterwards stand); the next automatic preparation builds them.
* The distributed network (MOTH Cloud's built-in worker, external workers, data preparation and
  evaluation on workers) from 0.7.x is unchanged.

## Phase 4 — Knowledge, research and workspace

* **Knowledge 2.0**: category (detected), project, confidence, verification, review date (possibly
  outdated flag) and near-duplicate detection for every document; reliable, current and same-project
  knowledge ranks first. Knowledge stays separate from the model weights.
* **Research Engine** (`POST /v1/research`, Settings → Intelligence → Research): extractive, cited
  reports over the knowledge the account may see, with corroborated vs single-source statements,
  numeric conflicts between sources and knowledge gaps. It does not browse the web and never presents
  statements as verified facts; reports can be saved as low-confidence research notes.
* Workspace: unchanged (explorer, editor, terminal, change diffs, approvals, project memory and test
  command detection already exist).

## Phase 5 — Benchmarking and performance

* **Benchmark history** in AI → Model: every promoted version's held-out results side by side, in
  priority order (conversation and coding first), with ▲/▼ against the previous version and the
  evaluation date. Candidates that were not promoted are not listed.
* **Serving performance**: when a model is loaded for serving, MOTH measures load time, generation
  speed and peak memory, and tries other CPU thread counts; one is kept only if it is at least 10 %
  faster **and** produces identical greedy output. Results are shown in the Model tab.

## Measured results (in this release's development environment)

On a locally trained 99,648-parameter MOTH model (MOTH 0.0.3 of the test lineage; production weights
were not available here):

| Benchmark | Result |
|---|---|
| Conversation (multi-turn, 48 held out) | 0 % |
| Code generation (10 held out, executed) | 0 % (0 % valid Python) |
| Debugging (10 held out, executed) | 0 % |
| Serving speed | 1,074 → 1,574 tokens/s (2 threads instead of the default, identical output, +46 %) |

A short check that the conversation curriculum moves the benchmark: 1,500 steps (about 45 s on CPU)
on the new conversation data alone took the held-out multi-turn pass rate from **0 % to 31 %** —
ending the turn 0 → 73 %, greetings and "I don't know" 100 %, numbered lists 33 %, arithmetic
follow-ups 17 % — but **context retention only 4 %**: a model this small does not learn to copy facts
from earlier turns quickly. That run was a measurement only; the production model is trained by
Evolution with the full curriculum and promoted only through the gates above.

## Limits

* The production model's results on the new benchmarks appear in AI → Model after its next evaluation;
  they were not available during development.
* Coding benchmarks execute Python only; other languages are trained on text but not executed.
* GPU and multi-machine performance were not measured on real hardware.


## 0.8.1 — Evolution never runs dry

**What happened.** Evolution never repeats a configuration on the same model. Once every planned
variant (curricula × learning rates) had been tried and rejected — for example after early stopping
with no held-out improvement — each new cycle found nothing to run and completed at once, so training
looked stopped.

**Fix.** When nothing new is left, Evolution explores (`v2._explore`): learning rates at ×0.5, ×2,
×0.25, ×4, ×0.7, ×1.4, ×0.125 and ×8 of the best known one, 1–3× the steps, the weakness-tilted and
balanced curricula in turn, and a fresh data sample; the exploration number is part of the
configuration, so nothing is repeated. The first time a model runs out of ideas, the data library is
also asked to grow. Exploration only creates candidates: the gates, monitoring and rollback decide.
If a cycle still cannot plan anything (no prepared data yet), the next attempt is 5 minutes later.

**Time estimates.** "Elapsed" used the experiment's first start time and the viewer's clock; a worker
experiment that waited in the queue showed hours although it had trained for minutes. MOTH Cloud now
sends `elapsed_seconds`, measured on its own clock from when a worker leased the job (or across the
local training sessions). "Remaining" still prefers the trainer's own measured rate.
