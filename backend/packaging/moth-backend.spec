# PyInstaller spec for the MOTH Code backend (one-folder build).
# Build: pyinstaller --noconfirm packaging/moth-backend.spec   (from backend/)
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

BACKEND = os.path.abspath(os.path.join(SPECPATH, ".."))  # noqa: F821 (SPECPATH is provided by PyInstaller)
sys.path.insert(0, BACKEND)

hiddenimports = (
    collect_submodules("moth")
    + collect_submodules("uvicorn")
    + ["websockets", "websockets.legacy", "httpx"]
)

a = Analysis(
    [os.path.join(SPECPATH, "entry.py")],  # noqa: F821
    pathex=[BACKEND],
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "torch.utils.tensorboard", "torchvision", "torchaudio"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="moth-backend",
    console=True,  # stdout is the handshake channel; the shell launches it with CREATE_NO_WINDOW
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="moth-backend", upx=False)
