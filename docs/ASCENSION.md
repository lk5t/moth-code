# ASCENSION (0.5.x) — plan and status

See the [continuation audit](CONTINUATION.md) for the current checkout's verified status, focused fixes,
and remaining requirements; the milestone labels below are historical release descriptions.

ASCENSION ships as staged, tested and signed releases. Each one is usable on its own and verified in
production before the next. This page says what each milestone contains and where it stands, so
nothing is presented as done before it is.

| Milestone | Contents | Status |
| --- | --- | --- |
| **0.5.0** | EasyConnect workers (one command on Linux/macOS/Windows, automatic start without sudo, uninstall, packages served by MOTH Cloud); CPU workers as production workers with benchmarks and capability-based job assignment; Referral Rewards 2.0 | Released |
| **0.5.1** | Intelligence Router (native MOTH; compatible external providers supported but off by default, as the Owner decided), Knowledge Engine (search over approved documents, cited answers), opt-in feedback learning, Training Data Factory (cleaning, deduplication, filtering of approved data), curriculum, weakness detection | Released ([details](INTELLIGENCE.md)) |
| **0.5.2** | MOTH 0.1 Foundation: conversational tokenizer and chat format, about 50M-parameter training pipeline on licensed chat and text data, a real training run within the available compute, honest benchmarks (conversation, instruction following, coding), model names independent of app versions (MOTH 0.1, 0.2 …), user model pinning | Released in 0.5.4 ([details](FOUNDATION.md)); MOTH 0.1 as model release `model-v0.1` |
| **0.5.3** | Evolution 2.0 (development checkpoints, curriculum experiments, early stopping, plateau-driven parameter growth with Owner approval, staged rollout, model versions) and Distributed Compute 2.0 (distributed training rounds, evaluation on CPU workers, speed-proportional workloads, MOTH Code as a participant). Not built: data preparation on workers (the server prepares data) | Released in 0.5.4 ([details](EVOLUTION2.md)) |
| **0.5.4** | Simplified desktop (Chat, Code, Intelligence, Evolution, Network, Settings), Intelligence Progress dashboard and MOTH timeline, one-click evolution. Not built: separate model families (Core, Code, Lite) — there is one MOTH lineage | Released |

## Ground rules that apply to every milestone

- Existing accounts, workers, databases and deployed models are preserved. Migrations are additive and
  tested against the release production runs before publishing.
- Model quality is reported from real benchmarks. All current machines are CPU-only, so MOTH 0.1 will
  be trained within that budget and its real scores shown. It improves automatically when a GPU
  worker joins.
- No external AI provider receives user data unless the Owner configures one and users opt in.
