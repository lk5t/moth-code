# Genesis Reset, fresh genesis and model growth

Follow-up to the published 0.6.0. Nothing here has been published; nothing here was run against a
production deployment. Destructive behaviour was exercised only on temporary test deployments.

## Genesis Reset

**Where:** Settings → Advanced → Genesis Reset. Owner only; other accounts do not see the section and
the server refuses them (403) regardless of what a client sends.

**What the Owner does**

1. *Review deletion.* Requires the password again. The server counts the real files and records it
   will delete and returns that inventory. Nothing is deleted. The review expires after 10 minutes.
2. *Type `RESET GENESIS`.* Including managed backups needs a second phrase, `DELETE MANAGED AI BACKUPS`.
3. *Final confirmation.* A dialog repeats the counts and the deployment address; only
   "Delete everything and reset" sends the request.

The server checks Owner role, recent re-authentication, the reviewed plan and the phrase itself. It
accepts `RESET GENESIS` and, so the published 0.6.0 desktop keeps working, the original
`DELETE ALL NATIVE AI DATA`.

**Deleted:** every native model (active, previous, candidate, archived), weights and packages,
architecture revisions, checkpoints and optimizer states, imported and prepared datasets, custom
tokenizers, training history and metrics, evolution experiments and cycles, evaluations and benchmark
results, promotion and rollback records, model-specific worker assignments, training caches and
temporary files, and any pending growth request.

**Kept:** accounts, sign-in and credentials, security keys and configuration, billing, plans and
referrals, conversations, projects and source files, general settings, worker enrolments and consent,
the applications themselves.

**Order of operations:** training and serving are fenced off first, worker assignments are revoked and
workers are told to delete their cached copies; then files and records are deleted; then the server
verifies that nothing remains. An interrupted reset stays fenced and can be continued. Deleting one
selected model is a different, ordinary action (Intelligence → Advanced).

**What cannot be deleted, and is disclosed:** managed backups unless explicitly included; copies outside
MOTH's storage (exported packages, infrastructure snapshots, published release archives); caches on
workers that are offline — the result lists workers that have not yet confirmed cleanup.

**This computer:** the desktop app can also delete the native AI data it stored locally (local models,
checkpoints, datasets, tokenizers, training tables) when the Owner ticks that box during the review.
It refuses while a local training job is running. Projects, conversations and settings are untouched.

## After the reset: No Model — Ready for Genesis

Overview (and Intelligence → Overview) shows a guide instead of an empty page:

1. *Data and tokenizer* — byte-level needs nothing. To use a tokenizer trained from data, prepare the
   dataset library first (Data), then return.
2. *Model size* — Seed (99,648 parameters with the byte tokenizer), Small (about 5.2M) or Foundation
   (about 41M). The numbers are computed by the server for the chosen tokenizer, together with the
   memory needed to train and whether this deployment can train it.
3. *Create the model* — random, untrained weights, load- and generation-checked, then made active.
4. *Train* — opens Intelligence → Training.

Old clients that send no choice still get the original seed.

## Why the parameter count did not change

Findings from the code and from the public status of the production deployment (its growth history is
Owner-only and was not inspected):

1. **Does growth exist?** Yes: `backend/moth/model/growth.py` (function-preserving deepening and
   widening) and the planner in `server/moth_server/evolution/v2.py`.
2. **Is it enabled?** Yes by default (`growth.enabled`).
3. **Is growth technically supported for this model?** Yes. From the 99,648-parameter seed the valid
   steps are 124,224 (+25%), 140,736 (+41%, needs approval) and 148,800.
4. **Why did it not happen?** Growth is proposed only after three consecutive completed cycles that
   each improve the held-out result by less than 1% without overfitting. A very small model that is
   still learning keeps improving by more than that, so no plateau is recorded and nothing is proposed.
   Ordinary training never changes the count — it changes the weights.
5. **Is the displayed count correct?** Yes. Production reports 99,648, which is exactly the seed
   architecture (2 layers, width 64, byte tokenizer); a test now counts the tensors of a deployed model
   and compares them with the displayed number.
6. **What changed?** Nothing was inflated. Intelligence → Advanced → *Model size and growth* now explains
   this in plain words, shows the evidence the planner sees, and lets the Owner request one growth
   experiment. It is an ordinary candidate: it is trained, must pass every gate against the deployed
   model, and is discarded otherwise. A larger starting size can be chosen at genesis.

## Dataset preparation failure ("all-v1")

Reproduced against Hugging Face: TinyStories and WikiText-103 prepare correctly; *The Stack (smol)* is
gated, and Hugging Face answers "not found" to requests that are not signed in. Selecting every
catalogue source therefore failed with a misleading "repository … is unavailable". The message now
says the dataset is gated, how to accept its terms and sign in (`HF_TOKEN` or `hf auth login`), and
that the source can be removed to prepare the others. A token cannot be entered in the app yet.

## Verification

- Server: `tests/test_genesis_v061.py` (phrase, legacy phrase, non-owner refusal, chosen size after a
  reset, deployed tensor count equals displayed count, library-tokenizer genesis, Owner-requested growth
  as a gated candidate), with the existing `test_native_reset.py`.
- Desktop backend: local reset deletes only native AI data.
- App: review → phrase → final confirmation flow, cancel paths, legacy-server phrase, empty state.
- End to end in a browser against a temporary deployment: reset, verified empty state, Begin Genesis,
  model created, Training opened.
- `scripts/test-genesis-desktop.py` (native Windows, run by the release workflow) follows the new
  controls; it has not run since the change — it runs in CI on Windows.
