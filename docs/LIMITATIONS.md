# Known limitations & remaining requirements (0.5.4)

Current verified implementation status and remaining requirements are in [CONTINUATION.md](CONTINUATION.md).
This page lists what depends on the Owner's infrastructure or accounts, what could not be verified in
the development environment, and what is unfinished — so nothing is overstated.

## Steps only the Owner can do (one time)

| Needed | Why | Where |
| --- | --- | --- |
| A **domain** pointing at the VPS, and **Caddy** (or another TLS proxy) on ports 80/443 | The official HTTPS endpoint desktops connect to | DNS at your registrar; Caddy needs root once ([SERVER.md](SERVER.md#steps-that-need-an-administrator-root)) |
| Run **`install-server.sh`** on the VPS | Switches the existing server to supervised, self-updating operation (adopts its data) | [SERVER.md](SERVER.md#moving-the-existing-vps-over-no-data-is-moved-or-deleted) |
| GitHub **secrets** `MOTH_RELEASE_SIGNING_KEY`, `TAURI_SIGNING_PRIVATE_KEY`, `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` and the variable **`MOTH_CLOUD_URL`** | Signed releases and the built-in endpoint | [RELEASING.md](RELEASING.md) |
| A read-only **GitHub token** on the server (while the repository is private) | The update agent downloads releases | `--github-token-file` |
| **SMTP**, **Stripe**, an Authenticode certificate | Real emails, paid plans, no SmartScreen warning | unchanged from v0.2 |

Without `MOTH_CLOUD_URL`, release builds have no built-in address. The app asks for one, and it can
be changed at any time in Settings → Connection. Set the variable only to a permanent HTTPS address,
never a temporary tunnel. Without the signing secrets, desktops get no automatic updates.

**Desktops on v0.2.x or v0.3.0 need one manual install of 0.3.1.** v0.2 had no working updater, and
v0.3.0 only checked for updates at a built-in address.
After that every update is automatic. The same is true for workers enrolled with v0.2.

## Not verified in the development environment

- **Windows:** the complete automatic update (detect → download → verify → install → relaunch → report,
  with user data preserved) is verified on a GitHub Windows runner with real installers. It used
  throw-away keys and a loopback server, not the production key or the VPS. Upgrading from v0.2.1 on
  a real PC was not tested.
- **The live VPS:** it was not touched. The installer and update agent were tested end to end on Linux
  with real processes: adopting a running v0.2.1 server, updates, rollback with database restore,
  recovery after a crash mid-update, and a simulated reboot. They were not run on the actual VPS or
  under real systemd (the container has no systemd). The cron supervisor path was tested.
- **HTTPS:** the Caddy configuration is generated and syntax-correct but was not run against a real
  domain and certificate.
- **GPU:** no NVIDIA GPU was available. CPU inference and CPU workers are tested; the CUDA paths are
  unchanged from v0.2 and untested on hardware.
- **PostgreSQL backups by the agent** need `pg_dump`/`pg_restore` on the server; the agent's backup and
  restore were exercised with SQLite. The server itself is tested on PostgreSQL.

## Model evolution (0.4.0)

- **Training hardware.** The VPS has no GPU. Without a MOTH GPU worker, or CPU training enabled for a
  small model, evolution plans its cycles and then **waits for compute**. It says so and never reports
  training. CPU training was measured only with tiny models; training MOTH-50M on the VPS CPU is
  possible within the memory estimate but slow, and was not measured.
- **What the gates can measure.** Held-out bits per byte or token loss, retention of every dataset
  learned before, Python completion validity, speed and memory are measured for every candidate.
  Reasoning, instruction following and factual accuracy (hallucination rate) are measured only if you
  upload task suites; otherwise they are reported as *not measured*. Small models also score 0 % on
  valid-Python completions today, so that gate only catches regressions once a model can complete code.
- **Architecture migration.** Since 0.5.3 a model can grow deeper and wider in its FFN without losing
  what it learned (function-preserving growth). Changing the residual width, the number of heads or the
  tokenizer is still not implemented (it needs distillation); datasets for another tokenizer are marked
  *needs migration*, and training from scratch is possible only when explicitly enabled.
- **One host.** The engine assumes one MOTH Cloud server process (as installed). Two server processes
  on one database would each run a scheduler.
- **Zero downtime.** The model switch is atomic for new requests (requests already running finish on
  the old model). On a CPU-only server, loading a large model briefly competes with inference for CPU.
- **Monitoring** uses this server's own measurements (error rate, latency, health probes). It cannot
  judge answer quality in production; quality is decided by the evaluation gates before deployment.
- **Compute budget** counts training time as experiments report it (at pause and finish), so a single
  long run is counted when it pauses or ends, not continuously.

## ASCENSION 0.5.x

- **Foundation status.** Earlier docs claim a 49M-token CPU run, but no trained Foundation weights or
  corresponding evaluation report were found in this checkout. Training completion is unverified.
  Every further improvement is limited by the compute the network provides — with only CPU workers, a
  cycle of a few thousand steps takes hours.
- **GPU training** is implemented (CUDA, bf16) but not verified on real NVIDIA hardware; all build
  machines are CPU-only. MOTH Code's Windows build bundles CPU PyTorch, so it contributes CPU compute.
- **Distributed training** uses verified local-SGD rounds; it is not robust against a coordinated group
  of malicious workers (no secure aggregation), and data preparation stays on the server.
- **External AI providers** are implemented but off by default (as decided); none is configured.
- **Model families** (separate Core/Code/Lite models) were not built: there is one MOTH lineage.
- **Releases.** Milestones 0.5.2–0.5.4 were built and tested in order but published together as 0.5.4.

## Model capability

The trained Foundation model's conversational, factual, mathematical and coding capabilities cannot
be verified without its actual weights and matching held-out data. The executed full-size scratch
smoke test demonstrates training, resume and generation, not useful intelligence. Chat should report
the deployed model's actual recorded benchmarks; unmeasured capabilities remain unmeasured.

## Design limits

- Staged rollouts use the install's random id; there is no per-region or per-plan targeting.
- The update agent keeps the latest 3 releases and 5 backups locally; off-host backups still use
  `scripts/backup-server.sh` (needs your storage and GPG key).
- Downloads that are interrupted restart from the beginning (desktop) or are retried (server, worker);
  only model uploads resume chunk by chunk.
- Docker installations update by pulling a new image, not through the agent.
- The terminal is line-oriented (not a full PTY). Changing the email address and deleting accounts are
  not implemented.
