# MOTH Worker — contributing training compute (CPU or GPU)

MOTH Worker is a small, separate program that trains the official MOTH model for the MOTH training
network and for model evolution. It is **not** an AI assistant. It never reads files on the machine
other than its own state, trains only on public, licensed data it downloads, and uploads only weight
updates.

Since 0.5, **CPU-only computers are full production workers**: MOTH gives every worker only jobs
that fit its memory, and prefers a GPU worker briefly for jobs that benefit from one.

## Requirements

| Requirement | Detail |
| --- | --- |
| OS | Linux (x86-64), Windows 10/11, macOS (best effort, see Limitations) |
| Python | 3.10+ with `venv`. On Windows it is installed for you with `winget` if it's missing; on Debian/Ubuntu: `sudo apt install python3-venv` |
| CPU / memory | 2+ cores, 3 GB+ RAM |
| GPU | Optional. An NVIDIA GPU with 8 GB+ VRAM is used when present (CUDA PyTorch is installed automatically) |
| Disk | 5 GB+ free (PyTorch plus the model) |
| Administrator rights | **Not needed** |

## One-command installation (EasyConnect)

1. In MOTH Code, open **Training & Referrals → Add a computer** and click **Get the command**.
2. Pick **Linux / macOS** or **Windows** and paste the command into a terminal (PowerShell on
   Windows) on that computer. It:
   - downloads the MOTH Worker release **from your MOTH Cloud** (relayed there from the signed
     GitHub release by the update agent);
   - verifies it against the SHA-256 pinned in the command, so nothing runs if the file differs;
   - creates a Python virtual environment (Linux/macOS: `~/.local/share/moth-worker/venv`, or
     `/opt/moth-worker` as root; Windows: `%LOCALAPPDATA%\MOTH\worker\venv`), installs the
     right PyTorch (CUDA for NVIDIA GPUs, CPU otherwise) and MOTH Worker;
   - enrolls the computer with a **single-use** token (valid 15 minutes) and stores the worker
     credential (file mode 600);
   - sets up an **automatic start** that survives reboots and restarts the worker if it stops:

     | Machine | Mechanism (chosen automatically) |
     | --- | --- |
     | Linux as root | systemd system service |
     | Linux, user with systemd lingering | systemd user service (lingering is enabled automatically where allowed) |
     | Linux, any other user (e.g. no sudo) | cron: `@reboot` plus a check every minute; the worker keeps exactly one copy running |
     | Windows | Scheduled task at logon (at startup when installed as administrator), restarting the worker if it stops |
     | macOS | LaunchAgent (`KeepAlive`) |
3. The worker appears under **Your workers** with its hardware, measured speed (GFLOP/s), verified
   jobs, tokens trained and reliability. Pause it, limit CPU cores, GPU memory and compute, or remove
   it from there.

Running the command again on the same computer (with a new token) **replaces** its old registration
instead of adding a second worker.

### Removing a worker

On the computer: `moth-worker uninstall` (Windows:
`& "$env:LOCALAPPDATA\MOTH\worker\venv\Scripts\moth-worker.exe" uninstall`). It stops the worker,
removes the automatic start (cron entries, systemd unit, scheduled task or LaunchAgent), revokes the
worker on MOTH Cloud and deletes its files. **Remove** in MOTH Code revokes it from the server side.

`install.sh` / `install.ps1` options:

| Option | Effect |
| --- | --- |
| `--name` / `-Name` | Name shown under **Your workers** |
| `--use-system-torch` / `-UseSystemTorch` | Reuse an already-installed PyTorch |
| `--torch-index URL` / `-TorchIndex URL` | Install PyTorch from a different wheel index |
| `--service auto\|systemd\|cron\|launchd` | Force an automatic-start mechanism (Linux/macOS) |
| `--no-service` / `-NoService` | No automatic start; run `moth-worker run` yourself |

## What a worker does

1. **Heartbeat** every 30 s: reports hardware and GPU utilisation, and receives the
   pause/revoke state and limits.
