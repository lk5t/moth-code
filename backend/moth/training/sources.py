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
    ".jsonl", ".sh", ".ps1", ".sql", ".lua", ".dart", ".vue", ".svelte", ".zig", ".ini", ".cfg",
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
    trusted: bool = False  # written by MOTH Code itself: assistant turns may contain special tokens


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
        raise FileNotFoundError(f"directory not found: {root.name}")
    for rel, path in iter_files(root, max_files=1_000_000):
        if path.suffix.lower() not in TEXT_EXTENSIONS or is_secret_path(rel) or path.is_symlink():
            continue
        if path.suffix.lower() == '.jsonl':
            yield from _iter_jsonl(path)
            continue
        try:
            with path.open(encoding='utf-8-sig') as stream:
                index = 0
                while text := stream.read(256 * 1024):
                    yield Document(text, f"dir:{root}", f"{rel}:{index}")
                    index += 1
        except UnicodeDecodeError:
            raise ValueError(f"{rel}: expected UTF-8 text") from None


def _iter_jsonl(path: Path) -> Iterator[Document]:
    with open(path, encoding="utf-8-sig") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                raise ValueError(f"{path.name}: line {i}: malformed JSON") from None
            if not isinstance(row, dict):
                raise ValueError(f"{path.name}: line {i}: expected an object")
            messages = row.get('messages')
            if messages is None and ('prompt' in row or 'answer' in row):
                if not all(isinstance(row.get(k), str) and row[k].strip() for k in ('prompt', 'answer')):
                    raise ValueError(f"{path.name}: line {i}: prompt and answer must be nonempty text")
                messages = [{'role': 'user', 'content': row['prompt']}, {'role': 'assistant', 'content': row['answer']}]
            if messages is not None:
                if (not isinstance(messages, list) or not messages or any(not isinstance(m, dict)
                    or m.get('role') not in ('system', 'user', 'assistant', 'tool', 'tool_call', 'tool_result')
                    or not isinstance(m.get('content'), str) for m in messages)
                    or not any(m['role'] == 'assistant' and m['content'].strip() for m in messages)):
                    raise ValueError(f"{path.name}: line {i}: messages need valid roles, text content and an assistant answer")
                messages = [{**m, 'role': 'tool_result' if m['role'] == 'tool' else m['role']} for m in messages]
                yield Document('\n'.join(m['content'] for m in messages), f'jsonl:{path}', str(i),
                               messages=messages, trusted=bool(row.get('moth_trusted')))
            elif isinstance(row.get('text'), str) and row['text'].strip():
                yield Document(row['text'], f'jsonl:{path}', str(i))
            else:
                raise ValueError(f"{path.name}: line {i}: expected nonempty text, prompt/answer, or messages")


def _iter_hf(src: SourceSpec) -> Iterator[Document]:
    try:
        import datasets  # type: ignore
    except ImportError as e:
        raise RuntimeError(f"Hugging Face source {src.target}: dataset support is not installed; install the backend datasets extra or update to a build with dataset support") from None
    entry = catalog_entry(src.spec) or {}
    field_name = src.options.get("field") or entry.get("field") or "text"
    config = src.options.get("config") or entry.get("config")
    split = src.options.get("split", "train")
    try:
        ds = datasets.load_dataset(src.target, config, split=split, streaming=True)
        for i, row in enumerate(ds):
            text = row.get(field_name)
            if not isinstance(text, str):
                raise ValueError(f"Hugging Face source {src.target}: record {i} lacks text field {field_name}")
            yield Document(text, src.spec, str(i))
    except Exception as error:
        status = getattr(getattr(error, 'response', None), 'status_code', None)
        kind = type(error).__name__
        if status in (401, 403) or 'Gated' in kind:
            reason = 'access denied; authenticate with an authorized account and accept the source license if required'
        elif status == 404 or 'NotFound' in kind:
            reason = 'repository, configuration or split is unavailable; check the selected source and access'
        elif isinstance(error, ValueError):
            reason = 'invalid configuration or missing text field; check the source field and split'
        else:
            reason = 'download or preparation failed; check connectivity and retry this source'
        # Do not expose request URLs, authorization headers or hub tokens from upstream exceptions.
        raise RuntimeError(f"Hugging Face source {src.target}: {reason} ({kind})") from None
