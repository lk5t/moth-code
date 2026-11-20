"""2.4: more things to attach in chat — screenshots and photos, and GitHub links.

MOTH is a text model and cannot see pictures. An attached image is kept on this computer (so the chat can show
it) and the text in it is read with the operating system's own text recognition: Windows 10/11 ``Windows.Media.Ocr``
(built in, offline), else Tesseract when it is installed. MOTH answers from that text; when no text could be read
the message says so, honestly.

A GitHub link attaches either one file (``…/blob/<ref>/<path>`` or a raw link) or a whole repository or folder
(``github.com/<owner>/<repo>[/tree/<ref>/<path>]``), read from GitHub's archive in memory — nothing is written to
disk and nothing runs. The same rules as dropped folders apply: text files only, never anything that looks like a
secret, within the same size limits.
"""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from moth.security.permissions import is_secret_path
from moth.workspace.attachments import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, SKIP_DIRS, _is_text

IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
               "bmp": "image/bmp", "webp": "image/webp"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_ARCHIVE_BYTES = 60 * 1024 * 1024
OCR_TIMEOUT_S = 60

# Windows PowerShell 5.1 (not PowerShell 7: it cannot load WinRT types). Reads the text with the built-in engine.
_WINDOWS_OCR = r"""
$ErrorActionPreference = 'Stop'
$m = [Environment]::GetEnvironmentVariable('PSModulePath', 'Machine'); if ($m) { $env:PSModulePath = $m }
[Console]::OutputEncoding = [Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); $task.Wait() | Out-Null; $task.Result }
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { Write-Output '::no-engine::'; exit 0 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($args[0])) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
foreach ($line in $result.Lines) { Write-Output $line.Text }
"""


class AttachError(ValueError):
    pass


# ---- images ----------------------------------------------------------------------------------------------
def _kind(name: str, data: bytes) -> str | None:
    sig = {b"\x89PNG": "png", b"\xff\xd8\xff": "jpg", b"GIF8": "gif", b"BM": "bmp"}
    for magic, ext in sig.items():
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _run(cmd: list[str], timeout: int = OCR_TIMEOUT_S) -> subprocess.CompletedProcess:
    kw: dict[str, Any] = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, **kw)


def read_text(path: Path) -> dict[str, Any]:
    """The text in an image: ``{"text", "engine", "note"}``. Never raises for a missing engine."""
    if sys.platform == "win32" and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
        exe = shutil.which("powershell.exe") or r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
        try:
            p = _run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", _WINDOWS_OCR, str(path)])
            out = (p.stdout or "").strip()
            if p.returncode == 0 and out != "::no-engine::":
                return {"text": out, "engine": "windows", "note": None if out else "No text was found in the image."}
            if out == "::no-engine::":
                note = "Windows has no text-recognition language installed (Settings → Time & language → Language)."
            else:
                note = "Windows could not read the image: " + ((p.stderr or "").strip().splitlines() or ["unknown error"])[-1][:200]
        except (OSError, subprocess.TimeoutExpired) as e:
            note = f"Windows text recognition did not run ({e.__class__.__name__})."
    else:
        note = None
    tess = shutil.which("tesseract")
    if tess:
        try:
            p = _run([tess, str(path), "-", "--psm", "3"])
            if p.returncode == 0:
                out = (p.stdout or "").strip()
                return {"text": out, "engine": "tesseract", "note": None if out else "No text was found in the image."}
            note = "Tesseract could not read the image."
        except (OSError, subprocess.TimeoutExpired):
            note = "Tesseract did not run."
    return {"text": "", "engine": None,
            "note": note or "This computer has no text recognition (install Tesseract), so MOTH only knows an image was attached."}


