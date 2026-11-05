# Training MOTH models

Every MOTH model starts from random weights. This guide explains how to get from nothing to a usable MOTH-50M.

## 1. Choose licensed data

Each dataset source must carry a license you are allowed to train on. It is recorded in the dataset's `meta.json`
and in every exported model's `manifest.json`.

| Source | License | Size | Notes |
| --- | --- | --- | --- |
| `stdlib` (Python standard library) | PSF-2.0 | ~10 MB of code | No download. Great for smoke tests; far too small to train MOTH-50M well. |
| `hf:roneneldan/TinyStories` | CDLA-Sharing-1.0 | ~2 GB | Simple English. Needs `pip install datasets`. |
| `hf:Salesforce/wikitext` (wikitext-103) | CC-BY-SA-3.0 | ~500 MB | English. Share-alike obligations apply. |
| `hf:bigcode/the-stack-smol` | permissive per-file licenses (gated) | ~1 GB | Accept the terms on Hugging Face first. |
| `dir:<folder>` | you declare it | — | Your own code, or code under a license that allows training. |
| `jsonl:<file>` | you declare it | — | `{"text": …}` or `{"messages": […]}` (instruction / agent data). |

## 2. Tokenizer

**Training → Tokenizer → New.** A 16,384-token vocabulary matches the MOTH-50M preset. The tokenizer learns from up to
`max_mb` of text (default 200 MB), using a mix that represents your target data (code and English).

Command line:

```bash
moth tokenizer --source stdlib --source "{\"spec\":\"hf:roneneldan/TinyStories\",\"license\":\"CDLA-Sharing-1.0\"}" --vocab-size 16384 --out tok.json
```

## 3. Dataset

**Training → Dataset → New** tokenises the sources into memory-mapped `train.bin`/`val.bin` with loss masks. About
2% of documents are held out for validation, chosen by a stable hash.

## 4. Train

**Training → Training runs → New**, preset `moth-50m`. The defaults suit a single consumer GPU:

| Setting | Default | Notes |
| --- | --- | --- |
| seq_len | 1024 | up to 2048 for MOTH-50M |
| batch_size × grad_accum | 8 × 4 | ≈ 32K tokens per optimizer step |
| lr / min_lr | 6e-4 / 6e-5 | cosine schedule, 500 warm-up steps |
| max_steps | 20,000 | ≈ 655M tokens |
| precision | auto | bf16 on GPUs that support it, else fp16 with loss scaling; fp32 on CPU |

**How much compute?** These are estimates, not measurements. Training costs about 6 × parameters × tokens FLOPs, so
MOTH-50M on 655M tokens is roughly 2 × 10¹⁷ FLOPs: on the order of a few hours on a recent high-end GPU, and well
over half a day on a mid-range one. A common rule of thumb is ~20 tokens per parameter (≈1B tokens for 50M
parameters), so more data and more steps keep helping. CPU training of MOTH-50M is impractically slow; use
`moth-small` for CPU experiments.

**Measured reference (from this repository's development environment, 4 CPU threads, no GPU):** `moth-small`
(6.2M parameters with a 4K vocabulary) trained on 852K tokens of Python stdlib for 600 steps (seq 256, batch 16) in
about 10 minutes at ~4.1K tokens/s. Validation loss went from ~8.3 to 4.19. The resulting model produces
Python-flavoured text but cannot follow instructions or use tools. That is expected at this scale.

**Pause / resume.** "Pause & checkpoint" stops after the current step and saves everything: model, optimizer,
loss-scaler, RNG and data-sampler state. Resuming continues bit-exactly (verified by a test), and you can extend
`max_steps` when resuming. Runs interrupted by a crash or shutdown are marked `interrupted` and resume from their
last checkpoint.

**Out of memory?** Reduce `batch_size` (raise `grad_accum` to keep the effective batch size), reduce `seq_len`, or
enable gradient checkpointing.

## 5. Evaluate and export

- **Export best** writes the best-validation checkpoint as a model under **Models** (fp16 by default, SHA-256
  checksummed).
- **Evaluate** measures validation loss, perplexity, next-token accuracy, and a small greedy code-completion
  benchmark (`moth/training/evaluate.py`). All numbers are computed by running the model.

## 6. Teaching MOTH to be an agent

The agent needs the model to emit `<|tool_call|>{"tool": …, "args": …}` actions. A model pretrained only on raw text
won't do that. The path forward:

1. Pretrain MOTH-50M on code and English (steps 1–5).
2. Fine-tune on chat and agent transcripts in `jsonl` `messages` format (the loss is applied to assistant turns only).
   Set `init_from` (advanced config) to the pretrained `model.pt`, and prepare the dataset with the **same
   tokenizer**.
3. Grow the data with **Learning network → Personal learning → Export verified tasks**. This turns tasks MOTH
   completed *and* verified with your tests into training examples, stored locally.

Only data that MOTH Code writes itself is marked `moth_trusted`, which lets its assistant turns contain real special
tokens. External JSONL is always encoded as plain text.
