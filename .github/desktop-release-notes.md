<p align="center"><img src="https://raw.githubusercontent.com/lk5t/moth-code/__REF__/branding/moth-icon-1024.png" width="96" alt="MOTH"/></p>

## MOTH Code __VERSION__ for Windows

### What's new — 0.9.0: MOTH runs itself. It adds much bigger training data on its own (about 90 GB of licensed sources, downloaded part by part as it needs them), quizzes itself every hour and learns from its mistakes, repairs common problems by itself (Settings → Advanced → Diagnostics shows what it did), and a worker's progress is no longer lost when its job moves elsewhere. 0.8.3: training runs now finish instead of stopping at about a tenth of their steps, and MOTH Cloud and your workers train the same experiment together (the network view shows whether MOTH Cloud joins in). A worker on a busy computer no longer holds an experiment while MOTH Cloud sits idle. 0.8.2: a stalled worker loses its experiment within minutes, so Evolution keeps moving. 0.8.1: Evolution keeps going (it explores when every plan was tried) and experiment times are measured by MOTH Cloud

### COGNITIVE EVOLUTION (0.8.0)

- MOTH's evolution now focuses on **conversation** (50 %) and **coding** (40 %), with new verified
  training data: multi-turn conversations that depend on earlier messages, debugging exercises, code
  explanations and test writing.
- New held-out benchmarks: multi-turn conversation, executed code generation and executed debugging.
  A new model is promoted only if neither conversation nor coding gets worse overall.
- **AI → Model** shows the benchmark history of every promoted version and measured serving speed.
- **Knowledge 2.0** and **Research** (Settings → Intelligence): categories, projects, confidence,
  verification, outdated and near-duplicate flags; cited research reports that separate corroborated
  statements, conflicts and gaps.

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