def save_image(store: Path, name: str, data: bytes) -> dict[str, Any]:
    if not data:
        raise AttachError("The image is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise AttachError(f"The image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.")
    ext = _kind(name, data)
    if not ext:
        raise AttachError("Not a PNG, JPEG, GIF, BMP or WebP image.")
    digest = hashlib.sha256(data).hexdigest()[:32]
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{digest}.{ext}"
    if not path.exists():
        path.write_bytes(data)
    found = read_text(path)
    text = found["text"][:MAX_FILE_BYTES]
    return {"id": f"{digest}.{ext}", "name": (name or f"image.{ext}")[:120], "size": len(data), "text": text,
            "engine": found["engine"], "note": found["note"]}


def image_path(store: Path, image_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|gif|bmp|webp)", image_id):
        raise AttachError("Unknown image.")
    p = store / image_id
    if not p.is_file():
        raise AttachError("That image is no longer on this computer.")
    return p


# ---- GitHub links ----------------------------------------------------------------------------------------
_NAME = r"[A-Za-z0-9_.-]{1,100}"
BLOB = re.compile(rf"^https?://github\.com/({_NAME})/({_NAME})/blob/([^/]+)/(.+)$")
RAW = re.compile(rf"^https?://raw\.githubusercontent\.com/({_NAME})/({_NAME})/([^/]+)/(.+)$")
REPO = re.compile(rf"^https?://github\.com/({_NAME})/({_NAME})(?:/tree/([^/]+)(?:/(.+))?)?/?$")


def _headers(token: str) -> dict[str, str]:
    h = {"User-Agent": "MOTH-Code"}
    if token and len(token) <= 400:
        h["Authorization"] = f"Bearer {token}"
    return h


def parse_github(url: str) -> dict[str, Any]:
    url = url.strip().split("#")[0].split("?")[0]
    for kind, rx in (("file", BLOB), ("file", RAW)):
        m = rx.match(url)
        if m:
            return {"kind": kind, "owner": m[1], "repo": m[2], "ref": m[3], "path": m[4]}
    m = REPO.match(url)
    if m:
        return {"kind": "tree", "owner": m[1], "repo": m[2].removesuffix(".git"), "ref": m[3] or "HEAD", "path": (m[4] or "").strip("/")}
    raise AttachError("Paste a GitHub link to a repository, folder or file (https://github.com/owner/repo…).")


def _get(url: str, token: str, limit: int) -> bytes:
    try:
        with httpx.stream("GET", url, headers=_headers(token), timeout=60, follow_redirects=True) as r:
            if r.status_code == 404:
                raise AttachError("GitHub says that link does not exist (or it is private: connect GitHub in Settings → Connections).")
            if r.status_code >= 400:
                raise AttachError(f"GitHub answered {r.status_code}.")
            buf = io.BytesIO()
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > limit:
                    raise AttachError(f"That is more than {limit // (1024 * 1024)} MB; link a folder or a file instead.")
            return buf.getvalue()
    except httpx.HTTPError as e:
        raise AttachError(f"GitHub could not be reached: {e}") from None


def fetch_github(url: str, token: str = "") -> dict[str, Any]:
    g = parse_github(url)
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    if g["kind"] == "file":
        shown = f"{g['repo']}/{g['path']}"
        if is_secret_path(g["path"]):
            return {"files": [], "skipped": [{"path": shown, "reason": "looks like a secret (key, .env or credentials)"}]}
        raw = _get(f"https://raw.githubusercontent.com/{g['owner']}/{g['repo']}/{g['ref']}/{g['path']}", token, MAX_FILE_BYTES * 4)
        if not _is_text(raw):
            return {"files": [], "skipped": [{"path": shown, "reason": "not a text file"}]}
        text = raw[:MAX_FILE_BYTES].decode("utf-8", errors="ignore")
        return {"files": [{"path": shown, "name": PurePosixPath(g["path"]).name, "size": len(raw), "content": text,
                           "truncated": len(raw) > MAX_FILE_BYTES}], "skipped": []}
    data = _get(f"https://codeload.github.com/{g['owner']}/{g['repo']}/tar.gz/{g['ref']}", token, MAX_ARCHIVE_BYTES)
    total = 0
    want = PurePosixPath(g["path"]) if g["path"] else None
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
    except tarfile.TarError:
        raise AttachError("GitHub's archive could not be read.") from None
    with tar:
        for member in sorted(tar.getmembers(), key=lambda x: x.name):
            if not member.isfile():
                continue  # links, devices and folders are never followed
            rel = PurePosixPath(*PurePosixPath(member.name).parts[1:])  # drop the "<repo>-<sha>/" folder
            if not rel.parts or any(p in SKIP_DIRS or p.startswith(".") for p in rel.parts[:-1]):
                continue
            if want and want not in (rel, *rel.parents):
                continue
            shown = f"{g['repo']}/{rel}"
            if len(files) >= MAX_FILES or total >= MAX_TOTAL_BYTES:
                skipped.append({"path": shown, "reason": "limit reached"})
                break
            if is_secret_path(rel):
                skipped.append({"path": shown, "reason": "looks like a secret (key, .env or credentials)"})
                continue
            fh = tar.extractfile(member)
            if fh is None:
                continue
            limit = min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
            raw = fh.read(limit + 1)
            if not _is_text(raw):
                continue  # images and binaries in a repository are simply left out
            text = raw[:limit].decode("utf-8", errors="ignore")
            total += len(text.encode("utf-8"))
            files.append({"path": shown, "name": rel.name, "size": member.size, "content": text, "truncated": len(raw) > limit})
    if not files and not skipped:
        raise AttachError("No text files were found at that link.")
    return {"files": files, "skipped": skipped}
