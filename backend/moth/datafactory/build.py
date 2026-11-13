"""Build a reproducible training corpus from the approved library.

``build(cache, out)``:

1. downloads (once) and verifies every catalog file;
2. pass 1 — collects held-out evaluation items (``role: eval`` files) and a deterministic holdout slice
   of every training source (by hash of the record id); these seed the decontaminator and deduplicator;
3. pass 2 — normalises, scrubs, quality-scores, decontaminates and deduplicates the training records,
   writing ``domains/<domain>.jsonl``;
4. writes ``manifest.json``: factory version, pinned sources and file hashes, every filter's counts,
   per-domain sizes and a content hash of the result. The same catalog + config gives the same corpus.

``tokenize_build(build_dir, tokenizer, tokenizer_path)`` turns the corpus into memory-mapped token files
(``tokens/<domain>/``, holdout = validation split) plus ``mixture.json`` that the trainer samples from.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from moth.datafactory import catalog, clean, fetch, parse

FACTORY_VERSION = 1

DEFAULT_CONFIG: dict[str, Any] = {
    "holdout_fraction": 0.02,
    "holdout_overrides": {"simple-wikipedia": 0.005, "python-stdlib": 0.01},
    "min_quality": {"language": 0.5, "conversation": 0.45, "knowledge": 0.5, "writing": 0.45, "math": 0.5,
                    "reasoning": 0.5, "code": 0.55},
    "min_words": {"knowledge": 40},
    "max_chars": {"simple-wikipedia": 60_000_000, "python-stdlib": 24_000_000},  # balance: no domain floods
    "near_dedupe": True,
    "sources": [s["id"] for s in catalog.SOURCES],
}


def _holdout(uid: str, frac: float) -> bool:
    return int(hashlib.sha1(uid.encode()).hexdigest()[:8], 16) % 100_000 < frac * 100_000


def _clean_record(rec: dict[str, Any]) -> tuple[dict[str, Any], int]:
    n = 0
    if "messages" in rec:
        msgs = []
        for m in rec["messages"]:
            text, k = clean.scrub(clean.normalize(m["content"]))
            n += k
            msgs.append({"role": m["role"], "content": text})
        return {**rec, "messages": msgs}, n
    text = clean.normalize(rec["text"])
    text, n = clean.scrub(text)  # credentials and personal data must be filtered in code too
    return {**rec, "text": text}, n


def build(cache: Path, out: Path, config: dict[str, Any] | None = None,
          log: Callable[[str], None] = print, extra_sources: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    cache, out = Path(cache), Path(out)
    tmp = out.with_name(out.name + ".building")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "domains").mkdir(parents=True)
    (tmp / "eval").mkdir()
    pins = cfg.get("pins") or {}
    # 0.9.0: a sharded source downloads only the shards its character budget needs
    sources = [catalog.limited(catalog.with_pin(catalog.source(s), pins.get(s)), cfg["max_chars"].get(s))
               for s in cfg["sources"]]
    # extra local sources (e.g. Owner-approved feedback): {"id", "name", "license", "attribution", "records"}
    extras = [{"id": e["id"], "name": e["name"], "domain": e.get("domain", "conversation"), "repo": None,
               "revision": None, "format": "records", "license": e["license"], "license_url": e.get("license_url", ""),
               "attribution": e.get("attribution", e["name"]), "files": [], "records": e["records"]}
              for e in (extra_sources or [])]
    sources += extras
    files: dict[str, list[tuple[dict, Path]]] = {}
    for src in sources:
        files[src["id"]] = fetch.fetch_source(cache, src, log=log) if src["files"] else []

    stats: dict[str, dict[str, int]] = {}
    eval_counts: dict[str, int] = {}
    holdout_counts: dict[str, int] = {}
    dedupe = clean.Deduper()
    eval_texts: list[str] = []

    def frac(sid: str) -> float:
        return cfg["holdout_overrides"].get(sid, cfg["holdout_fraction"])

    def records(src):
        if src["format"] == "records":
            yield from src["records"]
            return
        if src["format"] == "synthetic":
            # 0.9.0: MOTH's own verified data grows with the library budget (about 200 characters per example;
            # repeats are removed by the deduplicator), up to 2 million examples per generator (100,000
            # where every example is executed)
            cap = cfg["max_chars"].get(src["id"])
            most = 100_000 if src.get("kind") in ("python", "debugging", "code_explain", "test_writing") else 2_000_000
            n = max(int(src.get("count", 1000)), min(most, int(cap or 0) // 200))  # executed kinds: fewer
            yield from parse.train_records({**src, "count": n}, {"path": ""}, Path("."))
            return
        if src["format"] == "stdlib":
            excluded = set(cfg.get('excluded_stdlib_files') or [])
            for rec in parse.train_records(src, {"path": ""}, Path(".")):
                if rec['uid'].split(':', 1)[-1] not in excluded:
                    yield rec
            return
        # 0.9.0: stop reading once enough text was read for the budget (both passes read the same records,
        # so holdout and training stay disjoint); large sources are never read to the end needlessly
        cap = cfg["max_chars"].get(src["id"])
        limit = int(cap / max(0.05, 1 - frac(src["id"])) * 2) if cap else None
        read = 0
        for f, path in files[src["id"]]:
            if f["role"] != "train":
                continue
            for rec in parse.train_records(src, f, path):
                yield rec
                if limit:
                    read += len(clean.record_text(rec))
                    if read >= limit:
                        return

    # ---- pass 1: evaluation items and holdouts ---------------------------------------------------------
    eval_out = {}
    for src in sources:
        for f, path in files[src["id"]]:
            if f["role"] != "eval":
                continue
            for item in parse.eval_items(src, f, path):
                suite = item["suite"]
                if suite not in eval_out:
                    eval_out[suite] = open(tmp / "eval" / f"{suite}.jsonl", "w", encoding="utf-8")
                eval_out[suite].write(json.dumps(item) + "\n")
                eval_counts[suite] = eval_counts.get(suite, 0) + 1
                # benchmark prompts and tests (not reference code: common code phrases are not leaks)
                eval_texts.append(item["prompt"] + "\n" + "\n".join(item.get("tests") or []))
    holdout_out = {}
    for src in sources:
        for rec in records(src):
            if not _holdout(rec["uid"], frac(src["id"])):
                continue
            rec, _ = _clean_record(rec)
            text = clean.record_text(rec)
            if not text.strip():
                continue
            dedupe.check(text, near=cfg["near_dedupe"])
            d = rec["domain"]
            if d not in holdout_out:
                holdout_out[d] = open(tmp / "eval" / f"holdout_{d}.jsonl", "w", encoding="utf-8")
            holdout_out[d].write(json.dumps(rec) + "\n")
            holdout_counts[d] = holdout_counts.get(d, 0) + 1  # kept out of training by the deduplicator
    for fh in list(eval_out.values()) + list(holdout_out.values()):
        fh.close()
    decon = clean.Decontaminator(eval_texts)
    log(f"evaluation items: {eval_counts}; holdout records: {holdout_counts}")

    # ---- pass 2: training records ------------------------------------------------------------------------
    domain_out: dict[str, Any] = {}
    domain_stats: dict[str, dict[str, int]] = {}
    digest = hashlib.sha256()
    for src in sources:
        st = stats.setdefault(src["id"], {"read": 0, "kept": 0, "holdout": 0, "chars": 0, "pii_redactions": 0})
        cap = cfg["max_chars"].get(src["id"])
        t0 = time.time()
        for rec in records(src):
            st["read"] += 1
            if _holdout(rec["uid"], frac(src["id"])):
                st["holdout"] += 1
                continue
            if cap and st["chars"] >= cap:
                st["over_budget"] = st.get("over_budget", 0) + 1
                continue
            rec, redactions = _clean_record(rec)
            text = clean.record_text(rec)
            d = rec["domain"]
            score, why = clean.quality(rec)
            if why is None and "text" in rec and len(clean.words(text)) < cfg["min_words"].get(d, 0):
                why = "too_short"
            if why is None and score < cfg["min_quality"].get(d, 0.5):
                why = "low_quality"
            if why is None and decon.contaminated(text):
                why = "eval_overlap"
            if why is None:
                why = {"exact": "duplicate", "near": "near_duplicate"}.get(
                    dedupe.check(text, near=cfg["near_dedupe"] and d != "code") or "", None)
            if why:
                st[why] = st.get(why, 0) + 1
                continue
            rec["quality"] = score
            line = json.dumps(rec, ensure_ascii=False) + "\n"
            if d not in domain_out:
                domain_out[d] = open(tmp / "domains" / f"{d}.jsonl", "w", encoding="utf-8")
            domain_out[d].write(line)
            digest.update(line.encode())
            st["kept"] += 1
            st["chars"] += len(text)
            st["pii_redactions"] += redactions
            ds = domain_stats.setdefault(d, {"records": 0, "chars": 0})
            ds["records"] += 1
            ds["chars"] += len(text)
        log(f"{src['id']}: kept {st['kept']} of {st['read']} in {time.time() - t0:.0f}s "
            f"({ {k: v for k, v in st.items() if k not in ('read', 'kept', 'chars')} })")
    for fh in domain_out.values():
        fh.close()

    manifest = {
        "factory_version": FACTORY_VERSION, "created": time.time(), "config": cfg,
        "sources": [{"id": s["id"], "name": s["name"], "domain": s["domain"], "license": s["license"],
                     "license_url": s["license_url"], "attribution": s["attribution"], "revision": s["revision"],
                     "files": [{"path": f["path"], "sha256": f["sha256"], "size": f["size"], "role": f["role"]}
                               for f in s["files"]], "stats": stats.get(s["id"], {})} for s in sources],
        "domains": domain_stats, "eval_items": eval_counts, "holdout_records": holdout_counts,
        "content_sha256": digest.hexdigest(), "factory_config": {k: v for k, v in cfg.items() if k != "pins"},
    }
    (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (tmp / "ATTRIBUTION.md").write_text(attribution(manifest))
    if out.exists():
        shutil.rmtree(out)
    os.replace(tmp, out)
    return manifest


def attribution(manifest: dict[str, Any]) -> str:
    lines = ["# Training data attribution", "",
             "This model was trained on the following datasets. Their licenses' attribution and share-alike",
             "terms apply where relevant.", ""]
    for s in manifest["sources"]:
        lines.append(f"- **{s['name']}** — {s['attribution']}. License: {s['license']} ({s['license_url']})"
                     + (f"; revision `{s['revision'][:12]}`" if s.get("revision") else ""))
    return "\n".join(lines) + "\n"


def _iter_jsonl(path: Path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def iter_texts(build_dir: Path, per_domain_chars: int = 8_000_000):
    """A balanced text sample for tokenizer training (every domain contributes)."""
    for p in sorted((Path(build_dir) / "domains").glob("*.jsonl")):
        n = 0
        for rec in _iter_jsonl(p):
            t = clean.record_text(rec)
            yield t
            n += len(t)
            if n >= per_domain_chars:
                break


def _encode(tok, rec: dict[str, Any]) -> tuple[list[int], list[int]]:
    from moth.model.chat_format import Message, encode_chat

    if "messages" in rec:
        ids, mask = encode_chat(tok, [Message(m["role"], m["content"]) for m in rec["messages"]],
                                add_generation_prompt=False)
    else:
        ids = tok.encode(rec["text"])
        mask = [1] * len(ids)
    return ids + [tok.eos_id], mask + [1]


# ---- chunked preparation (0.7.2): identical on MOTH Cloud and on workers -------------------------------
def record_hash(rec: dict[str, Any]) -> bytes:
    """16-byte identity of a record's text (whitespace-normalised) for exact deduplication."""
    import hashlib

    return hashlib.sha256(" ".join(clean.record_text(rec).split()).encode("utf-8")).digest()[:16]


