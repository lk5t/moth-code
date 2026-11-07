"""Download approved dataset files once, verify them, and reuse them.

Files live in ``<cache>/<repo>@<revision>/<path>``. A file is used only after its size and SHA-256 match
the catalog; the verified record (``.verified.json``) means later builds reuse it without downloading or
re-hashing it. Interrupted downloads resume with HTTP Range requests. A file that does not verify is
deleted and reported — it is never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from moth.datafactory import catalog

CHUNK = 1 << 20


class FetchError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def local_path(cache: Path, src: dict[str, Any], f: dict[str, Any]) -> Path:
    return Path(cache) / f"{src['repo'].replace('/', '__')}@{src['revision'][:12]}" / f["path"]


def _record(cache: Path) -> Path:
    return Path(cache) / ".verified.json"


def verified(cache: Path) -> dict[str, Any]:
    try:
        return json.loads(_record(cache).read_text())
    except (OSError, ValueError):
        return {}


def _mark(cache: Path, key: str, info: dict[str, Any]) -> None:
    rec = verified(cache)
    rec[key] = info
    tmp = _record(cache).with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, sort_keys=True))
    os.replace(tmp, _record(cache))


def _download(url: str, dest: Path, size: int, timeout: float = 120.0,
              progress: Callable[[int, int], None] | None = None, opener=None) -> None:
    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    open_ = opener or urllib.request.urlopen
    for attempt in range(6):
        have = part.stat().st_size if part.exists() else 0
        if have > size:
            part.unlink()
            have = 0
        if have == size:
            break
        req = urllib.request.Request(url, headers={"User-Agent": "moth-data-factory"})
        if have:
            req.add_header("Range", f"bytes={have}-")
        try:
            with open_(req, timeout=timeout) as r:
                status = getattr(r, "status", 200)
                mode = "ab" if have and status == 206 else "wb"
                if mode == "wb":
                    have = 0
                with open(part, mode) as out:
                    while True:
                        block = r.read(min(CHUNK, size - have + 1))
                        if not block:
                            break
                        out.write(block)
                        have += len(block)
                        if have > size:
                            raise FetchError(f"download exceeds its pinned size: {url}")
                        if progress:
                            progress(have, size)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            if attempt == 5:
                raise FetchError(f"download failed after retries: {url}: {e}") from e
            time.sleep(min(30, 2 ** attempt))
    if not part.exists() or part.stat().st_size != size:
        got = part.stat().st_size if part.exists() else 0
        raise FetchError(f"incomplete download of {url}: {got} of {size} bytes")
    os.replace(part, dest)


def fetch_file(cache: Path, src: dict[str, Any], f: dict[str, Any], progress=None, opener=None,
               log: Callable[[str], None] = lambda m: None) -> Path:
    """Return the verified local copy of a catalog file, downloading it only if needed."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    dest = local_path(cache, src, f)
    key = f"{src['repo']}@{src['revision']}/{f['path']}"
    rec = verified(cache).get(key)
    if rec and dest.exists() and rec.get("sha256") == f["sha256"] and dest.stat().st_size == f["size"]:
        return dest  # downloaded and verified before: reuse
    if not (dest.exists() and dest.stat().st_size == f["size"]):
        log(f"downloading {key} ({f['size'] / 1e6:.1f} MB)")
        _download(catalog.file_url(src, f), dest, f["size"], progress=progress, opener=opener)
    digest = sha256_file(dest)
    if digest != f["sha256"]:
        dest.unlink(missing_ok=True)
        raise FetchError(f"{key} does not match its pinned SHA-256 (got {digest[:16]}…, expected "
                         f"{f['sha256'][:16]}…); the file was deleted and will not be used")
    _mark(cache, key, {"sha256": digest, "size": f["size"], "verified_at": time.time(),
                       "license": src["license"]})
    log(f"verified {key}")
    return dest


def fetch_source(cache: Path, src: dict[str, Any], roles=("train", "eval"), **kw) -> list[tuple[dict, Path]]:
    return [(f, fetch_file(cache, src, f, **kw)) for f in src["files"] if f["role"] in roles]
