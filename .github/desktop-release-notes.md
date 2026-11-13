<p align="center"><img src="https://raw.githubusercontent.com/lk5t/moth-code/__REF__/branding/moth-icon-1024.png" width="96" alt="MOTH"/></p>

## MOTH Code __VERSION__ for Windows

### What's new

- **AI → Model:** the active MOTH model in one place — an animated core drawn from its real layers and
  heads, verified parameters, architecture, checkpoint, tokenizer, deployment and held-out capabilities
  compared with the rollback model; Owner rollback and a compact history.
- **What trains MOTH:** MOTH Cloud's server, workers and this computer, in any combination. MOTH Cloud
  now trains together with the workers.
- Workers also prepare training data (every result is checked by MOTH Cloud); new verified reasoning and
  language data.
- Owner-only notifications; smoother view and tab transitions, loading skeletons and consistent focus.
- Updates are checked hourly; a staged rollout is shown as a wait, not an error.

Installing this update preserves existing accounts, settings, projects, datasets, tokenizers, models and checkpoints.
Foundation training is **not** claimed complete. Physical GPU verification requires compatible hardware.

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
