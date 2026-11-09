# Intelligent Evolution — completion evidence

Branch: `claude/jolly-darwin-2qeihd`. Remote and local HEAD were synchronized at `188b358` at continuation start. That commit's full CI succeeded: run 42587150791, all ten jobs (PostgreSQL, SQLite, Windows/Linux backend and desktop shell, frontend, Windows/Linux worker installation, Linux server/agent/worker updates and recovery).

| Phase | Status and evidence |
|---|---|
| 1 Simplified settings | Implemented; backend permission/persistence/resource-policy tests and five-control UI regressions passed. Individual PC contribution remains separate. |
| 2 Hardware optimization | CPU execution, actual available Windows RAM logic, cached bounded measurements, adaptive batches, unsupported-GPU fallback and inference/resource policy covered. Physical GPU, thermal and Windows power-sensor validation unavailable here; simulated driver tests are not hardware proof. |
| 3 Distributed consent | Implemented and integration tested: Owner-only cloud registration, personal opt-in, local verified account/device binding, pause/stop/revoke, immutable worker kind, expired lease and revocation safeguards. |
| 4 Reliability | Existing verified result accounting, leases, heterogeneity, corrupt/duplicate result rejection and redistribution remain operational. Reliability ordering and bounded compute profiles added. Representative physical multi-machine latency/performance certification remains unavailable; no claim of certified scaling. |
| 5 Live UI | Implemented: five Intelligence sections, deployed identity/revision/tokenizer, measured training charts/ETA and deployment history. Real Chromium checks passed at 1440/800 px, preserving chat drafts and editor visibility. Restarted isolated Cloud against existing database/checkpoints; browser revision, step and tokenizer matched API. Blocking progress requests cleared displayed model identity with an explicit unavailable state. |
| 6 Dataset/training | TXT and JSONL prompt/answer/messages token production, intended tokenizer, approval, actual forward/backward passes and checkpoints tested. License metadata and gated/error categories retained. Hugging Face dependency/loader packaging added. Exact production all-v1 traceback was never supplied; cannot certify its particular source. Local pip dependency download blocked by proxy CONNECT403; no physical GPU. |
| 7 Revisions/milestones | Routine CPU-trained promotions retain public version and advance revision. Two real CPU lifecycle runs verified continuation and rollback. Milestone guards require independent material practical gains, repeatability, retention, speed and memory bounds. Positive milestone orchestration unit tested with controlled evaluator results; no trained Foundation milestone is claimed. |
| 8 Recovery/deployment | Real checkpoint/crash/restart/resume and rollback tests passed on SQLite and PostgreSQL. Deployment DB-failure injection preserves live engine; integrity/tokenizer/growth protections retained. |
| 9 Permissions/privacy | Existing suites and new direct API test verify an already leased public dataset stops being downloadable when reclassified private: shard/weight requests return409 and claim returns204. No source redistribution consent is inferred from training consent. This is tested boundary coverage, not an independent public security audit. |
| 10 Updates | Server 0.5.9 workflow42584643037 succeeded and GitHub confirms published signed manifest, cloud and worker bundles. Linux real-process update/rollback/recovery CI passed. Desktop 0.5.9 workflow42595477401 succeeded: all14 jobs, original published0.5.1→0.5.4 production-signature update proof, signed A→B installation/restart/data-preservation test, production frozen-backend/native UI checks, manifest/signature verification and publication. GitHub confirms both release asset lists and non-draft/non-prerelease status. |
| 11 Testing | Full CI at188b358,3c8e865 and1d64653 passed. Latest run42595384712 passed all10 jobs. New private-lease test plus three existing boundary tests:4 passed. Native harness contract verification:9 server and2 UI tests passed. Browser checks above passed. Physical GPU and the production all-v1 download remain validation limits. Both final Windows update gates passed. |
| 12 Integration/release | Desktop and Server0.5.9 are published and mandatory Windows release gates passed. Suitable evidence for controlled CPU rollout; unrestricted GPU/model-quality certification remains incomplete. No trained Foundation quality claim. No production model reset, destructive migration or manual production deployment performed. |

## This continuation