2. **Claim** a job.
3. **Download** the current checkpoint and a public, licensed data shard. Both are
   checksum-verified.
4. **Train** for the job's steps, respecting the GPU memory fraction and duty cycle. Progress
   is saved every 25 steps, so an interrupted job resumes from its last checkpoint after a
   reboot or reconnect.
5. **Upload** the weight update. The coordinator verifies protocol, base version, checksum,
   tensor shapes, finiteness, update size, and that held-out loss does not get worse. Only
   accepted work counts.
6. If the worker stops responding, its lease expires after 10 minutes and the job goes to
   another worker.

**Rewards.** Verified jobs can earn MOTH usage credits for the person whose referral code was
used when enrolling the server, after a minimum number of verified jobs and a pending period
(Owner-configurable). Idle or failing servers earn nothing, and you cannot refer your own
server.

## Automatic updates

Workers update themselves. Every 30 minutes, between training jobs, the worker asks MOTH Cloud whether a
newer worker release is available for it (releases roll out in stages). An update is installed only if:

- the release manifest's ed25519 signature verifies against the key built into the worker, and
- the downloaded bundle matches the SHA-256 in that signed manifest, and
- the new code passes a start test.

The new version is installed next to the current one (`versions/<version>`, with `current` and
`previous` links in the worker's state directory), and the worker restarts into it and reconnects with
the same credential. A job in progress is always finished first — training progress is never discarded
for an update. If a new version fails to start three times, the previous version is restored
automatically. The worker's version is shown in MOTH Code → Training & Referrals and in the Owner
Dashboard. Use `moth-worker run --no-auto-update` to opt out.

Workers installed with v0.2 don't have the updater yet: reinstall them once with a new enrollment
command; from then on they update themselves.

## Commands

| Command | Purpose |
| --- | --- |
| `moth-worker detect` | Show detected hardware and whether it's supported |
| `moth-worker enroll --server URL --token TOKEN` | Manual enrollment |
| `moth-worker run [--max-jobs N]` | Run the worker loop |
| `moth-worker status` | Show enrollment status |
| `moth-worker run --log-file F` | Run with a rotating log file (what the automatic start uses) |
| `moth-worker install-service [--mode …]` | Set up the automatic start (systemd, cron, launchd or a scheduled task) |
| `moth-worker uninstall [--keep-files] [--yes]` | Stop, remove the automatic start, revoke on MOTH Cloud, delete files |

## Jobs a worker runs (0.5.3+)

| Job | Who gets it | What happens |
| --- | --- | --- |
| Evolution experiment (`evolve_train`) | the first compatible worker (GPU preferred for 5 minutes) | trains a whole experiment and returns its update |
| Distributed shard (`dist_shard`) | every compatible participant, once per round | trains its slice of the curriculum from the round's weights; steps follow the worker's measured speed |
| Evaluation (`eval_loss`, MOTH Worker 0.5.3+) | CPU workers first | measures a candidate's held-out loss; counts only when two different workers agree |
| Training-network round (`train_round`) | workers with ≥ 1 GB free memory | the original federated rounds of the training network |

MOTH Code can take part too (Network or Model training → *Contribute this computer*): it enrolls this
computer with your account and runs the same worker loop in the background.

## Status of distributed training (honest summary)

Experiments train in verified rounds: participants train the same weights on different slices of the
curriculum, the server checks every update and averages them weighted by tokens, and applies a round
only if its own held-out probe does not get worse. Repeated or late submissions are refused and expired
shards are reassigned. Tested end to end with real training in real MOTH Worker runners (two workers,
including a disconnection; MOTH Code's participant alongside a standalone worker) — see
[TEST_RESULTS.md](TEST_RESULTS.md).

Not done yet: large-scale training (many workers, larger models), robust aggregation against coordinated
poisoning, secure aggregation, and data preparation on workers. GPU execution has not been verified on
real NVIDIA hardware here (all build machines are CPU-only), and the Windows desktop build bundles CPU
PyTorch, so MOTH Code contributes CPU compute.
