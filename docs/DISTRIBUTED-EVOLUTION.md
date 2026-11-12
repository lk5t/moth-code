# Distributed Evolution (0.6.3)

What changed in 0.6.3, how it behaves, and what was — and was not — verified.

## Parallel experiments across compute

- When an experiment is running and more compute is free, the Evolution Engine starts the next
  planned experiment instead of waiting (`parallel_experiments`, on by default). MOTH Cloud runs one
  local experiment at a time; each online MOTH worker with enough memory takes one more. Sharded
  (distributed) training still uses all workers for one experiment and is not combined with parallel
  runs. The activity feed records it as **Running in parallel**.
- Worker jobs keep their 0.6.2 protections: consent and pause by the worker's owner, resource limits,
  leases that expire and are reassigned, checkpoint resume, checksum-verified artifacts, and results
  only accepted from the worker the job was assigned to.
- Measured (one 4-core Linux machine, a real worker thread sharing the same CPU, two 200-step tiny
  experiments): parallel 17.4 s vs. sequential 21.4 s, 1.23× faster
  (`server/tests/test_parallel_v063.py`). Separate machines should gain more; that was **not**
  measured here, and no GPU or multi-machine run was verified.

## Evolution 2.0

- **Strategy memory**: each experiment records its strategy (weakness-tilted or balanced mixture).
  Once two strategies each have at least two finished runs, the one with the higher pass rate and mean
  improvement runs first, with the reason shown under "Why MOTH changed its plan".
- **Data effects**: after at least four finished experiments, mixture weights move (bounded ±30%)
  toward the data categories whose share correlated with measured held-out improvement.
- **Data scaling**: when a model has trained on three times the prepared training tokens, the source
  budget doubles (up to 64 M characters per source) and data is prepared again.
- **Automatic promotion**: a candidate that passes every gate is served to a share of users, monitored
  for the configured window, then promoted. If MOTH Cloud answering is off, no user request can arrive,
  so the promotion requires at least three passing health checks across the whole window instead
  (event **Health verified**). Any failing check rolls back; the previous model never stops serving
  during a staged rollout.
- **Retention**: after a promotion passes monitoring, MOTH keeps the active model and the previous
  working model (rollback target) and removes files of older versions and unchosen candidates. Their
  records stay as history. Versions serving users or used by active work are never removed. The
  Evolution setting `retention.models` (Owner settings API; default 2, 0 keeps everything) controls it;
  it is deliberately not shown in AI Settings.

## Dataset factory

- Three more licensed coding sources with pinned revisions and SHA-256 checksums: Magicoder
  OSS-Instruct 75K (MIT), CodeFeedback Filtered Instruction (Apache-2.0) and Glaive Code Assistant
  (Apache-2.0). Real downloads parsed 75,197 / 156,525 / 136,108 records.
- Large JSON files are parsed as a stream. Downloads are cached by checksum and not repeated. The
  automatic download limit grows with free disk (5%, between 256 MB and 20 GB).
- The custom safety dataset and its configuration are untouched.

## Command center (AI → Evolution)

The Evolution card shows the current objective, the active and previous (rollback) model, experiments
running in parallel and jobs waiting for a worker, enrolled workers with their measured compute and
current task, and the single thing currently holding progress back. All values come from server
records; nothing is estimated or simulated.

## Continuous evolution

Rounds run back to back: as soon as one ends (promoted, rejected or nothing to promote), the next is
planned and started — there is no timer between rounds and no slowdown after rounds without an
accepted improvement. Repetition is avoided by the plan itself (configurations already tried are
skipped; the capability assessment below changes data, training or architecture when progress
stalls). Two waits remain, both visible in the app: a failed round is retried after 1, 2, 4 or 8
minutes (and Evolution pauses itself after the configured number of failures in a row), and when
there is nothing to train yet (for example while data is prepared) MOTH looks again within a minute.
The Owner's resource budget (compute hours per day) still applies.

## Real parameter counts

Every displayed parameter count is counted from the saved weights: package inspection maps the
tensors in `model.pt` onto the architecture and adds each learnable parameter once (a tied
embedding/output weight is one parameter; buffers are not parameters). Registration records the
result (`params_measured`: total, trainable, source) and rejects a package whose weights disagree
with its manifest. Releases registered before 0.6.3 are measured by the engine in the background; a
registry value that differed is replaced and an activity event says so. The app says "counted from
the saved weights" only for measured counts.

The ~5.2M shown on a deployment created with the Genesis "Small" size and the byte tokenizer is
real: that architecture has 5,184,768 parameters with a 272-token vocabulary. It stays the same
across versions because continued training changes weights, not size.