def encode_chunk(tok, path: Path) -> dict[str, np.ndarray]:
    """Tokenize one chunk of records: concatenated ids and loss mask, per-record offsets and text hashes.

    The same function runs on MOTH Cloud and on workers, so a worker's output can be checked by
    re-encoding any of its records (tokenization is deterministic)."""
    ids_all: list[int] = []
    mask_all: list[int] = []
    offsets = [0]
    hashes = bytearray()
    for rec in _iter_jsonl(Path(path)):
        ids, mask = _encode(tok, rec)
        ids_all += ids
        mask_all += mask
        offsets.append(len(ids_all))
        hashes += record_hash(rec)
    return {"ids": np.asarray(ids_all, dtype=np.uint32), "mask": np.asarray(mask_all, dtype=np.uint8),
            "offsets": np.asarray(offsets, dtype=np.int64),
            "hashes": np.frombuffer(bytes(hashes), dtype=np.uint8).reshape(-1, 16) if hashes else np.zeros((0, 16), np.uint8)}


def chunk_bytes(arrays: dict[str, np.ndarray]) -> bytes:
    import io

    buf = io.BytesIO()
    np.savez(buf, **arrays)
    return buf.getvalue()


def load_chunk(data: bytes) -> dict[str, np.ndarray]:
    import io

    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        return {k: z[k] for k in ("ids", "mask", "offsets", "hashes")}


