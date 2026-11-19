<p align="center"><img src="https://raw.githubusercontent.com/lk5t/moth-code/__REF__/branding/moth-icon-1024.png" width="96" alt="MOTH"/></p>

## MOTH Code __VERSION__ for Windows

### What's new in 2.2

- **MOTH can move past its first model.** Better candidates are no longer rejected over measurement noise (speed and memory of a same-size model, chance-level drops on small exams). Workers' finished runs on small models are kept instead of refused as "update too large".
- **A readable MOTH timeline:** clear version labels, a scale that one far-off point no longer flattens, promoted and not-promoted versions set apart, and values on hover.
- **Clearer Evolution card.** It says why candidates are not being promoted, uses consistent model names and has plain-language plans.
- **Tidier app.** Home actions are together, sign-in screens have a Sign in button, the tour lives in Settings → About, the project chat toolbar is readable, and panels pause their refreshes while the window is hidden.

The full list is in [CHANGELOG.md](https://github.com/lk5t/moth-code/blob/__REF__/CHANGELOG.md).

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
