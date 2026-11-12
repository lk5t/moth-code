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

## Limitations

- Dataset preparation and tokenization run on MOTH Cloud, not on workers.
- GPU training, multi-GPU and multi-machine speedups were not verified in this environment (no GPU).
- The parallel speedup above was measured on a single shared-CPU machine.
- A lower loss alone is never treated as proof of capability: promotion needs held-out evaluation
  gates and monitoring.
- Capability benchmarks are small, fixed held-out sets (e.g. 100 GSM8K problems); differences within
  sampling noise are treated as no change. Reply-failure reasons are recorded for versions benchmarked
  with 0.6.3 or later.
- Changing the tokenizer is never automatic; it needs a new Genesis.
