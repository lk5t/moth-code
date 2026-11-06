# MOTH Cloud model evolution

MOTH Cloud can improve its own model: it continues training the deployed model on training data you
approved, evaluates every result against the model it would replace, deploys only candidates that are
better without losing anything, watches them in production and rolls back if they misbehave. Then it
plans the next cycle from what it learned. You can run it unattended once it is set up.

Owner Dashboard → **Evolution** shows and controls all of it.

## The cycle

```
approved training data ─► training memory ─► experiment planning ─► compute scheduling
  ─► continued training ─► evaluation ─► candidate promotion ─► deployment ─► monitoring ─► next cycle
```

| Step | What happens | Code |
| --- | --- | --- |
| Data | Only datasets you **approved** in Evolution → Training data are used. Each source needs a license. A dataset that contains user data needs your explicit confirmation that the users gave permission. MOTH never adds conversations, workspaces or credentials by itself, and secret-looking files (`.env`, keys, …) are skipped when a dataset is built. | `server/moth_server/evolution/datasets.py` |
| Memory | Every run is recorded with its reproducible configuration, dataset (by hash), results, regressions, resources, duration and lineage (which model came from which). Dataset contents are never stored or shown. | `evolution/memory.py` |
| Planning | New data first, then data tied to a measured weakness (something the model got worse at than its parent, or a low coding score). Learning rates that improved earlier experiments are tried first. An exact configuration that already ran is never repeated. | `evolution/planner.py` |
| Compute | A local GPU, an online MOTH GPU worker, or — only if you enable it — this server's CPU, and only if the estimated memory fits with your reserve. Otherwise the experiment **waits** and the dashboard says why; it is never shown as training. | `evolution/compute.py` |
| Training | Continued training from the deployed model's weights with its exact architecture (`moth.training.continue_run`), in a separate low-priority process with checkpoints. Pausing and resuming continue from the last checkpoint, including after a crash or server restart. On a worker, the existing worker software runs it as an `evolve_train` job. | `evolution/backends.py`, `backend/moth/training/continue_run.py` |
| Evaluation | The candidate and the current model run the same deterministic benchmarks (`moth.model.benchmark`). Promotion needs **every** gate: the existing release checks; a held-out improvement on the data it learned (≥ 0.5 %); no retained capability more than 2 % worse; coding (valid-Python completions) and any task suites you supplied not worse; speed and memory within limits. A lower training loss is never enough. | `evolution/evaluation.py` |
| Deployment | The existing deployment path: checksum, real inference health check, then an atomic switch. The previous model stays available. Deployment never needs a desktop reinstall or a server restart. | `moth_server/models.py` |
| Monitoring | For a configurable window (default 30 min), real health probes, plus the error rate and latency of real requests compared with the previous model. A problem rolls back to the previous stable model automatically. | `evolution/engine.py` |
| Next cycle | Scheduled after the configured interval (default 24 h). Failed cycles back off exponentially. After 3 failed cycles in a row, evolution pauses itself and tells you. | `evolution/engine.py` |

One cycle runs at a time, and its experiments train one after another. Everything is stored in the
database, so a cycle continues after a restart or an upgrade. The active model is never modified:
candidates are new versions.

### Continued training vs. a new architecture

Evolution only continues training a model with the same architecture and tokenizer as its data. A
dataset made for a different tokenizer is marked *needs migration* and is not used. Weights are never
loaded across architectures. Training a new architecture from scratch is off unless you enable
`allow_from_scratch`. Distillation-based migration is not implemented yet (see Limitations).

## Setting it up on the VPS

1. **Upgrade MOTH Cloud** to a release that includes evolution (0.4.0 or later). The update agent does
   this automatically, with a verified backup first. Upgrade the desktop app to 0.4.0 or later to get
   the Evolution tab.
2. **Deploy a model** (Owner Dashboard → AI models). Evolution continues training the deployed model.
3. **Add training data** in Evolution → Training data: a `.zip` or `.tar.gz` of code or text, or a
   single file, with its license. It is tokenized with the deployed model's tokenizer. Larger datasets
   can be prepared on the server with `moth prepare --tokenizer <the deployed model's tokenizer.json>` and registered with
   `POST /v1/admin/evolution/datasets/register`.
4. **Approve** the dataset. A cycle is planned at the next check.
5. **Compute**: this server has no GPU (check Evolution → Compute). Either:
   - enroll a MOTH worker with an NVIDIA GPU (Owner Dashboard → Workers). Experiments are then sent to
     it automatically; or
   - allow CPU training on the server (Evolution → Settings → *Allow CPU training on this server*),
     only if the model is small enough (see below). Training then runs only while MOTH Cloud is quiet,
     with the thread, memory and disk limits you set, and pauses with a checkpoint when it gets busy.

   Without either, experiments wait, and the dashboard says so.
6. Optional: add **benchmark task suites** (JSON Lines of `{"prompt", "answer"}`) for reasoning,
   instruction following or accuracy. Without them those capabilities are reported as *not measured*.

## Hardware requirements

Estimated memory for training (`compute.estimate_training_memory`): 16 bytes per parameter (weights,
gradients, AdamW moments) plus activations plus about 0.6 GB.

| Model | Parameters | Training memory (batch 8 × 256 tokens) | Where it is realistic |
| --- | --- | --- | --- |
| moth-tiny / moth-small | 0.1 M / 7 M | < 1 GB | CPU (measured: 1500 steps of moth-tiny in 18 s on 2 threads) |
| MOTH-50M | 49 M | about 3 GB | a GPU worker; CPU possible but slow (not measured here) |
| moth-150m / moth-400m | 150 M / 400 M | about 5–10 GB | a GPU worker |

Inference keeps running during training. On a CPU-only server, training yields to requests: it pauses
whenever a chat request is being answered or traffic is above the configured threshold.

## API

All under `/v1/admin/evolution` and Owner-only. Changing settings, data permissions, starting a cycle
or rolling back also needs a recent sign-in.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/status` | Active and stable model, current cycle with experiments and real progress, latest comparison, warnings |
| GET | `/resources` | CPU, RAM, disk, GPUs, workers, inference load, training time in the last 24 h |
| PUT | `/settings` | `{"changes": {...}}` (validated) |
| POST | `/pause`, `/resume`, `/run`, `/cancel` | Control |
| GET | `/cycles`, `/cycles/{id}`, `/experiments/{id}`, `/experiments/{id}/log`, `/events` | History and logs |
| GET | `/versions`; POST `/rollback` | Version history with lineage; switch to an earlier compatible version |
| GET/POST | `/datasets`, `/datasets/register`, `/datasets/{id}/approve`, `/datasets/{id}/revoke` | Training data |
| GET/POST | `/suites` | Benchmark task suites |

## Database

Schema 3 (migration 3, additive, applied automatically after the agent's verified backup):
`training_datasets`, `evolution_cycles`, `evolution_experiments`, `evaluation_reports`,
`model_lineage`, `evolution_events`. Existing releases get a lineage row recording their origin.
Nothing existing is changed or deleted. Settings and engine state are in `server_config`
(`evolution_settings`, `evolution_state`). Retention: evolution events older than `retention_days`
(default 180) are deleted. Model versions, lineage, evaluation reports and experiment records are kept.
