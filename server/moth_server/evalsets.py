"""Evaluation datasets for the model release gate.

Why this exists: v0.2 evaluated releases only against the training coordinator's probe tokens
or a hand-placed ``data/eval/tokens.bin``. A MOTH Cloud without an initialised training network
had neither, so every uploaded model was rejected with "no evaluation set is configured" — and a
model trained with its own tokenizer could not be scored against the network's probe at all.

Kinds of dataset:

* ``text`` — UTF-8 text. Scored in **bits per byte** with each model's own tokenizer, so it works
  for every MOTH model regardless of tokenizer. Preferred.
* ``tokens`` — uint32 token ids made with one specific tokenizer (the coordinator probe set, or a
  legacy ``data/eval/tokens.bin`` + ``tokens.json`` naming its tokenizer fingerprint). Only used
  for models with that exact tokenizer.

Sources, in the order they are chosen for a model (unless the Owner pins one):

1. datasets the Owner uploaded in the dashboard (newest first);
2. the training coordinator's probe set, when the model's tokenizer matches;
3. a legacy ``data/eval/tokens.bin`` with matching tokenizer fingerprint;
4. the **built-in** text set: a fixed sample of the Python standard library source (PSF-2.0)
   from this server's own Python installation. It is always available, so evaluation is never
   blocked; the report notes when a model's training data may overlap with it.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sysconfig
import uuid
from pathlib import Path
from typing import Any

from moth_server.context import Ctx
from moth_server.db import now

MIN_TEXT_BYTES = 4 * 1024
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MIN_TOKENS = 2048
BUILTIN_ID = "builtin-python-stdlib"
# A fixed, ordered list so the built-in set is the same on every server with the same Python.
BUILTIN_FILES = ("textwrap.py", "string.py", "bisect.py", "heapq.py", "fnmatch.py", "colorsys.py", "shlex.py",
                 "glob.py", "difflib.py", "statistics.py", "queue.py", "netrc.py")
BUILTIN_MAX_BYTES = 192 * 1024


class EvalSetError(ValueError):
    pass


def root(ctx: Ctx) -> Path:
    d = ctx.settings.data_dir / "eval" / "datasets"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- validation ----------------------------------------------------------------------------------
def validate_text(data: bytes) -> list[str]:
    problems = []
    if len(data) < MIN_TEXT_BYTES:
        problems.append(f"the text is too short ({len(data)} bytes); provide at least {MIN_TEXT_BYTES // 1024} KB of "
                        "held-out text")
    if b"\x00" in data[:1 << 20]:
        problems.append("the file looks binary (contains NUL bytes); upload plain UTF-8 text")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as e:
        problems.append(f"the file is not valid UTF-8 text (byte {e.start})")
    return problems


def validate_tokens(path: Path, vocab_size: int | None = None) -> list[str]:
    import numpy as np

    size = path.stat().st_size
    if size % 4:
        return ["token files must contain little-endian uint32 ids (size is not a multiple of 4 bytes)"]
    n = size // 4
    if n < MIN_TOKENS:
        return [f"the token set is too small ({n} tokens); at least {MIN_TOKENS} are needed"]
    if vocab_size is not None:
        mx = int(np.fromfile(path, dtype=np.uint32, count=min(n, 1 << 20)).max())
        if mx >= vocab_size:
            return [f"token id {mx} is outside the tokenizer's vocabulary ({vocab_size})"]
    return []


# ---- sources -----------------------------------------------------------------------------------------
def _meta_path(d: Path) -> Path:
    return d / "meta.json"


def uploaded(ctx: Ctx) -> list[dict]:
    out = []
    for d in sorted(root(ctx).iterdir(), reverse=True):
        mp = _meta_path(d)
        if d.is_dir() and mp.exists():
            try:
                m = json.loads(mp.read_text())
            except ValueError:
                continue
            m["path"] = str(d / m["file"])
            m["valid"] = Path(m["path"]).exists() and _sha(Path(m["path"])) == m["sha256"]
            if not m["valid"]:
                m["problems"] = ["the stored file is missing or was modified (checksum mismatch)"]
            out.append(m)
    out.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return out


def coordinator_probe(ctx: Ctx) -> dict | None:
    from moth_server.training import coordinator_root

    croot = coordinator_root(ctx)
    probe, tokp = croot / "probe.bin", croot / "tokenizer.json"
    if not probe.exists():
        return None
    d = {"id": "coordinator-probe", "name": "Training network probe set", "kind": "tokens", "source": "coordinator",
         "path": str(probe), "sha256": _sha(probe), "tokens": probe.stat().st_size // 4, "license": "training data",
         "tokenizer_fingerprint": None, "valid": True}
    try:
        from moth.model.tokenizer import Tokenizer

        tok = Tokenizer.load(tokp)
        d["tokenizer_fingerprint"] = tok.fingerprint()
        problems = validate_tokens(probe, tok.vocab_size)
    except Exception as e:  # noqa: BLE001
        problems = [f"the coordinator tokenizer could not be read: {e}"]
    if problems:
        d.update(valid=False, problems=problems)
    return d


def legacy_tokens(ctx: Ctx) -> dict | None:
    p = ctx.settings.data_dir / "eval" / "tokens.bin"
    if not p.exists():
        return None
    meta = p.with_name("tokens.json")
    fp = None
    if meta.exists():
        try:
            fp = json.loads(meta.read_text()).get("tokenizer_fingerprint")
        except ValueError:
            pass
    d = {"id": "legacy-tokens", "name": "data/eval/tokens.bin", "kind": "tokens", "source": "legacy", "path": str(p),
         "sha256": _sha(p), "tokens": p.stat().st_size // 4, "tokenizer_fingerprint": fp, "valid": True}
    problems = validate_tokens(p)
    if not fp:
        problems.append("its tokenizer is unknown — add data/eval/tokens.json with 'tokenizer_fingerprint', or upload "
                        "a text dataset instead")
    if problems:
        d.update(valid=False, problems=problems)
    return d


def builtin(ctx: Ctx) -> dict | None:
    """Materialise the built-in text set once (deterministic content) and describe it."""
    out = ctx.settings.data_dir / "eval" / "builtin" / "python-stdlib.txt"
    if not out.exists():
        stdlib = Path(sysconfig.get_paths()["stdlib"])
        parts, total = [], 0
        for name in BUILTIN_FILES:
            p = stdlib / name
            if p.exists() and total < BUILTIN_MAX_BYTES:
                text = p.read_text(encoding="utf-8", errors="replace")
                parts.append(f"# ---- {name} ----\n{text}")
                total += len(text.encode())
        if not parts:
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        data = "\n".join(parts).encode()[:BUILTIN_MAX_BYTES].decode("utf-8", errors="ignore")
        out.write_text(data, encoding="utf-8")
    return {"id": BUILTIN_ID, "name": "Built-in: Python standard library sample", "kind": "text", "source": "builtin",
            "path": str(out), "sha256": _sha(out), "bytes": out.stat().st_size, "license": "PSF-2.0",
            "valid": not validate_text(out.read_bytes()),
            "note": "Always available. If a model was trained on Python standard library code, upload your own "
                    "held-out text for a fairer score."}


def all_datasets(ctx: Ctx) -> list[dict]:
    pinned = ctx.db.get_config("eval_dataset_pinned")
    items = [d for d in (*uploaded(ctx), coordinator_probe(ctx), legacy_tokens(ctx), builtin(ctx)) if d]
    for d in items:
        d["pinned"] = d["id"] == pinned
        d.setdefault("problems", [])
    return items


def public(d: dict) -> dict:
    return {k: v for k, v in d.items() if k != "path"}


# ---- selection ---------------------------------------------------------------------------------------
def compatible(d: dict, tokenizer_fingerprint: str | None) -> tuple[bool, str]:
    if not d.get("valid"):
        return False, "; ".join(d.get("problems") or ["dataset is not valid"])
    if d["kind"] == "tokens":
        if not d.get("tokenizer_fingerprint"):
            return False, "token dataset has no known tokenizer"
        if d["tokenizer_fingerprint"] != tokenizer_fingerprint:
            return False, "token dataset was made with a different tokenizer than this model"
    return True, ""


def select_for(ctx: Ctx, tokenizer_fingerprint: str | None) -> tuple[dict | None, list[dict]]:
    """The dataset to evaluate a model with, plus why each other candidate was skipped."""
    skipped = []
    items = all_datasets(ctx)
    pinned = [d for d in items if d["pinned"]]
    for d in pinned + [d for d in items if not d["pinned"]]:
        ok, why = compatible(d, tokenizer_fingerprint)
        if ok:
            return d, skipped
        skipped.append({"id": d["id"], "name": d["name"], "reason": why})
    return None, skipped


# ---- Owner management ----------------------------------------------------------------------------------
def add(ctx: Ctx, name: str, filename: str, src: Path, kind: str, license_: str, tokenizer_fingerprint: str | None,
        actor_id: int) -> dict:
    from moth_server.audit import audit

    if kind not in ("text", "tokens"):
        raise EvalSetError("kind must be 'text' or 'tokens'")
    size = src.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise EvalSetError(f"the file is too large ({size // 2**20} MB); the limit is {MAX_UPLOAD_BYTES // 2**20} MB")
    if kind == "text":
        problems = validate_text(src.read_bytes())
    else:
        if not tokenizer_fingerprint or not re.fullmatch(r"[0-9a-f]{8,64}", tokenizer_fingerprint):
            raise EvalSetError("token datasets need the tokenizer fingerprint they were made with")
        problems = validate_tokens(src)
    if problems:
        raise EvalSetError("; ".join(problems))
    sha = _sha(src)
    for d in uploaded(ctx):
        if d["sha256"] == sha:
            raise EvalSetError(f"this dataset was already uploaded as '{d['name']}'")
    did = f"{int(now())}-{uuid.uuid4().hex[:8]}"
    dest = root(ctx) / did
    dest.mkdir(parents=True)
    fname = "text.txt" if kind == "text" else "tokens.bin"
    shutil.move(str(src), dest / fname)
    meta = {"id": did, "name": name.strip()[:128] or filename[:128], "kind": kind, "source": "uploaded",
            "file": fname, "original_filename": filename[:200], "sha256": sha, "license": license_.strip()[:64],
            "tokenizer_fingerprint": tokenizer_fingerprint if kind == "tokens" else None, "created_at": now(),
            "created_by": actor_id, ("bytes" if kind == "text" else "tokens"): size if kind == "text" else size // 4}
    _meta_path(dest).write_text(json.dumps(meta, indent=2))
    audit(ctx.db, "eval_datasets.added", actor_id, f"eval_dataset:{did}", {"name": meta["name"], "kind": kind,
                                                                            "sha256": sha})
    return {**meta, "valid": True, "problems": [], "pinned": False}


def remove(ctx: Ctx, did: str, actor_id: int) -> None:
    from moth_server.audit import audit

    if not re.fullmatch(r"[0-9]+-[0-9a-f]{8}", did) or not (root(ctx) / did).is_dir():
        raise EvalSetError("only uploaded datasets can be removed")
    shutil.rmtree(root(ctx) / did)
    if ctx.db.get_config("eval_dataset_pinned") == did:
        ctx.db.set_config("eval_dataset_pinned", None)
    audit(ctx.db, "eval_datasets.removed", actor_id, f"eval_dataset:{did}")


def pin(ctx: Ctx, did: str | None, actor_id: int) -> None:
    from moth_server.audit import audit

    if did and did not in {d["id"] for d in all_datasets(ctx)}:
        raise EvalSetError("unknown dataset")
    ctx.db.set_config("eval_dataset_pinned", did)
    audit(ctx.db, "eval_datasets.pinned", actor_id, f"eval_dataset:{did}")


def spec(d: dict) -> dict[str, Any]:
    """What the evaluation subprocess needs."""
    return {k: d.get(k) for k in ("id", "name", "kind", "path", "sha256", "source", "tokenizer_fingerprint")}
