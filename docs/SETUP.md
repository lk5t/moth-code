# Setup & building

> **v0.2 note.** MOTH is cloud-only. Users sign in to a MOTH account and use MOTH Cloud, so no GPU or model is
> needed on their PC. The PyTorch/CUDA notes below apply only to the Owner's local model-training tools and to
> development. To run the MOTH Server see [SERVER.md](SERVER.md); for GPU workers see [WORKER.md](WORKER.md).

## Installing (end users)

Download `MOTH Code_x.y.z_x64-setup.exe` from the repository's GitHub Releases and run it. It installs per user (no
administrator rights needed). The installer bundles the Python backend with a **CPU build of PyTorch**, so it works
on any 64-bit Windows 10/11 PC.

**NVIDIA GPU (CUDA).** A CUDA PyTorch build is too large for the NSIS installer (NSIS has a 2 GB limit), so v0.1
uses an external Python environment for GPU acceleration:

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
```

```bash
python -m pip install "<path-to-repo>/backend"
```

Then set the user environment variable `MOTH_PYTHON` to that interpreter (for example
`C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe`) and restart MOTH Code. The app will run the backend
with that interpreter instead of the bundled CPU one. **Settings → About** shows the detected GPU.

## Development

Prerequisites:

- Python 3.10+ (3.12 recommended)
- Node.js 22+
- Rust stable
- Git
- Windows: [WebView2 and the MSVC build tools](https://tauri.app/start/prerequisites/)
- Linux: `libwebkit2gtk-4.1-dev libgtk-3-dev librsvg2-dev libsoup-3.0-dev`

```bash
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
```

```bash
python -m pip install -e "./backend[dev]"
```

```bash
cd app && npm install
```

```bash
npm run tauri dev
```

In development the Rust shell runs `python -m moth.server` from `backend/` (`python` on Windows, `python3`
elsewhere, or `MOTH_PYTHON`).

**Browser-only UI development.** Run the backend yourself and use Vite without Tauri:

```bash
cd backend && python -m moth.server --port 8765
```

```bash
cd app && npm run dev
```

Then open http://localhost:1420. Without `MOTH_API_TOKEN` the backend accepts unauthenticated local requests, so use
this only for development.

### Environment variables

| Variable | Purpose |
| --- | --- |
| `MOTH_HOME` | Data directory (default `%APPDATA%\MOTH Code` / `~/.moth`). |
| `MOTH_PYTHON` | Interpreter used to run the backend (overrides the bundled backend). |
| `MOTH_BACKEND_URL` / `MOTH_API_TOKEN` | Connect the desktop shell to an already-running backend. |
| `MOTH_SHELL` | Shell used by the terminal on Linux/macOS (Windows uses PowerShell, falling back to `cmd`). |

## Building the Windows installer locally

On Windows, from the repository root:

```bash
python -m pip install "./backend[package]"
```

```bash
cd backend && pyinstaller --noconfirm --distpath dist packaging/moth-backend.spec
```

Copy the PyInstaller output into the Tauri resources folder (PowerShell):

```powershell
Copy-Item -Recurse backend/dist/moth-backend app/src-tauri/resources/backend
```

```bash
cd app && npx tauri build --config src-tauri/tauri.release.conf.json
```

To produce updater artifacts locally, set `TAURI_SIGNING_PRIVATE_KEY` first and put your public key into the release
config (see [RELEASING.md](RELEASING.md)). The installer is written to `app/src-tauri/target/release/bundle/nsis/`.

## Running the test suites

```bash
cd backend && python -m pytest -q
```

```bash
cd app && npm run typecheck && npm test
```

```bash
cargo test --manifest-path app/src-tauri/Cargo.toml
```
