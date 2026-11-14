# Autonomous MOTH (0.9.0)

0.9.0 lets MOTH keep improving and keep running without the Owner. It grows its own training data,
teaches itself from checked problems and repairs common faults by itself. Every automatic decision
is recorded in the Evolution activity, and the safety rules are unchanged:

- a candidate is promoted only after the held-out gates;
- a failed deployment rolls back;
- private data never leaves MOTH Cloud;
- no Genesis Reset or deletion of user data ever happens automatically.

## Bigger data, added by MOTH

`backend/moth/datafactory/large_sources.py` lists 13 large sources: 242 files, about 90 GB. Each is
pinned by upstream revision, and each file by its size and SHA-256 (`scripts/pin-large-sources.py`
regenerates the list).

| Source | Domain | Licence | Size |
|---|---|---|---|
| Cosmopedia stories | language | Apache-2.0 | 11.9 GB |
| Cosmopedia textbooks (Khan Academy, OpenStax, Stanford, WikiHow seeds) | knowledge | Apache-2.0 | 4.2 GB |
| Cosmopedia maths | math | Apache-2.0 | 4.5 GB |
| Cosmopedia web-seeded articles | knowledge | Apache-2.0 | 32.7 GB |
| FineWeb-Edu (10B-token sample) | knowledge | ODC-By 1.0 | 28.5 GB |
| SmolTalk Magpie-Ultra conversations | conversation | Apache-2.0 | 1.4 GB |
| SmolTalk constraints, rewriting, summaries | writing | Apache-2.0 | 0.2 GB |
| SmolTalk self-instructed code | code | ODC-By 1.0 | 0.03 GB |
| OpenCoder code instructions (stage 2) | code | MIT | 0.5 GB |
| OpenCoder large-scale diverse code instructions | code | MIT | 3.5 GB |
| MetaMathQA | math | MIT | 0.4 GB |
| OpenAssistant oasst2 | conversation | Apache-2.0 | 0.05 GB |
| TinyStories (full training set) | language | CDLA-Sharing-1.0 | 2.2 GB |

Attribution for each source is carried into every model's `ATTRIBUTION.md`, as before.

**Shard by shard.**
- A sharded source downloads only the files its character budget needs (`catalog.shards_for`).
- A build stops reading a source once it has read enough for the budget. The holdout and training
  passes read the same records, so they stay disjoint.

**Growth.** When the lineage has trained on more than three times the prepared tokens (or when
Evolution finds the data too thin), `autopilot.scale_data`:

1. doubles each source's budget (`max_source_chars`, up to 2 billion characters per source);
2. adds the next source from `LADDER`:
   - first conversation and code, which follow the 50/40/10 focus;
   - then textbooks, maths, stories, FineWeb-Edu and web articles;
3. lets downloads use up to half of the free disk.

If a build would not fit on the disk, discovery halves the budget until it does, instead of stopping.

**What is never added.**
- An Owner-revoked source is never added again.
- A source without a verified licence is never added.
- `autonomous_sources: false` in the discovery policy turns automatic additions off.

**More generated data.** MOTH's verified generators produce more examples as the budget grows: about
one per 200 characters of budget. That is up to 2 million per generator, or 100,000 for generators
whose every example is executed.

## Self-training

`server/moth_server/intelligence/self_training.py` runs every hour while Evolution is on and a model
is serving.

**The quiz.**
- The model answers 40 fresh problems per kind: arithmetic, instructions, reasoning and language.
- Each problem gets a greedy answer and, if that is wrong, one sampled answer.
- Every answer is checked against the generator's answer key: the number, the name, the ordering or
  the requested text.

**What it keeps.** Both kinds of example are written to `self_training/records.jsonl` (at most 200,000)
and join the next data preparation as a CC0 source.
- A correct answer is kept as a self-verified example in MOTH's own words.
- A wrong answer is kept as a correction, with the generator's checked answer.

**Steering.** The pass rate per kind is MOTH's measured weakness on new problems. It ranks
capabilities that have no benchmark yet, and so steers the curriculum.

**Benchmarks are unaffected.** The held-out benchmarks never use these problems, so promotion still
measures real progress.

## Self-repair and diagnostics

`server/moth_server/evolution/supervisor.py` checks every minute for each problem below and applies
its fix.

| Problem | Fix |
|---|---|
| The Evolution loop has stopped | Start it again |
| The Evolution loop is alive but no round has finished for 30 minutes | Wake it and report it (a running round is never interrupted) |
| The model pipeline has stopped | Start it again |
| A model is deployed but none is serving | Load it, or the rollback model of the same model line |
| MOTH Cloud's built-in worker has stopped, or has been failing for 10 minutes | Start it again |
| Less free disk than the reserve | Safe cleanup (see below) |
| A cycle has not changed for 3 hours while nothing runs | Wake the engine |
| A data preparation has made no progress for 2 hours | Mark it failed so it is prepared again |

