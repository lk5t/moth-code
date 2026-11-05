# Verified test results — v0.1.0

Everything below was actually run. Commands are listed so the results can be reproduced.

## Automated suites (development environment: Linux x86-64, 4 CPU threads, no GPU, Python 3.13, PyTorch 2.15 CPU)

| Suite | Command | Result |
| --- | --- | --- |
| Backend (pytest) | `cd backend && python -m pytest -q` | **103 passed, 0 failed** |
| Frontend (Vitest) | `cd app && npm test` | **13 passed** |
| Frontend typecheck | `cd app && npm run typecheck` | passed |
| Frontend production build | `cd app && npm run build` | passed |
| Rust shell | `cargo test --manifest-path app/src-tauri/Cargo.toml` | **2 passed** |

## GitHub Actions CI (run 2, commit `c24a67c`)

| Job | Result |
| --- | --- |
| Backend tests (ubuntu-latest, Python 3.12) | passed |
| Backend tests (windows-latest, Python 3.12) | passed |
| Frontend typecheck, tests and build | passed |
| Desktop shell (ubuntu-latest) | passed |
| Desktop shell (windows-latest) | see the Actions page for the latest status |

The first CI run (commit `1e5e744`) failed on Windows. It exposed real bugs that the Linux suite could not catch:

- PowerShell needs `&` to run a command that starts with a quoted path.
- PowerShell didn't propagate exit codes.
- `edit_file` couldn't match text in CRLF files.
- The CLI crashed writing UTF-8 to a cp1252 console.

All four were fixed and covered by tests. On Linux, one flaky assertion was replaced by a deterministic comparison.

## What the backend tests cover

| Area | Highlights |
| --- | --- |
| Model | Analytic and real parameter counts match (MOTH-50M = 49,295,872 parameters); causality; KV-cache decoding equals full recomputation; grouped-query attention; deterministic greedy generation; cancellation. |
| Training genuinely updates weights | After one backward pass and AdamW step, **every** parameter tensor has changed and all gradients are finite. |
| Learning | On a synthetic corpus, the final train loss is under 60% of the initial loss, and validation loss decreases. |
| Resume | A run stopped at step 12 and resumed to step 30 produces **bit-identical weights** to an uninterrupted 30-step run (deterministic algorithms enabled). |
| Checkpoints / export | Best and latest checkpoints, atomic writes, rotation, STOP-file pause; export → load → evaluate; a corrupted model file is detected by checksum. |
| Tokenizer | Lossless round-trip on random Unicode; special-token handling with no injection from plain text; deterministic training; save/load fingerprints. |
| Data | License required for every source; validation split; chat loss masks; trusted vs untrusted special-token encoding. |
| CLI end to end | `tokenizer → prepare → train → export → generate` as real subprocesses. |
| API end to end | Tokenizer, dataset and training jobs through HTTP; concurrent-run refusal with no leftovers; export; load; streamed chat over WebSocket; evaluation job. |
| Agent | Real file edit plus a real pytest verification run; failed verification → `needs_review`; invalid model output → `model_incapable`; `give_up`; out-of-workspace denial; approval deny/approve for deletes; step limit; error memory recall; cancel, resume and revert; recovery after restart; context-budget trimming; **a genuine untrained MOTH network driving the loop is reported as incapable and changes nothing.** |
| Security | Workspace boundary and symlink escape; destructive, publish and network command classification; secret detection; approval broker; API token auth for HTTP and WebSocket. |
| Policy | No default restrictions; block/redact/warn; validation; persistence; credential redaction independent of policy. |
| Hybrid inference | Local-only without a model fails clearly; an unconfigured cloud is reported as not available; consent gates for chat and project data; auto prefers local; cloud output equals local output for the same model; secrets redacted before sending; non-MOTH servers refused; API key masked. |
| Community | Opt-in default, pause, schedule (including overnight windows), daily limits, clamped resource settings; validation rejects missing keys, bad shapes, NaN, oversized and empty updates; weighted FedAvg; two clients complete a round and aggregate into version 1 with lineage; checksum, stale-base and harmful (probe-loss) updates rejected; corrupted shard download detected; personal export uses only test-verified tasks. |
| Robustness | No CUDA / broken driver → CPU; hardware info never raises; corrupt model manifests reported; impossible training config fails cleanly with its error recorded; failing subsystem isolated. |
| Workspace | File ops; project scan; terminal streaming, exit codes, cancel (process tree), timeout, `cd` confinement; git status/diff/commit/log; CRLF-preserving edits; PowerShell wrapping. |

## Manual / integration verification

These were run in the development environment, not by the automated suites.

- **Real training run through the UI backend:**
  - Tokenizer `stdlib-4k`, trained on 3 MB of Python stdlib (PSF-2.0).
  - Dataset: 845,927 train and 6,908 validation tokens.
  - `moth-small` (6.16M parameters), 600 steps, seq 256 × batch 16, on CPU, at ~4.1K tokens/s.
  - Validation loss fell from ≈8.3 (random init) to **4.186**.
  - Exported, loaded and chatted with: 75 tokens/s on CPU. The output is Python-like text, as expected at this scale.
- **Agent with that model:** the task "Add a multiply function…" ended as `model_incapable` after three unusable
  outputs, with no file changes. That is the expected and honest result.
- **Desktop app launch (Linux, Xvfb):**
  - The Tauri shell started the backend with an ephemeral port, a token and its parent PID.
  - Unauthenticated API calls got 401.
  - The backend exited after the app was force-killed (within ~6.5 s).
- **Bundled backend:**
  - A PyInstaller build (~900 MB with CPU PyTorch) announced readiness and loaded all subsystems.
  - It ran a frozen generation, and a training job it launched as a frozen subprocess completed.
  - The Tauri app built with the release resource mapping launched the bundled backend from its resource
    directory.
- **UI:** browser screenshots against the real backend covered the workspace, editor, terminal (a typed command
  returned its output), chat streaming, agent report, training dashboard (live loss curve), models, community and
  settings.

## Not verified here

- Building or installing the Windows NSIS installer and the signed update flow. These run only in the release
  workflow, which needs a version tag and signing secrets.
- GPU (CUDA) training and inference. No GPU was available. The code paths are written for CUDA, and CPU fallback is
  tested.
- Training MOTH-50M to a useful quality level.
