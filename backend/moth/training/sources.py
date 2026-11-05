"""Training data sources, each tagged with a license.

MOTH only trains on data whose license permits it. Every prepared dataset
records the sources and licenses it was built from in ``meta.json``.

Source specs (strings, used by the CLI and API):

* ``stdlib`` — Python standard library source code (PSF-2.0), found on the
  local machine. Zero-download bootstrap corpus for code.
* ``dir:<path>`` — a local folder of text/code the user has the right to use;
  the user must declare its license (``license`` field).
* ``jsonl:<path>`` — JSON Lines with ``{"text": ...}`` or
  ``{"messages": [{"role", "content"}, ...]}`` (chat / instruction data).
* ``hf:<dataset_id>`` — a Hugging Face dataset (requires the optional
  ``datasets`` package and network access). Only catalog entries have vetted
  licenses; anything else requires an explicit license declaration.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from moth.security.permissions import is_secret_path
from moth.workspace.scanner import iter_files

TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs",
    ".rb", ".php", ".swift", ".html", ".css", ".scss", ".json", ".toml", ".yaml", ".yml", ".md", ".txt", ".rst",
    ".sh", ".ps1", ".sql", ".lua", ".dart", ".vue", ".svelte", ".zig", ".ini", ".cfg",
}

# Vetted public datasets. ``license`` is the dataset's published license; users
# must still review and accept the terms (some datasets are gated).
CATALOG: list[dict[str, Any]] = [
    {"id": "stdlib", "spec": "stdlib", "name": "Python standard library", "kind": "code",
     "license": "PSF-2.0", "download": False,
     "notes": "Source code of the Python standard library installed on this computer. No download needed."},
    {"id": "tinystories", "spec": "hf:roneneldan/TinyStories", "name": "TinyStories", "kind": "english",
     "license": "CDLA-Sharing-1.0", "download": True, "field": "text",
     "notes": "Synthetic short stories with simple English; good for small language models."},
    {"id": "wikitext-103", "spec": "hf:Salesforce/wikitext", "config": "wikitext-103-raw-v1", "name": "WikiText-103",
     "kind": "english", "license": "CC-BY-SA-3.0", "download": True, "field": "text",
     "notes": "Wikipedia articles. Share-alike: derived models must respect attribution requirements."},
    {"id": "the-stack-smol", "spec": "hf:bigcode/the-stack-smol", "name": "The Stack (smol)", "kind": "code",
     "license": "Permissive source licenses (per-file); gated — accept terms on Hugging Face", "download": True,
     "field": "content", "gated": True,
     "notes": "Small sample of permissively licensed source code from The Stack."},
]


@dataclass
class SourceSpec:
    spec: str
    license: str = ""
    max_documents: int | None = None
    max_bytes: int | None = None
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        return self.spec.split(":", 1)[0]

    @property
    def target(self) -> str:
        return self.spec.split(":", 1)[1] if ":" in self.spec else ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_any(cls, v: "str | dict | SourceSpec") -> "SourceSpec":
        if isinstance(v, SourceSpec):
            return v
        if isinstance(v, str):
            return cls(spec=v)
        return cls(**{k: val for k, val in v.items() if k in cls.__dataclass_fields__})


@dataclass
class Document:
    text: str
    source: str
    id: str
    messages: list[dict[str, str]] | None = None  # chat-formatted documents


class LicenseError(ValueError):
    pass


def catalog_entry(spec: str) -> dict[str, Any] | None:
    return next((c for c in CATALOG if c["spec"] == spec), None)


def resolve_license(src: SourceSpec) -> str:
    entry = catalog_entry(src.spec)
    lic = src.license or (entry["license"] if entry else "")
    if not lic:
        raise LicenseError(f"source {src.spec!r} has no declared license; declare one you have the right to use")
    return lic


def find_stdlib() -> Path | None:
    """Locate a Python standard library *source* tree (the frozen app has none of its own)."""
    candidates: list[Path] = []
    if not getattr(sys, "frozen", False):
        candidates.append(Path(sysconfig.get_paths()["stdlib"]))
    for exe in ("python3", "python", "py"):
        found = shutil.which(exe)
        if not found:
            continue
        try:
            out = subprocess.run([found, "-c", "import sysconfig;print(sysconfig.get_paths()['stdlib'])"],
                                 capture_output=True, text=True, timeout=20)
            if out.returncode == 0 and out.stdout.strip():
                candidates.append(Path(out.stdout.strip()))
        except (OSError, subprocess.TimeoutExpired):
            continue
    for c in candidates:
        if (c / "os.py").exists():
            return c
    return None


def iter_source(src: SourceSpec) -> Iterator[Document]:
    kind = src.kind
    produced, nbytes = 0, 0

    def limited(docs: Iterator[Document]) -> Iterator[Document]:
        nonlocal produced, nbytes
        for d in docs:
            if not d.text.strip() and not d.messages:
                continue
            yield d
            produced += 1
            nbytes += len(d.text)
            if src.max_documents and produced >= src.max_documents:
                return
            if src.max_bytes and nbytes >= src.max_bytes:
                return

    if kind == "stdlib":
        root = find_stdlib()
        if root is None:
            raise FileNotFoundError("No Python standard library sources found. Install Python 3 to use this source.")
        yield from limited(_iter_stdlib(root))
    elif kind == "dir":
        yield from limited(_iter_dir(Path(src.target)))
    elif kind == "jsonl":
        yield from limited(_iter_jsonl(Path(src.target)))
    elif kind == "hf":
        yield from limited(_iter_hf(src))
    else:
        raise ValueError(f"unknown source kind {kind!r}")


def _iter_stdlib(root: Path) -> Iterator[Document]:
    skip = {"site-packages", "test", "tests", "idlelib", "lib2to3", "turtledemo", "__pycache__", "dist-packages"}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and not d.startswith("."))
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                p = Path(dirpath) / fn
                try:
                    text = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                yield Document(text, "stdlib", p.relative_to(root).as_posix())


def _iter_dir(root: Path) -> Iterator[Document]:
    if not root.is_dir():
        raise FileNotFoundError(f"directory not found: {root}")
    for rel, path in iter_files(root, max_files=1_000_000):
        if path.suffix.lower() not in TEXT_EXTENSIONS or is_secret_path(rel):
            continue
        try:
            if path.stat().st_size > 1_000_000:
                continue
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        yield Document(text, f"dir:{root}", rel)


def _iter_jsonl(path: Path) -> Iterator[Document]:
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if "messages" in row:
                text = "\n".join(m.get("content", "") for m in row["messages"])
                yield Document(text, f"jsonl:{path}", str(i), messages=row["messages"])
            else:
                yield Document(row.get("text", ""), f"jsonl:{path}", str(i))


def _iter_hf(src: SourceSpec) -> Iterator[Document]:
    try:
        import datasets  # type: ignore
    except ImportError as e:
        raise RuntimeError("Hugging Face sources need the optional 'datasets' package: pip install datasets") from e
    entry = catalog_entry(src.spec) or {}
    field_name = src.options.get("field") or entry.get("field") or "text"
    config = src.options.get("config") or entry.get("config")
    split = src.options.get("split", "train")
    ds = datasets.load_dataset(src.target, config, split=split, streaming=True)
    for i, row in enumerate(ds):
        yield Document(str(row.get(field_name, "")), src.spec, str(i))
