# MOTH 0.1 — Foundation (0.5.2)

**Verified status (2026-11-07):** the architecture and scratch-training pipeline exist, but this checkout
contains no trained Foundation checkpoint, split weights, or matching completed evaluation report.
Earlier corpus/run/release descriptions below are historical claims and have not been independently
verified. Foundation training must not be described as complete on this evidence. The short 49.3M
architecture smoke run in [CONTINUATION.md](CONTINUATION.md) is not a trained Foundation release.

MOTH 0.1 is the root of the one MOTH model lineage. Everything later (0.2, 0.3 …) continues these weights;
nothing restarts from random weights unless a new architecture is deliberately created.

## Model

| | |
| --- | --- |
| Architecture | decoder-only transformer (`moth-decoder-v1`): 12 layers, d_model 512, 8 heads, SwiGLU FFN 1536, RMSNorm, rotary positions, tied embeddings |
| Parameters | **49,295,872** (measured: `sum(p.numel())`) |
| Tokenizer | MOTH byte-level BPE, 16,384 tokens, trained on a balanced sample of the corpus (lossless; code-aware pre-tokenisation) |
| Context | 2,048 tokens (trained on 512-token windows) |
| Chat format | `<|system|> … <|user|> … <|assistant|> …<|end|>` — the loss is computed on assistant turns only |

## Data (approved dataset library, build `2d35066c…`)

35.2M training tokens after cleaning, deduplication and benchmark decontamination (details in
[INTELLIGENCE.md](INTELLIGENCE.md)): knowledge 18.1M (Simple English Wikipedia), language 9.9M (TinyStories),
code 2.5M (Python standard library, MBPP), conversation 2.4M (OpenAssistant, Dolly), maths 1.0M (GSM8K),
writing 0.9M and reasoning 0.4M (Dolly, ARC). Licenses: CDLA-Sharing-1.0, CC-BY-SA-3.0/4.0, Apache-2.0,
MIT, CC-BY-4.0, PSF-2.0 — attribution in every package's `ATTRIBUTION.md`.

The **foundation** curriculum stage mixes the domains (language 30%, knowledge 28%, code 14%, conversation
12%, maths 6%, writing 5%, reasoning 3%) with at most 4 passes over any small dataset.

## Training recipe (historical completed-run claim unverified)

`python scripts/train-moth-foundation.py --data DIR --steps 3000 --threads 3` — 3,000 steps × 16,384
tokens (batch 8 × accumulation 4 × 512) = 49M tokens, AdamW (β 0.9/0.95, weight decay 0.1), learning rate
1e-3 with warm-up and cosine decay to 1e-4, gradient clipping 1.0, bf16 autocast on CPUs with AMX.

Measured throughput on the 4-core build machine: 1,100–1,600 tokens/s (≈ 11 s per step), so the
foundation run takes about 10–12 hours. A GPU worker is roughly 20–50× faster.

## Persistence and integrity

* Every checkpoint holds the weights, the AdamW state, the data-sampler and RNG state, the step and the
  lineage counters; resuming continues exactly (no step is repeated or skipped).
* Checkpoints are written atomically and fsynced, with a SHA-256 sidecar; resuming verifies it and falls
  back to the newest intact checkpoint (a damaged one is set aside, never trained on).
* Retention: the newest three checkpoints, milestones (`keep_every`) and `best.pt`.
* One trainer per run directory (an OS-level lock that disappears when a process dies).

## Evaluation and release criteria

`python scripts/evaluate-model.py --package DIR --eval-dir EVAL --out report.json` runs the capability
benchmarks on held-out data (maths, reasoning, executed code, instruction following, held-out loss per
domain, safety, generation speed on one CPU thread) and checks the release criteria
(`moth/model/release_criteria.py`), fixed before the training finished:

| Criterion | Threshold |
| --- | --- |
| Held-out language loss | ≤ 2.6 nats/token |
| Held-out conversation loss (assistant turns) | ≤ 4.0 |
| Held-out knowledge loss | ≤ 4.2 |
| Well-formed replies to new prompts | ≥ 50% |
| ARC-Easy accuracy | ≥ 25% (chance) |
| Harmful requests refused by the serving pipeline | ≥ 90% |
| Generation speed, 1 CPU thread | ≥ 5 tokens/s |

The model-release workflow re-runs the evaluation itself and refuses to publish if a criterion fails.

## Delivery

An official model release is a signed `kind: model` release (`model-v0.1`): the package archive and a
manifest signed with the MOTH release key, carrying the evaluation report. MOTH Cloud's update agent
downloads it, verifies the signature and SHA-256, hands it to the server, which verifies both again,
imports it once, evaluates it and deploys it (`auto_deploy_official_models`). MOTH Code can download the
deployed model (signature and SHA-256 verified) and answer on the computer.

## Results

No trained Foundation quality result was verified in this continuation. See
[CONTINUATION.md](CONTINUATION.md) for actual tests and remaining model-quality requirements.

## Safe preparation and resume

With approved catalog datasets available, prepare without starting training:

```bash
python scripts/train-moth-foundation.py --data /path/to/new-foundation-data --prepare-only
```

Then run the same command without `--prepare-only`, choosing `--device cpu` or `--device cuda` and
appropriate `--threads`, `--batch-size`, `--grad-accum` and `--steps`. Batch probing is enabled;
`--no-batch-autotune` keeps the configured microbatch. Reuse the same data directory to resume.
An existing tokenizer, approved build, replay mixture and lineage are retained. Incompatible metadata
or a run with no intact resumable checkpoint causes an explicit error, never a silent random restart.
Do not repurpose an existing run directory for another corpus or tokenizer.

Development-only checks may use `--sources python-stdlib --max-source-chars 20000 --preset moth-tiny
--vocab-size 320`; such a subset is not a complete Foundation corpus or quality evaluation.