- Added `server/tests/test_worker_boundaries.py::test_private_dataset_is_blocked_even_for_preexisting_worker_lease`; committed and pushed `3c8e8659ade8e6be40271022fdc2086246b4fcda`.
- Restarted only the disposable browser-test Cloud, preserving its database, model and checkpoints. Production was not contacted or modified.
- Reused existing signed Desktop workflow from passing commit188b358; no signing, updater, rollout or workflow gate changes.
- Existing Server release: https://github.com/lk5t/moth-code/releases/tag/server-v0.5.9
- Desktop release verification: https://github.com/lk5t/moth-code/actions/runs/42595477401

Foundation training is not complete. Small CPU tests establish pipeline behavior, not general model capability.

## Native release gate correction

Desktop run42590212731 passed full CI, both real Windows update tests, production signed installer/frozen-backend/Owner-login checks, workspace drafts and interactive tabs. Its native harness then timed out checking `backends.workers` after clicking the separate `cloud_workers` control. Fixed only `scripts/test-genesis-desktop.py` to assert the correct cloud setting and additionally ensure personal-worker backend policy remains unchanged. Compilation,9 server contract/privacy tests and2 UI contract tests passed. Commit1d64653a0d05acec79eb4fb7e99495df5969fca2 pushed. Existing signed release rerun42595477401 retains every gate. Prior failed release was not published (GitHub404).

## Full architecture execution evidence

The passing Linux backend CI job executes `scripts/verify-foundation-training.py`: the full moth-50m architecture, PSF-2.0 stdlib corpus, real forward/backward/AdamW updates, checkpoints at steps1/2, optimizer-state verification, resume to step3 and192 processed tokens, integrity-verified export and CPU generation. The script asserts every weight tensor differs from its initial snapshot. This is expressly not a quality benchmark or a trained Foundation completion claim. GPU remains unavailable locally.

## Published release evidence

- Server workflow42584643037: completed/success. Release: https://github.com/lk5t/moth-code/releases/tag/server-v0.5.9
- Desktop workflow42595477401: completed/success,14 successful jobs. Release: https://github.com/lk5t/moth-code/releases/tag/desktop-v0.5.9
- Desktop assets: `MOTH.Code_0.5.9_x64-setup.exe`, `.exe.sig`, `moth-release-desktop-0.5.9.json`, `.json.sig`, `SHA256SUMS`. Installer GitHub digest: `sha256:df96f9685778587143c37ef3b140b6dd39be94b3311d3320e662c708f4e852b6`.
- Server assets: `moth-cloud-0.5.9.tar.gz`, `moth-worker-0.5.9.tar.gz`, worker checksum, signed `moth-release-0.5.9.json` and `SHA256SUMS`. Both releases confirmed `draft=false`, `prerelease=false` through GitHub API.
- Native Windows independent proof: real frozen backend/Cloud API; five Intelligence tabs; workspace draft preservation; cloud toggle and actual worker enrollment; real CPU cycle; Owner session/navigation restored after restart;800×600 layout. `production_reset=false`, `trained_foundation=false`.
- Signed updater and signature-verification implementations were not modified. Existing rollout controls remain authoritative. No claim that a particular production installation has already updated.

## Final limits and readiness

All twelve phases have been reviewed against source and available execution evidence; the table distinguishes functional implementation from incomplete environment-specific validation. Physical CUDA/GPU performance, real thermal/power behavior and representative multi-host scaling are not certified. The exact production `all-v1` source/traceback remains unavailable; local Hugging Face dependency/download execution is blocked by proxy403. Source imports, approved local datasets and real CPU training are verified. Positive public-milestone orchestration is unit tested, but no substantial trained-model milestone or full Foundation training completion is claimed.

The signed CPU Desktop/Cloud release passed its available release gates and is ready for the existing controlled rollout. A blanket claim of unrestricted GPU readiness or production Foundation model quality is not supported. Completing those validation items requires supported physical hardware and access to the approved external source/production diagnostics, not a reset of existing models.

Only these repository files changed during this continuation:

1. `server/tests/test_worker_boundaries.py`: directly exercise privacy denial on an existing worker lease (3c8e865).
2. `scripts/test-genesis-desktop.py`: fix the obsolete native assertion to use `cloud_workers` and additionally verify personal-worker backend policy remains unchanged (1d64653).
3. `docs/INTELLIGENT-EVOLUTION-VERIFICATION.md`: replace stale progress notes with the phase evidence, release results and explicit limits.

No application/updater code, dependency, model weight, tokenizer, checkpoint, account or production configuration was changed during this continuation. The isolated browser-test Cloud was restarted using its existing data.
