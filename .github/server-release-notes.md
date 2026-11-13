## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

This release (0.7.2) adds:

- Dataset preparation on workers: chunks are tokenized and hashed by workers 0.7.2+, re-encoded in
  part and verified by MOTH Cloud, merged with exact deduplication; MOTH Cloud takes unclaimed or late
  chunks itself. User-consented feedback is never sent to workers.
- MOTH Cloud's built-in worker: the server joins distributed training rounds, preparation and
  evaluations under the same verification (pauses during its own local experiments; follows the Owner's
  "What trains MOTH" choice; `MOTH_CLOUD_WORKER=0` disables it). The bundle now includes the worker.
- Failing training strategies are suspended while another strategy works.
- Verified synthetic reasoning and language sources.
- Still from 0.7.1: minimum monitored requests 0, one active + one rollback model, Owner-only
  notifications, immediate worker updates, conditional GitHub requests in the update agent.

The existing evolution, distributed workers, growth, held-out promotion gates, staged rollout, Genesis
Reset safeguards, signed update agent and automatic rollback are kept. Genesis Reset never runs during an upgrade.

Installing or auto-updating this release **never resets native AI data** or initializes replacement
weights. Foundation training is not claimed complete. The existing updater transport/signing and
rollback implementations are retained. Desktop and Worker 0.6.0 and later are compatible with this server.

| File | What it is |
| --- | --- |
| `moth-cloud-__VERSION__.tar.gz` | Server bundle: server, MOTH backend, update agent, installer, templates, backup script, `INSTALL.md` |
| `moth-worker-__VERSION__.tar.gz` (+ `.sha256`) | MOTH Worker bundle |
| `moth-release-__VERSION__.json` + `.sig` | Manifest with the SHA-256 of every file, signed with the MOTH release key |
| `SHA256SUMS` | Checksums of all files above |

Install or upgrade an existing server: see `INSTALL.md` in the bundle
([docs/SERVER.md](https://github.com/lk5t/moth-code/blob/__REF__/docs/SERVER.md)). Existing data is adopted in place
after a verified backup; nothing is deleted.

The Windows desktop candidate is built by the separate signed Desktop workflow. Publication requires explicit Owner approval.
