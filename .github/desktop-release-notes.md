<p align="center"><img src="https://raw.githubusercontent.com/lk5t/moth-code/__REF__/branding/moth-icon-1024.png" width="96" alt="MOTH"/></p>

## MOTH Code __VERSION__ for Windows

### Compact workspace and live training

- The existing legacy model is displayed as **MOTH 0.0.1**; its weights, registry ID and measured parameter count are preserved.
- Code and Chat use compact toolbars, wider conversations and growing message inputs. Saved layouts, drafts, files and tasks are retained.
- Main application tabs share a cleaner keyboard-accessible design. Subtle MOTH wing motion respects reduced-motion preferences.
- Intelligence → Training shows reported steps, tokens, loss, compute and checkpoint status directly. Unknown measurements are labelled.
- Removing a worker revokes its credential and removes it from normal worker lists while preserving training/audit history.

### GENESIS

- One Code/Chat workspace preserves drafts, active tasks and unsaved files when switching modes.
- Intelligence groups Overview, Training, Evolution, Network and Data, with measured model activity,
  live backend status and existing advanced controls.
- Training controls send the correct JSON body and show readable API errors. Signed updates retain
  network/rollout errors, retry failed checks and install verified downloads on close or restart.
- A fresh native MOTH 0.01 reset requires a verified archive and a separate, explicit Owner approval.
  Installing this release does not reset any model. The fresh baseline is untrained; Foundation
  training is not claimed complete.

### Install

- **New install, or coming from v0.2.x:** download **`MOTH.Code___VERSION___x64-setup.exe`** below and run it. It
  installs for your user account only; no administrator rights are needed. Your accounts, settings, workspaces,
  training runs, models and checkpoints are kept.
- **Already on v0.3.1 or later:** nothing to do. MOTH Code finds this update by itself, downloads and verifies it in
  the background, and shows *"MOTH Code __VERSION__ is ready — Restart now"*. It also installs when you close the app.

Windows SmartScreen may warn because the installer is not code-signed yet: choose **More info → Run anyway**.

### Connecting

Sign in, and if MOTH Cloud's address needs changing (for example while the permanent domain's HTTPS is being set
up), go to **Settings → Connection**, enter the address, and choose **Test & use**. No reinstall is needed.

| File | What it is |
| --- | --- |
| `MOTH.Code___VERSION___x64-setup.exe` | Windows installer |
| `MOTH.Code___VERSION___x64-setup.exe.sig` | Updater signature (checked by the app before installing an update) |
| `moth-release-desktop-__VERSION__.json` + `.sig` | Signed release manifest |
| `SHA256SUMS` | Checksums |

This is a desktop release. It doesn't change the MOTH Cloud server; server releases are published separately.
