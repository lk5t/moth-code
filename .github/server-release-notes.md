## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

LIVING INTELLIGENCE retains the existing training/evolution, distributed workers, adaptive growth,
held-out promotion gates, staged rollout, signed update agent and automatic rollback. It adds
capability-labeled reference tests, a privacy-filtered activity feed and an explicit full native AI
reset, separate from legacy reversible lineage recovery.

Full reset requires an authenticated, recently reauthenticated Owner, reviewed deletion inventory
and exact typed confirmation. Managed backup deletion needs a separate confirmation. Native work
is fenced, owned artifacts and native records are removed and verified, failures are recoverable,
and workers acknowledge scoped cleanup. Unverified/offline copies and infrastructure snapshots
remain disclosed. Accounts, credentials, ordinary chat, billing, settings, consent, signing keys and
installed software are preserved. Use the supported single-coordinator deployment; stop any other
process that directly writes its native storage before resetting.

Installing or auto-updating this release **never resets native AI data** or initializes replacement
weights. Foundation training is not claimed complete. The existing updater transport/signing and
rollback implementations are retained. Desktop and Worker 0.6.0 are compatible with this server.

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
