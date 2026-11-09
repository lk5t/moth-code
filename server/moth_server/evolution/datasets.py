"""Approved training data: the only data model evolution may train on.

A training dataset is a prepared token dataset (``moth.training.data`` format: ``train.bin``,
``val.bin``, masks and ``meta.json`` listing every source with its license). It is **pending** until
the Owner approves it; only **approved** datasets are used. A dataset that contains user data
(conversations, user files) additionally needs the Owner to confirm that the users gave explicit
permission. MOTH never adds conversations, credentials or workspace files to training data by itself:
data only enters through this registry. Secret-looking files are skipped when a dataset is built from
files (``moth.training.sources``), and only ids, hashes, licenses and token counts are ever recorded or
shown — never the contents.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import zipfile
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select

from moth_server.audit import audit
from moth_server.context import Ctx
from moth_server.db import now, training_datasets

MAX_UPLOAD = 512 * 1024**2


class DatasetError(ValueError):
    pass


def root(ctx: Ctx) -> Path:
    p = ctx.settings.data_dir / "evolution" / "datasets"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def public(d: dict) -> dict:
    out = {k: d.get(k) for k in ("id", "name", "sha256", "tokens_train", "tokens_val", "tokenizer_fingerprint",
                                 "license", "contains_user_data", "status", "approved_by", "approved_at",
                                 "created_at", "revoked_at")}
    for k in ("sources", "tags"):
        v = d.get(k)
        out[k] = json.loads(v) if isinstance(v, str) else (v or [])
    # sources carry only the spec kind and license, never paths that could reveal private content
    out["sources"] = [{"kind": str(s.get("spec", "")).split(":", 1)[0], "license": s.get("license"),
                       "tokens": s.get("tokens")} for s in out["sources"] if isinstance(s, dict)]
    return out


def get(ctx: Ctx, did: int) -> dict | None:
    return ctx.db.one(select(training_datasets).where(training_datasets.c.id == did))


def all_(ctx: Ctx) -> list[dict]:
    return ctx.db.all(select(training_datasets).order_by(training_datasets.c.id))


def approved(ctx: Ctx, tokenizer_fingerprint: str | None = None) -> list[dict]:
    rows = ctx.db.all(select(training_datasets).where(training_datasets.c.status == "approved")
                      .order_by(training_datasets.c.id))
    return [r for r in rows if tokenizer_fingerprint is None or r["tokenizer_fingerprint"] == tokenizer_fingerprint]


def inspect(ds_dir: Path) -> dict[str, Any]:
    """Validate a prepared dataset directory and summarise it (no contents are read beyond counts)."""
    meta_p = ds_dir / "meta.json"
    if not meta_p.exists():
        raise DatasetError("not a prepared MOTH dataset: meta.json is missing")
    meta = json.loads(meta_p.read_text())
    for f in ("train.bin", "val.bin"):
        if not (ds_dir / f).exists():
            raise DatasetError(f"the dataset is incomplete: {f} is missing")
    sources = meta.get("sources") or []
    if not sources or any(not str(s.get("license", "")).strip() for s in sources):
        raise DatasetError("every source of a training dataset must declare its license")
    itemsize = 2 if meta.get("dtype") == "uint16" else 4
    tokens_train = (ds_dir / "train.bin").stat().st_size // itemsize
    tokens_val = (ds_dir / "val.bin").stat().st_size // itemsize
    if tokens_val < 300:
        raise DatasetError(f"the validation split is too small to evaluate on ({tokens_val} tokens; need ≥ 300)")
    return {"meta": meta, "tokens_train": int(tokens_train), "tokens_val": int(tokens_val),
            "sha256": _sha(ds_dir / "train.bin"),
            "license": ", ".join(sorted({str(s["license"]) for s in sources}))}


def _insert(ctx: Ctx, name: str, ds_dir: Path, info: dict, tags: list[str], contains_user_data: bool,
            actor_id: int | None) -> dict:
    dup = ctx.db.one(select(training_datasets).where(training_datasets.c.sha256 == info["sha256"],
                                                     training_datasets.c.status != "revoked"))
    if dup:
        raise DatasetError(f"this data is already registered as dataset #{dup['id']} ({dup['name']})")
    with ctx.db.tx() as c:
        res = c.execute(training_datasets.insert().values(
            name=name[:128], path=str(ds_dir), sha256=info["sha256"], tokens_train=info["tokens_train"],
            tokens_val=info["tokens_val"], tokenizer_fingerprint=info["meta"]["tokenizer_fingerprint"],
            license=info["license"][:2000],
            sources=json.dumps([{"spec": s.get("spec"), "license": s.get("license"), "tokens": s.get("tokens")}
                                for s in info["meta"].get("sources", [])]),
            tags=json.dumps(sorted({t.strip().lower()[:24] for t in tags if t.strip()})),
            contains_user_data=bool(contains_user_data), status="pending", created_by=actor_id, created_at=now()))
        did = res.inserted_primary_key[0]
        audit(ctx.db, "evolution.dataset_registered", actor_id, f"dataset:{did}",
              {"tokens": info["tokens_train"], "license": info["license"][:200], "user_data": contains_user_data}, conn=c)
    return get(ctx, did)


def register_prepared(ctx: Ctx, src_dir: Path, name: str, tags: list[str], contains_user_data: bool,
                      actor_id: int | None) -> dict:
    """Register a dataset prepared on the server (``moth prepare``), copied into MOTH's storage."""
    src_dir = Path(src_dir).resolve()
    info = inspect(src_dir)
    dest = root(ctx) / f"ds-{info['sha256'][:16]}-{uuid.uuid4().hex[:8]}"
    if dest.resolve() != src_dir:
        shutil.rmtree(dest, ignore_errors=True)
        shutil.copytree(src_dir, dest)
        tok = Path(info["meta"].get("tokenizer_path", ""))
        if tok.exists():  # keep the tokenizer with the data so training never depends on another path
            shutil.copy2(tok, dest / "tokenizer.json")
            meta = {**info["meta"], "tokenizer_path": str(dest / "tokenizer.json")}
            (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    return _insert(ctx, name, dest, inspect(dest), tags, contains_user_data, actor_id)


def _extract(upload: Path, filename: str, dest: Path) -> None:
    from moth_server.models import safe_extract

    low = filename.lower()
    if low.endswith((".tar.gz", ".tgz", ".tar")):
        safe_extract(upload, dest)
    elif low.endswith(".zip"):
        with zipfile.ZipFile(upload) as z:
            for m in z.infolist():
                p = (dest / m.filename).resolve()
                if dest.resolve() not in p.parents and p != dest.resolve():
                    raise DatasetError("the archive contains unsafe paths")
            z.extractall(dest)
    else:
        name = Path(filename).name or "data.txt"
        shutil.copyfile(upload, dest / name)


def create_from_files(ctx: Ctx, upload: Path, filename: str, name: str, license_: str, tags: list[str],
                      contains_user_data: bool, tokenizer_dir: Path, actor_id: int | None) -> dict:
    """Build a training dataset from uploaded text/code (a file, .zip or .tar.gz) with the tokenizer of
    the model it will train (normally the deployed model)."""
    from moth.model.tokenizer import Tokenizer
    from moth.training.data import prepare_dataset

    if not license_.strip():
        raise DatasetError("declare the license under which you may use this data for training")
    if upload.stat().st_size > MAX_UPLOAD:
        raise DatasetError(f"uploads are limited to {MAX_UPLOAD // 1024**2} MB; prepare larger datasets on the server")
    tok_path = tokenizer_dir / "tokenizer.json"
    tok = Tokenizer.load(tok_path)
    with tempfile.TemporaryDirectory(prefix="moth-ds-", dir=root(ctx)) as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        try:
            _extract(upload, filename, src)
        except (OSError, tarfile.TarError, zipfile.BadZipFile):
            raise DatasetError(f"{Path(filename).name}: unreadable or invalid upload archive") from None
        out = Path(tmp) / "prepared"
        try:
            prepare_dataset([{"spec": f"dir:{src}", "license": license_.strip()}], tok, tok_path, out)
        except ValueError as e:
            raise DatasetError(str(e)) from None
        shutil.copy2(tok_path, out / "tokenizer.json")
        meta = json.loads((out / "meta.json").read_text())
        meta["tokenizer_path"] = "tokenizer.json"
        # the source path was a temporary upload folder: keep only the kind and license
        for s in meta.get("sources", []):
            s["spec"] = "upload:" + Path(filename).name[:80]
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        info = inspect(out)
        dest = root(ctx) / f"ds-{info['sha256'][:16]}-{uuid.uuid4().hex[:8]}"
        if any(r["sha256"] == info["sha256"] and r["status"] != "revoked" for r in all_(ctx)):
            raise DatasetError("this data is already registered")
        shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(out), dest)
    meta = json.loads((dest / "meta.json").read_text())
    meta["tokenizer_path"] = str(dest / "tokenizer.json")
    (dest / "meta.json").write_text(json.dumps(meta, indent=2))
    return _insert(ctx, name, dest, inspect(dest), tags, contains_user_data, actor_id)


