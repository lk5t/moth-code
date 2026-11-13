## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

This release (0.8.0 — COGNITIVE EVOLUTION) adds:

- Conversation and coding curricula (verified generated data), held-out multi-turn and executed coding
  benchmarks, a 50/40/10 conversation/coding/other starting focus and a balanced-capabilities promotion
  gate. Installations already using generated data adopt the new sources once.
- Knowledge 2.0 metadata (new table, no schema migration) and the Research Engine (`POST /v1/research`).
- Measured serving performance per deployed model; a CPU thread setting is kept only when ≥ 10 %
  faster with identical output.
- Still from 0.7.x: MOTH Cloud's built-in worker, data preparation on workers, immediate worker updates,
  one active + one rollback model, Owner-only notifications.

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
