## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

This release (0.7.1) adds:

- Evolution promotes a verified model without waiting for user requests: the minimum monitored
  requests becomes 0 once (a value the Owner sets later persists); without traffic, repeated passing
  health checks are the evidence, and a failing check still rolls back.
- One active model and one rollback model: after each verified promotion, older packages are removed
  (records and measurements are kept). Nothing is removed during the upgrade itself.
- Owner-only notifications (`/v1/admin/notifications`; HTTP 403 for every other account).
- Workers are told about a newer worker release in every heartbeat and install it between jobs at once;
  worker releases go to every worker immediately, and a failed install backs off (at most 6 hours).
- The update agent asks GitHub conditionally (ETag, 304 Not Modified), reuses verified manifests and
  waits out GitHub rate limits instead of retrying.

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