def approve(ctx: Ctx, did: int, actor_id: int, user_data_permission: bool = False) -> dict:
    d = get(ctx, did)
    if not d:
        raise DatasetError("unknown dataset")
    if d["status"] == "revoked":
        raise DatasetError("a revoked dataset cannot be approved again; register it again")
    if d["contains_user_data"] and not user_data_permission:
        raise DatasetError("this dataset contains user data: confirm that the users gave explicit permission "
                           "to train on it")
    with ctx.db.tx() as c:
        c.execute(training_datasets.update().where(training_datasets.c.id == did)
                  .values(status="approved", approved_by=actor_id, approved_at=now()))
        audit(ctx.db, "evolution.dataset_approved", actor_id, f"dataset:{did}",
              {"user_data_permission": bool(user_data_permission)}, conn=c)
    return get(ctx, did)


def revoke(ctx: Ctx, did: int, actor_id: int) -> dict:
    """Stop using a dataset for new experiments (models already trained on it are kept)."""
    d = get(ctx, did)
    if not d:
        raise DatasetError("unknown dataset")
    with ctx.db.tx() as c:
        c.execute(training_datasets.update().where(training_datasets.c.id == did)
                  .values(status="revoked", revoked_at=now()))
        audit(ctx.db, "evolution.dataset_revoked", actor_id, f"dataset:{did}", conn=c)
    return get(ctx, did)


def meta(d: dict) -> dict:
    return json.loads((Path(d["path"]) / "meta.json").read_text())


def val_suite(d: dict) -> dict[str, Any]:
    """The dataset's validation split as a held-out benchmark (retention of what was learned)."""
    m = meta(d)
    return {"kind": "tokens", "path": str(Path(d["path"]) / "val.bin"), "dtype": m.get("dtype", "uint32"),
            "tokenizer_fingerprint": d["tokenizer_fingerprint"], "sha256": d["sha256"]}


def write_shard(d: dict, dest: Path, max_tokens: int = 32 * 1024 * 1024) -> str:
    """The training split as uint32 tokens for MOTH workers (their wire format); returns its SHA-256."""
    import numpy as np

    m = meta(d)
    tokens = np.fromfile(Path(d["path"]) / "train.bin", dtype=np.dtype(m.get("dtype", "uint32")))[:max_tokens]
    dest.parent.mkdir(parents=True, exist_ok=True)
    tokens.astype(np.uint32).tofile(dest)
    return _sha(dest)


def tar_ok(path: Path) -> bool:
    try:
        return tarfile.is_tarfile(path)
    except OSError:
        return False
