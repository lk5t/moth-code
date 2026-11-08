# Compact UI and measured training progress (0.5.9)

Scope starts at `8fbcefc2752e8862bdd3691c234b2ceb98d2cead` on `claude/jolly-darwin-2qeihd`.

The known `moth-200k-v0.1-step500` package is presented as **MOTH 0.0.1**. This is a UI label, not a new model, a model-version migration, a weight reset or a claim of completed training. Official evolved model versions and external providers retain their names. Existing settings, consent, workspaces, accounts, inference, training scheduling and signed update/rollback systems remain in place.

Code and Chat fill the window, use smaller headers/gutters and content-sized composers, and keep mounted state during mode switches. Main section/settings/Owner/tool/file tabs share a compact visual treatment; existing navigation is retained. Decorative MOTH motion is gentle and respects reduced-motion preferences. Work-state animation follows actual request/task/training state.

The Training tab shows measured steps, tokens, training/validation loss, compute assignment, throughput and latest reported checkpoint without opening advanced controls. Unknown values say “Not reported”; paused, waiting and error states stay explicit. No elapsed-time progress simulation is used. Local counters come from the actual trainer; worker fields remain limited to what workers report.

Revoking a worker invalidates access, requeues its leased job and removes it from normal account/Owner lists. Its database tombstone, audit trail, contributions and checkpoints remain so identities and training history are preserved. This does not remotely uninstall software on a disconnected computer.

## Verification before release

- Focused frontend suites: 12 tests passed (compact UI, workspace modes, Intelligence hub, Owner dashboard, Owner training).
- TypeScript checking and production frontend build passed.
- Server: real progress dashboard/timeline CPU lifecycle and revoke regression: 2 passed. Event decoding plus revoke regression: 2 passed in the earlier focused run.
- Backend: existing genuine 60-step optimizer/loss/checkpoint regression passed, including measured token consistency.
- Chromium with actual isolated Cloud/backend: drafts and unsaved Monaco content survived Code/Chat switching; all main tab areas worked; settings/Intelligence/Owner layouts had no document overflow at 800×600; Code/Chat filled the available width at 1440 and 800 pixels; reduced motion disabled brand animation.
- A fresh isolated CPU fixture completed 1,000 optimizer steps and 128,000 tokens. The new visible card displayed training loss **3.4167**, held-out validation loss **3.2489**, and `step_00001000.pt` at step 1,000. These are smoke-run measurements, not evidence of a fully trained Foundation model or general capability.
- Physical GPU/multi-machine training and a live update on the user's Windows installation were not exercised locally. Signed Windows installer/update and native UI verification run through the existing release gates; publication results are recorded below when confirmed.

## Exact changed files and necessity

| File | Reason |
|---|---|
| `.github/desktop-release-notes.md` | Describe the requested desktop changes in the signed release. |
| `.github/server-release-notes.md` | Describe the required progress and worker-list API changes in the signed server release. |
| `.github/workflows/release.yml` | Set the existing desktop release input default to 0.5.9; signing and gates unchanged. |
| `.github/workflows/server-release.yml` | Set the existing server release input default to 0.5.9; signing and gates unchanged. |
| `app/package-lock.json` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `app/package.json` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `app/src-tauri/Cargo.lock` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `app/src-tauri/Cargo.toml` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `app/src-tauri/tauri.conf.json` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `app/src/components/MothEmblem.tsx` | Add opt-in subtle wing motion and unique SVG references for simultaneously mounted emblems. |
| `app/src/components/NavRail.tsx` | Animate the brand gently and expose the selected main destination accessibly. |
| `app/src/components/ui/tabs.tsx` | Apply one compact, scrollable tab style with selected and keyboard-focus states. |
| `app/src/features/agent/AgentPanel.tsx` | Compact the task welcome/composer and use the MOTH emblem for actual running tasks. |
| `app/src/features/chat/ChatPanel.tsx` | Use available conversation width, reduce gutters, grow the composer with content/panel width, and animate real streaming. |
| `app/src/features/chat/ChatView.tsx` | Compact model/context rows and use the model presentation label. |
| `app/src/features/evolution/EvolutionView.tsx` | Use the same model presentation label in evolution. |
| `app/src/features/intelligence/IntelligenceHub.tsx` | Show measured training progress above advanced controls and compact the main tab row. |
| `app/src/features/intelligence/IntelligenceView.tsx` | Use the same model presentation label across current model, capabilities and timeline. |
| `app/src/features/intelligence/OnDeviceSection.tsx` | Use the same model presentation label for local model status. |
| `app/src/features/intelligence/TrainingProgress.tsx` | Display actual step, token, loss, compute and checkpoint reports with honest waiting/paused/error states. |
| `app/src/features/owner/ModelOverview.tsx` | Use the same model presentation label in Owner model controls. |
| `app/src/features/owner/OwnerDashboard.tsx` | Compact Owner navigation and page gutters without replacing its panels. |
| `app/src/features/owner/ops.tsx` | Clarify worker removal and retained training history in the existing revoke control. |
| `app/src/features/settings/SettingsView.tsx` | Use shared accessible tabs and compact spacing for all existing settings groups. |
| `app/src/features/workspace/EditorPanel.tsx` | Compact file tabs, add selection/close labels and arrow-key file navigation. |
| `app/src/features/workspace/WorkspaceShell.tsx` | Compact Code/Chat navigation and fill the available window while keeping both workspaces mounted. |
| `app/src/features/workspace/WorkspaceView.tsx` | Reduce toolbar height and give new layouts more editor space while retaining saved layouts. |
| `app/src/index.css` | Define gentle MOTH motion and disable it under reduced-motion preferences. |
| `app/src/lib/model-label.ts` | Present the existing legacy checkpoint as MOTH 0.0.1 without changing registry identity or weights. |
| `app/src/test/compact-ui.test.tsx` | Cover legacy labels, independent emblems, measured progress updates, paused/waiting states and keyboard tabs. |
| `backend/moth/__init__.py` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `backend/moth/training/trainer.py` | Include the real accumulated token counter in existing trainer events. |
| `backend/pyproject.toml` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `backend/tests/test_training.py` | Check emitted counters against the actual trainer in the existing optimizer/checkpoint regression. |
| `scripts/test-worker-install.ps1` | Expect removed workers to be absent after the real Windows uninstall test. |
| `scripts/test-worker-install.sh` | Expect removed workers to be absent after the real Linux uninstall test. |
| `server/moth_server/__init__.py` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `server/moth_server/evolution/backends.py` | Retain measured token counts and checkpoint filename/step from trainer events. |
| `server/moth_server/routes/dashboard.py` | Exclude revoked workers from Owner lists and user detail lists. |
| `server/moth_server/routes/intelligence.py` | Expose measured experiment progress and assigned device in the existing progress endpoint. |
| `server/moth_server/routes/training.py` | Exclude revoked workers from the account worker list. |
| `server/pyproject.toml` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `server/tests/test_evolution_integrity.py` | Cover real event decoding for steps, tokens, losses and checkpoints. |
| `server/tests/test_training_network.py` | Cover list removal, invalidated credentials, job requeue and preserved revocation tombstone. |
| `worker/moth_worker/__init__.py` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `worker/pyproject.toml` | Coordinate package/version metadata for the existing signed 0.5.9 release; no dependency changes. |
| `docs/UI-POLISH.md` | Record the requested scope, exact file changes, measurements and delivery limits. |
