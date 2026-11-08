## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

GENESIS adds an Owner-gated, reversible fresh MOTH 0.01 lineage, automatically eligible CPU training,
compatible GPU preference with CPU fallback, corrected training controls and lineage-aware metrics.
Existing dataset, growth, distributed training, evaluation and rollback implementations are retained.
The reset first verifies an archive/restoration and then requires separate explicit Owner approval.
Installing this release never resets the deployed model or user data. A fresh baseline is untrained;
neither these smoke tests nor this release establishes completed Foundation training.

The 0.5.8 update-agent patch uses public GitHub download URLs for unauthenticated release
assets, reducing REST use to one release-list request per check. An unreadable historical
manifest no longer blocks verified newer releases. Private repositories keep authenticated
asset requests; manifest signatures, payload checksums, health verification and rollback remain required.
Desktop 0.5.7 remains the compatible Windows release.

The 0.5.9 follow-up exposes measured live training tokens/loss/checkpoints and removes revoked
workers from normal user and Owner lists without deleting training history or resetting weights.
The existing 0.5.8 agent transport fix and signing/rollback requirements are retained.

| File | What it is |
| --- | --- |
| `moth-cloud-__VERSION__.tar.gz` | Server bundle: server, MOTH backend, update agent, installer, templates, backup script, `INSTALL.md` |
| `moth-worker-__VERSION__.tar.gz` (+ `.sha256`) | MOTH Worker bundle |
| `moth-release-__VERSION__.json` + `.sig` | Manifest with the SHA-256 of every file, signed with the MOTH release key |
| `SHA256SUMS` | Checksums of all files above |

Install or upgrade an existing server: see `INSTALL.md` in the bundle
([docs/SERVER.md](https://github.com/lk5t/moth-code/blob/__REF__/docs/SERVER.md)). Existing data is adopted in place
after a verified backup; nothing is deleted.

The Windows desktop app for this version ships in the next desktop release.
