## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

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