## Capability-based growth

The decision to grow is made from measured intelligence, not a single loss threshold
(`evolution/capacity.py`). Each round assesses arithmetic, reasoning, coding, instruction following
and held-out language / conversation / knowledge loss over the last three measured versions, plus
training progress, tokens trained per parameter, data per domain and available compute. It checks,
in order: overfitting, too little training for the size, replies that never end (a format problem),
too little data for a stalled capability, the tokenizer (reported only), and only then capacity.
The outcome is one of continue training, improve data, adjust training, foundation training or grow,
shown in AI → Evolution ("Intelligence check") and the activity feed in plain language.

A larger candidate keeps the existing weights (function-preserving expansion), is trained on the same
data on whatever authorized compute has the memory, and must beat the current model on the same
benchmarks — including improving a capability that motivated it beyond sampling noise. Otherwise it
is discarded ("Larger model did not improve performance enough. Keeping the current version.").
Growth respects the parameter ceiling and step limit, never runs while another growth candidate is
in progress, waits three rounds after a rejection, and pauses after three rejections in 20 rounds.

## One computing network (MOTH Cloud + workers)

Start Evolution coordinates every authorized machine; there is no separate training-job workflow.

- **Why workers sat idle before.** The automatic data library always includes conversation data, which
  trains only on the assistant's replies (a loss mask). Worker jobs carried tokens only, so every
  experiment on such a mixture was kept on MOTH Cloud ("local · cpu"). Also, MOTH Cloud's own CPU was
  always chosen before any CPU worker.
- **Masks travel with the job.** A worker job now carries its shard's loss mask (SHA-256 checked,
  served only to the worker holding the lease), and the worker trains and reports losses with it — the
  same alignment as training on MOTH Cloud. Only workers 0.6.3 or newer may claim such a job; older
  workers never get it. Private (user-contributed) data still never leaves MOTH Cloud. Sharded rounds
  (one experiment split across many workers) still carry tokens only and are used only for unmasked data.
- **Placement by measured speed.** Each machine's real end-to-end throughput (tokens/s, including
  downloads and uploads for workers) is recorded after every run; until then the hardware benchmark is
  used, discounted 20 % for network transfers. A worker at least 0.8× as fast as MOTH Cloud takes work
  first (MOTH Cloud stays responsive); while MOTH Cloud trains, a parallel experiment goes to a free
  worker only if it is at least 0.5× as fast — slower, the cycle would take longer than running it here
  afterwards. Busy and incompatible workers are not counted as free capacity.
- **Recovery.** A disconnected worker's lease expires and its job is requeued; if no worker takes it
  within 10 minutes it is cancelled and the experiment continues on MOTH Cloud. Results are accepted
  only for the worker holding the lease, so a returning worker cannot upload a duplicate.
- **Live view.** AI → Evolution lists MOTH Cloud and every worker with ID, state (working / online,
  idle / unavailable), current experiment and progress, CPU and memory use, speed relative to MOTH
  Cloud, measured throughput, finished runs and tokens trained, and the last problem of the past day.
- **Measured (one 4-core machine, real worker loop sharing the CPU):** the same two-experiment cycle
  (245,760 tokens) took 19.6 s on MOTH Cloud alone and 10.4 s with the worker — 1.88× faster. A cycle
  on conversation data trained one experiment on MOTH Cloud and one on the worker at the same time,
  with the worker applying the loss mask (`server/tests/test_network_v063.py`).
- **Worker auto-update loop fixed.** After a worker had already updated once, the restart after the next
  update inherited the previous version's environment and started the old version again, which
  re-installed the same update and restarted. Restarts now start from the original environment, so the
  newest installed version runs (`server/tests/test_worker_restart_v063.py`).

## Limitations

- Dataset preparation and tokenization run on MOTH Cloud, not on workers.
- Sharded (multi-worker) training of one experiment is token-only; conversation data uses whole-experiment worker jobs.
- The production Worker #8 could not be reached from the development environment; its behaviour was
  reproduced with a real worker process against an isolated MOTH Cloud.
- GPU training, multi-GPU and multi-machine speedups were not verified in this environment (no GPU).
- The parallel speedup above was measured on a single shared-CPU machine.
- A lower loss alone is never treated as proof of capability: promotion needs held-out evaluation
  gates and monitoring.
- Capability benchmarks are small, fixed held-out sets (e.g. 100 GSM8K problems); differences within
  sampling noise are treated as no change. Reply-failure reasons are recorded for versions benchmarked
  with 0.6.3 or later.
- Changing the tokenizer is never automatic; it needs a new Genesis.
