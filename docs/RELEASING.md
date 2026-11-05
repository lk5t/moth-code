# Releasing & signed updates

## One-time setup: updater signing key

Tauri verifies every in-app update against a public key compiled into the app. Generate a key pair **on your own
machine** and keep the private key secret:

```bash
cd app && npx tauri signer generate -w ~/.tauri/moth-code.key
```

In the GitHub repository settings, add:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `TAURI_SIGNING_PRIVATE_KEY` | contents of `~/.tauri/moth-code.key` |
| Secret | `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | its password (if you set one) |
| Variable | `TAURI_UPDATER_PUBKEY` | contents of `~/.tauri/moth-code.key.pub` |

Without these, release builds still succeed, but `scripts/prepare-release.mjs` disables updater artifacts and logs a
warning, so the build never offers updates it cannot verify.

## Cutting a release

1. Bump the version in **all** of: `app/package.json`, `app/src-tauri/tauri.conf.json`,
   `app/src-tauri/Cargo.toml`, `backend/pyproject.toml`, `backend/moth/__init__.py`. The release script fails on any
   mismatch.
2. Update `CHANGELOG.md`, commit, then either push a tag, or run the **Release (Windows)** workflow manually from the Actions tab with the tag as input (the workflow creates the tag and release itself):

```bash
git tag v0.1.0
```

```bash
git push origin v0.1.0
```

3. The `Release (Windows)` workflow:
   - builds the PyInstaller backend with CPU PyTorch;
   - smoke-tests the frozen executable (server handshake, all subsystems loaded, a CLI job);
   - bundles it into the NSIS installer;
   - publishes a **pre-release** with the MOTH-themed installer (plus `.sig` and `latest.json` when signing is configured).
4. The release is published as a pre-release. Installed apps check
   `https://github.com/lk5t/moth-code/releases/latest/download/latest.json` (Settings → Updates, plus a silent
   check at startup) and install only updates whose signature verifies.

Because `releases/latest` ignores drafts and pre-releases, mark a release as **latest** when you want installed apps
to receive it.
