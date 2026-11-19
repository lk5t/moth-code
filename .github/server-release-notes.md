## MOTH Cloud __REF__ — server release

The MOTH Cloud server for self-managing operation: one-time installation (no sudo required), automatic
signed updates, verified backups, health checks with automatic rollback, the fixed model publishing
workflow (evaluation datasets, resumable uploads) and the Owner Dashboard APIs.

What's new in 2.2:

- **2.2.3: MOTH Cloud installs Node.js by itself** (official build, SHA-256 verified, into its data folder, no administrator rights), so the JavaScript exam runs.

- **2.2.2: candidates are evaluated again.** Every evaluation crashed with "KeyError: 'value'" because the JavaScript exam (which needs Node.js) returned no score. A suite that cannot run is now just not measurable.

- **2.2.1: MOTH grows again.** A growth size rejected twice was blocked forever, so parameters stopped growing. Now only failures on the same base within two days count, and a smaller step is tried meanwhile.

- **Promotion no longer rejects better models over noise.**
  - A same-architecture candidate's speed and memory are recorded as information, not blocking (the base was often benchmarked while the server was idle and the candidate during training).
  - On small accuracy exams, a drop within three standard errors does not count as a skill getting worse.
- **Worker results on small models are kept.** Whole-run results allow relative updates up to 1000×; shared rounds allow up to 100× (was 10×). Shapes and finite values are always checked, and rounds must still lower held-out loss.
- **A rejection streak is reported.** The autopilot's bottleneck names the checks that blocked the last five or more candidates.
- Plain-language exploration objectives, and readable tokens-per-parameter values.

The full list is in [CHANGELOG.md](https://github.com/lk5t/moth-code/blob/__REF__/CHANGELOG.md).

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
