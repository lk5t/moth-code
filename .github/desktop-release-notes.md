<p align="center"><img src="https://raw.githubusercontent.com/lk5t/moth-code/__REF__/branding/moth-icon-1024.png" width="96" alt="MOTH"/></p>

## MOTH Code __VERSION__ for Windows

### What's new in 2.4

- **Saved prompts**, **chat tabs**, **Run** on code blocks (temporary folder, 15-second limit, you confirm first) and project files in Ctrl+K.
- Home shows **top helpers this week** and **test scores across versions**.
- **Report a problem** from Settings → Updates & about.
- Network: **Pause while gaming** per computer.

### What's new in 2.3

- **2.3.2:** AI → **Shared training** shows a shared run as an animated picture in plain words. Attach folders, screenshots/photos (or paste them) and GitHub links. Edit or branch from any message, rate any answer, and pick a theme and accent colour.
- **2.3.1:** Home shows this week's progress, how MOTH answers now (before and after its last upgrade) and a one-click **Train on this PC**. Network shows each computer's health and lets you set its training hours. The AI timeline says why each version was or was not promoted.
- **A new, compact look:**
  - The sidebar has New chat, Search chats, **Projects as folders with their chats inside**, then Chats, and your account at the bottom.
  - Your messages sit on the right; MOTH's replies are plain text.
  - One message box with attach, model and Send.
  - A small connection status line.
- **The "This computer" switch tells you when your NVIDIA GPU could train MOTH** through the MOTH Worker instead.

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