**Safe cleanup.**
- It removes finished run folders, superseded data preparations and rejected candidates first.
- It removes download caches only if space is still short.
- It never removes protected items.

**Recording and escalation.** Each repair is recorded in `supervisor_log` and as an event. A problem
repaired three times within an hour raises one `supervisor.attention` error event.

**Diagnostics page.** Settings → Advanced → Diagnostics (`GET /v1/admin/evolution/diagnostics`) shows:
- the loops;
- serving;
- the built-in worker;
- the disk;
- recent repairs;
- the last 200 server warnings and errors, redacted before they are kept.

"Check now" runs the checks at once. "Copy report" copies a plain-text summary.

## Resumable worker jobs

**Snapshots.**
- Evolution workers send a progress snapshot every 10 minutes and whenever they pause.
- A snapshot is the weight change so far, with its step and token counts, sent to
  `POST /v1/worker/jobs/{id}/snapshot`.
- MOTH Cloud checks it the same way it checks a final result (base checksum, payload checksum, shape
  and size bounds), then keeps the latest one.

**Take-back.** When a job is taken back:
1. the snapshot becomes `resume-base.pt`;
2. the experiment's remaining steps are reduced by the steps already done;
3. the next local or worker run starts from that point, and the job spec carries `resume_base`.

The candidate's step and token totals include the resumed part. Growth experiments always restart
from their verified grown base.

## Worker phases and honest status

**Worker phases.**
- Workers report what they are doing with each heartbeat: downloading the model, downloading the
  training data, loading the model, measuring the batch size, training, uploading the result.
- The live view shows the worker's reported step, tokens and loss.
- A take-back says where the worker was stuck.

**Health states.** `GET /cloud/v1/health` distinguishes:
- `model_loading`: a model is deployed but not loaded yet;
- `training_first_model`: Evolution is training a first model;
- `no_model_deployed`: nothing is deployed or training.

The desktop app shows these states. It retries one slow health answer before it reports MOTH Cloud
as unreachable.

## 0.10.0: successors that can win, cleaner replies, alerts

**Gates for bigger models.** Speed and memory used to be compared with the model being replaced (at most
25 % slower, 25 % more memory), which no model many times larger can meet. Growth and successor candidates
are now held to absolute limits: at least 15 tokens/s (`gates.min_tokens_per_second`) and at most half of
the server's memory. Same-size candidates keep the relative limits.

**Sizing by measurement.** `capacity.right_size` trains each candidate shape for a few steps on random
tokens (`moth.training.speed_probe`) and keeps the largest shape whose measured speed, plus the workers'
share, trains about 20 tokens per parameter in a day. The current shape is timed the same way, and since its
real training speed is known, the ratio calibrates every probe (a busy server measures low for all shapes
alike). Probes are cached for the day and never run while a successor trains.

**Context and tokenizer.** Successors use `max_seq_len` 1024 and train at up to 4× the usual sequence length
with a proportionally smaller batch. For a byte-level lineage, MOTH first prepares the library again with a new
8,192-token BPE tokenizer (`library.ensure_successor_tokenizer`; the successor waits while it runs, and keeps the
byte tokenizer if it fails). Held-out capability losses now also report bits per byte; when the candidate's
tokenizer differs from the base's, every held-out comparison uses bits per byte of the same text, and
token-level datasets of the old tokenizer are left out.

**Shared successors.** A successor is never given to a single worker. When shared rounds are possible it is
started first, split across MOTH Cloud and every online worker, from seeded initial weights generated on MOTH
Cloud, with a round every 1,000 steps; each round is still accepted only if the probe loss does not get worse.

**Replies.** `GenerationParams` gained `min_p`, `frequency_penalty`, `no_repeat_ngram`, `stop_loops` and
`soft_end`. Chat (`LocalInference.chat`) turns them on unless the request set them (`generation.chat_quality`);
benchmarks and tool calls are unchanged.

**Morning report and alerts.** `GET /v1/admin/evolution/morning-report?since=` summarises recorded events,
experiments, self-quiz results and the deployed model's answer to a fixed question (kept for "then vs now").
`GET /v1/admin/evolution/alerts?after=` returns promotions and problems after an event id (with a one-line
status for the tray); the desktop app polls it every minute and shows system notifications.

**Live writing sample.** At every evaluation the trainer writes the model's greedy answer to a fixed
question to `events.jsonl` (`kind: sample`); no random numbers are drawn, so training stays reproducible.
