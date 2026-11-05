<p align="center"><img src="https://raw.githubusercontent.com/lk5t/moth-code/__REF__/branding/moth-icon-1024.png" width="96" alt="MOTH"/></p>

## MOTH Code — SIMPLIFY

MOTH is now self-managing. Install once, sign in, start coding: MOTH Code connects to MOTH Cloud by
itself and keeps itself up to date. MOTH Cloud and MOTH Workers update themselves from this signed
release, and publishing AI models works end to end.

### Install

1. Download **`MOTH.Code_<version>_x64-setup.exe`** below. You only need to do this once, or once more
   if you are coming from v0.2: future versions install themselves.
2. Run it. It installs for your user account only, so no administrator rights are needed.
3. Windows SmartScreen may warn because the installer is not code-signed yet. Choose **More info → Run anyway**.

### For the Owner

- `moth-cloud-<version>.tar.gz` is the MOTH Cloud server bundle. Install it once with
  `deploy/install-server.sh`. After that, MOTH Cloud picks up new releases on its own.
- `moth-worker-<version>.tar.gz` is the MOTH Worker bundle. Workers on v0.3 update automatically.
- `moth-release-<version>.json` and its `.sig` are the signed manifest for every file in this release.

Read the [known limitations](https://github.com/lk5t/moth-code/blob/__REF__/docs/LIMITATIONS.md) and the
[CHANGELOG](https://github.com/lk5t/moth-code/blob/__REF__/CHANGELOG.md).
