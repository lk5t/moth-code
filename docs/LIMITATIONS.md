# Known limitations & unfinished work (v0.1.0)

This is a foundation release. Everything listed as working in the README is implemented and tested. This page
lists what is **not** done yet, or done only partially, so nothing is overstated.

## Model capability

- **No trained model ships with MOTH Code.** Users train their own. The only model trained during development was a
  6.2M-parameter `moth-small` trained for ~10 minutes on 852K tokens of Python stdlib code (validation loss 4.19).
  It produces Python-flavoured text and cannot follow instructions.
- **The agent needs a model trained for tool use.** A model pretrained on raw text will not emit
  `<|tool_call|>` actions, and tasks end as "beyond current model". The engine, tools and permissions are ready.
  What's missing is (1) MOTH-50M pretraining at scale and (2) an instruction/agent fine-tuning dataset, which does not
  exist yet. Personal learning can grow one from verified tasks, but bootstrapping it needs a model that can already
  complete some tasks.
- MOTH-50M has a 2K-token context. Prompts for large projects are trimmed (retrieved code first, then old steps), so
  long multi-file tasks will need larger presets (`moth-150m`/`moth-400m`, 4K context) and more training.
- The code benchmark is a small set of greedy completion checks for tracking early progress. It is not a
  standard benchmark.

## Training

- One training run at a time; single GPU; no multi-GPU or distributed data parallel yet.
- The BPE tokenizer trainer is pure Python. Fine for tens to hundreds of MB, slow for multi-GB corpora (use
  `max_mb`). Dataset preparation is likewise single-process.
- Hugging Face datasets need the optional `datasets` package and network access. Gated datasets need terms accepted
  on huggingface.co first. The license catalog records published licenses; users remain responsible for compliance.
- Fine-tuning from an exported model (`init_from`) is available only as an advanced config field, with no dedicated
  UI flow.

## Application

- **The terminal is line-oriented, not a full PTY.** Commands run with streamed output, a persistent working
  directory and Ctrl+C cancellation, but interactive full-screen programs (vim, interactive REPLs, password prompts)
  are not supported.
- The installer bundles **CPU PyTorch only** (the CUDA build exceeds NSIS's 2 GB limit). GPU users point `MOTH_PYTHON`
  at a CUDA environment (see SETUP.md). A separate GPU runtime download is planned.
- The installer is ~1 GB unpacked because of PyTorch.
- The Windows installer and in-app updates are built only by the GitHub Actions release workflow. They have not been
  produced or installed in this development environment. The frozen backend and the bundled-resource launch path
  were verified on Linux.
- Signed updates need the owner to generate a key and configure repository secrets (see RELEASING.md). Until then,
  release builds don't offer updates. The installer itself is not Authenticode code-signed, so Windows SmartScreen
  will warn.
- Single window; no multi-workspace tabs; no inline diff review before the agent applies edits (changes can be
  reverted afterwards per task).
- Chat history is kept per project, without search or export.

## Learning network & cloud

- **No MOTH Cloud servers and no public community coordinator are operated.** The protocols, clients and reference
  servers are implemented and tested. Endpoints must be configured by the user and are empty by default.
- Community aggregation is token-weighted FedAvg with per-update validation and a probe-loss check. Secure
  aggregation, robust aggregation against coordinated poisoning, reputation and differential privacy are future work.
- Community jobs download the full model each round, which is fine at 50M parameters but needs deltas or sharding for
  larger models.
- The GPU memory cap uses PyTorch's per-process memory fraction, and throttling is a duty cycle between steps. There
  is no OS-level GPU scheduling or idle detection yet.

## Testing

- The Rust shell has unit tests only; desktop UI behaviour was verified by launching the real app under a virtual
  display and by browser screenshots, not by an automated end-to-end UI suite.
- Windows-specific behaviour is covered by the Windows CI jobs, not by manual testing on a Windows PC.