def split_records(src: Path, dest_dir: Path, per_chunk: int) -> list[Path]:
    """Split a domain's JSONL into chunks of ``per_chunk`` records (in order)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    out: list[Path] = []
    fh = None
    n = 0
    with open(src, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if fh is None or n >= per_chunk:
                if fh:
                    fh.close()
                p = dest_dir / f"{src.stem}-{len(out):05d}.jsonl"
                out.append(p)
                fh = open(p, "w", encoding="utf-8")
                n = 0
            fh.write(line if line.endswith("\n") else line + "\n")
            n += 1
    if fh:
        fh.close()
    return out


def tokenize_build(build_dir: Path, tok, tokenizer_path: Path, out: Path | None = None,
                   log: Callable[[str], None] = print,
                   train_chunks: dict[str, list[dict[str, np.ndarray]]] | None = None) -> dict[str, Any]:
    """Tokenize a build. Exact duplicate records (same normalised text) are written once.

    ``train_chunks``: per domain, already-encoded chunks of its training records in order (from
    ``encode_chunk``, e.g. prepared by workers and verified); other domains are encoded here."""
    build_dir = Path(build_dir)
    out = Path(out or build_dir / "tokens")
    manifest = json.loads((build_dir / "manifest.json").read_text())
    dtype = np.uint16 if tok.vocab_size <= 65535 else np.uint32
    licenses: dict[str, set[str]] = {}
    for s in manifest["sources"]:
        licenses.setdefault(s["domain"], set()).add(s["license"])
    mixture: dict[str, Any] = {"format": 1, "tokenizer_fingerprint": tok.fingerprint(),
                               "tokenizer_path": str(Path(tokenizer_path).resolve()),
                               "build_sha256": manifest["content_sha256"], "domains": {}}
    for p in sorted((build_dir / "domains").glob("*.jsonl")):
        d = p.stem
        ddir = out / d
        ddir.mkdir(parents=True, exist_ok=True)
        counts = {}
        duplicates = 0
        for split, src in (("train", p), ("val", build_dir / "eval" / f"holdout_{d}.jsonl")):
            n = 0
            seen: set[bytes] = set()
            with open(ddir / f"{split}.bin.tmp", "wb") as fb, open(ddir / f"{split}.mask.tmp", "wb") as fm:
                if split == "train" and train_chunks and d in train_chunks:
                    for ch in train_chunks[d]:
                        offs = ch["offsets"]
                        for r in range(len(offs) - 1):
                            h = bytes(ch["hashes"][r])
                            if h in seen:
                                duplicates += 1
                                continue
                            seen.add(h)
                            a, b = int(offs[r]), int(offs[r + 1])
                            fb.write(ch["ids"][a:b].astype(dtype).tobytes())
                            fm.write(ch["mask"][a:b].tobytes())
                            n += b - a
                elif src.exists():
                    for rec in _iter_jsonl(src):
                        h = record_hash(rec)
                        if h in seen:
                            duplicates += split == "train"
                            continue
                        seen.add(h)
                        ids, mask = _encode(tok, rec)
                        fb.write(np.asarray(ids, dtype=dtype).tobytes())
                        fm.write(np.asarray(mask, dtype=np.uint8).tobytes())
                        n += len(ids)
            counts[split] = n
        if counts["val"] < 64:  # tiny domains: carve validation from the end of train
            tr = np.fromfile(ddir / "train.bin.tmp", dtype=dtype)
            mk = np.fromfile(ddir / "train.mask.tmp", dtype=np.uint8)
            k = max(64, len(tr) // 50)
            tr[-k:].tofile(ddir / "val.bin.tmp")
            mk[-k:].tofile(ddir / "val.mask.tmp")
            tr[:-k].tofile(ddir / "train.bin.tmp")
            mk[:-k].tofile(ddir / "train.mask.tmp")
            counts = {"train": len(tr) - k, "val": k}
        for split in ("train", "val"):
            for kind in ("bin", "mask"):
                os.replace(ddir / f"{split}.{kind}.tmp", ddir / f"{split}.{kind}")
        meta = {"format": 1, "created": time.time(), "dtype": np.dtype(dtype).name,
                "tokenizer_path": mixture["tokenizer_path"], "tokenizer_fingerprint": tok.fingerprint(),
                "vocab_size": tok.vocab_size, "tokens": counts, "domain": d,
                "sources": [{"spec": f"factory:{s['id']}", "license": s["license"]}
                            for s in manifest["sources"] if s["domain"] == d or d in _domains_of(s)]}
        (ddir / "meta.json").write_text(json.dumps(meta, indent=1))
        mixture["domains"][d] = {"dir": d, "tokens": counts, "duplicates_removed": duplicates,
                                 "prepared_by": "workers" if train_chunks and d in train_chunks else "server"}
        log(f"tokenized {d}: {counts['train']:,} train / {counts['val']:,} val tokens"
            + (f", {duplicates} duplicate record(s) removed" if duplicates else ""))
    (out / "mixture.json").write_text(json.dumps(mixture, indent=1))
    return mixture


def _domains_of(src: dict[str, Any]) -> set[str]:
    if src["id"] == "dolly-15k":
        return set(catalog.DOLLY_DOMAINS.values())
    return {src["domain"]}
