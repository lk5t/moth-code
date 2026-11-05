# MOTH Worker — contributing GPU training compute

MOTH Worker is a small, separate Linux program that trains rounds of the official MOTH
model for the MOTH training network. It is **not** an AI assistant. It never reads files
on the machine other than its own state, and it uploads only weight updates.

## Requirements

| Requirement | Detail |
| --- | --- |
| OS | Linux x86-64 |
| Python | 3.10+ with `venv` (on Debian/Ubuntu: `apt install python3-venv`) |
| GPU | NVIDIA, 8 GB+ VRAM (an RTX 3060 12 GB is the reference worker), with a working driver (`nvidia-smi`) |
| Disk | About 10 GB free (PyTorch plus the model) |

It works on rented GPU servers from any provider. No provider-specific integration is needed.

## One-command enrollment

1. In MOTH Code, open **Training & Referrals → Add a GPU server** and click **Generate command**.
2. Paste the command into the server's terminal. It does four things:
   - downloads the versioned MOTH Worker release from the MOTH Server;
   - verifies it with `sha256sum -c` against the SHA-256 pinned in the command, so nothing
     runs if the file differs;
   - extracts the release and runs `install.sh`, which creates a Python virtual environment
     (`/opt/moth-worker` as root, otherwise `~/.local/share/moth-worker/venv`), installs a
     CUDA build of PyTorch matching the driver, and installs MOTH Worker;
   - enrolls the machine with a **single-use** token that expires after 15 minutes, saves a
     worker credential (file mode 600), and installs a systemd service that restarts
     automatically.
3. The worker appears under **Your workers**. Pause it, set GPU-memory and compute limits, or
   revoke it from there. A revoked worker stops at its next heartbeat and cannot reconnect.

`install.sh` options:

| Option | Effect |
| --- | --- |
| `--name` | Name shown under **Your workers** |
| `--use-system-torch` | Reuse an already-installed PyTorch |
| `--torch-index URL` | Install PyTorch from a different wheel index |
| `--no-service` | Don't install the systemd service; run the worker manually with `moth-worker run` |

Without systemd (some containers), run `moth-worker run` inside `tmux` or `screen`.

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

## Commands

| Command | Purpose |
| --- | --- |
| `moth-worker detect` | Show detected hardware and whether it's supported |
| `moth-worker enroll --server URL --token TOKEN` | Manual enrollment |
| `moth-worker run [--max-jobs N]` | Run the worker loop |
| `moth-worker status` | Show enrollment status |
| `moth-worker install-service` | Install the systemd service |

## Status of distributed training (honest summary)

The network trains controlled rounds: workers train the same checkpoint on different shards,
and verified updates are aggregated by token-weighted federated averaging into a new
checkpoint version. That checkpoint must then pass the evaluation gate before the Owner (or
auto-deploy) puts it into MOTH Cloud.

This loop is tested end to end with real training on CPU (see [TEST_RESULTS.md](TEST_RESULTS.md)).
Large-scale distributed training is future work: many workers, larger models, robust
aggregation against coordinated poisoning, and secure aggregation. GPU execution of the
worker itself has not been verified on real NVIDIA hardware in the development environment.
