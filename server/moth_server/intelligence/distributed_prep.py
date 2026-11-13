"""Dataset preparation on workers (0.7.2): tokenization and deduplication hashing, verified and merged.

When a library build is tokenized and compatible workers are online, each public domain's training
records are split into chunks of ``CHUNK_RECORDS`` and offered as ``prep_tokenize`` jobs. A worker
downloads the chunk and the lineage's tokenizer (both checked by SHA-256), encodes every record with
the same code MOTH Cloud uses (``moth.datafactory.build.encode_chunk``) and returns the token ids, loss
mask, per-record offsets and a 16-byte hash of each record's text.

MOTH Cloud never trusts that output blindly: tokenization is deterministic, so it re-encodes the first,
the last and several random records of the chunk and compares ids, masks and hashes exactly; the
structure (record count, monotonic offsets, lengths) is checked too. Anything else is refused and the
chunk is prepared on MOTH Cloud instead. MOTH Cloud also works on the queue itself (work stealing): it
takes chunks nobody has claimed, and after ``WAIT_SECONDS`` it prepares whatever is still outstanding,
so a slow or vanished worker never delays a build. Exact duplicates are removed when the chunks are
merged in their original order — the merged result is the same whoever prepared each chunk.

Only domains whose sources are all public licensed data are sent to workers; user-consented feedback
is always prepared on MOTH Cloud.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import now, training_jobs, workers

CHUNK_RECORDS = 2000
MIN_WORKER_VERSION = "0.7.2"
WAIT_SECONDS = 900.0
HEAD_START = 5.0  # seconds a fresh chunk is left to the workers before MOTH Cloud may take it
SPOT_CHECKS = 4


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def eligible_workers(ctx: Ctx) -> list[dict]:
    from moth_server.training import version_at_least, worker_allowed

    s = (ctx.db.get_config("evolution_settings", {}) or {})
    if (s.get("backends") or {}).get("workers") is False or (s.get("distributed") or {}).get("prepare_on_workers") is False:
        return []
    t = now()
    return [w for w in ctx.db.all(select(workers).where(workers.c.revoked_at.is_(None)))
            if (w["last_heartbeat_at"] or 0) >= t - 180 and not w["paused"] and worker_allowed(ctx, w)
            and version_at_least(w["version"], MIN_WORKER_VERSION)]


def public_domains(manifest: dict) -> set[str]:
    from moth.datafactory.build import _domains_of

    private: set[str] = set()
    every: set[str] = set()
    for s in manifest.get("sources", []):
        doms = {s.get("domain")} | _domains_of(s)
        every |= doms
        if s.get("id") == "feedback" or s.get("license") == "user-consented":
            private |= doms
    return {d for d in every if d} - private


def _encode_local(tok, chunk: Path) -> dict:
    from moth.datafactory.build import encode_chunk

    return encode_chunk(tok, chunk)


def prepare(ctx: Ctx, bid: int, build_dir: Path, tok, tok_path: Path, log: Callable[[str], None],
            wait_seconds: float = WAIT_SECONDS, poll: float = 0.5,
            head_start: float = HEAD_START) -> dict[str, list[dict]] | None:
    """Encode the public domains' training records with the help of workers. None: no workers."""
    from moth.datafactory.build import load_chunk, split_records

    from moth_server.evolution import memory as MEM
    from moth_server.evolution.native_reset import next_job_values
    from moth_server.training import requeue_expired

    manifest = json.loads((Path(build_dir) / "manifest.json").read_text())
    domains = public_domains(manifest)
    files = [p for p in sorted((Path(build_dir) / "domains").glob("*.jsonl")) if p.stem in domains]
    if not files or not eligible_workers(ctx):
        return None
    prep = Path(build_dir) / "prep"
    chunks: list[tuple[str, Path]] = []
    for p in files:
        chunks += [(p.stem, c) for c in split_records(p, prep / "chunks", CHUNK_RECORDS)]
    if len(chunks) < 2:
        return None  # one chunk: sending it away cannot be faster than encoding it here
    tok_sha = _sha(Path(tok_path))
    jobs: dict[int, tuple[str, Path]] = {}
    with ctx.db.tx() as c:
        for d, ch in chunks:
            spec = {"prep": {"build": bid, "domain": d, "chunk": str(ch), "tokenizer": str(tok_path),
                             "out": str(prep / (ch.stem + ".npz"))},
                    "round": -1, "base_sha256": tok_sha, "shard_sha256": _sha(ch),
                    "tokenizer_fingerprint": tok.fingerprint(), "shard_id": ch.stem,
                    "job_id": f"prep-{bid}-{ch.stem}", "requirements": {"memory_bytes": 0}, "prefer_cpu": True,
                    "min_worker_version": MIN_WORKER_VERSION}
            jid = c.execute(training_jobs.insert().values(**next_job_values(ctx, c), kind="prep_tokenize",
                                                          status="queued", spec=json.dumps(spec), attempts=0,
                                                          max_attempts=2, created_at=now(), updated_at=now())
                            ).inserted_primary_key[0]
            jobs[jid] = (d, ch)
    log(f"preparing {len(chunks)} chunk(s) with {len(eligible_workers(ctx))} worker(s) and MOTH Cloud")
    MEM.event(ctx, "data.distributed", f"Dataset build {bid}: {len(chunks)} chunks of training records are being "
              "tokenized by workers and MOTH Cloud together; every worker result is checked by re-encoding records.",
              build=bid, chunks=len(chunks))
    started = time.time()
    by_server = 0
    while True:
        requeue_expired(ctx)
        rows = {r["id"]: r for r in ctx.db.all(select(training_jobs).where(training_jobs.c.id.in_(list(jobs))))}
        outstanding = [j for j in jobs if not Path(json.loads(rows[j]["spec"])["prep"]["out"]).exists()]
        if not outstanding:
            break
        late = time.time() - started >= wait_seconds
        # workers get a short head start; afterwards MOTH Cloud takes unclaimed chunks (work stealing)
        ready = time.time() - started >= head_start or not eligible_workers(ctx)
        take = next((j for j in outstanding if rows[j]["status"] in ("failed", "cancelled")
                     or (ready and rows[j]["status"] == "queued")
                     or (late and rows[j]["status"] == "leased")), None)
        if take is None:
            time.sleep(poll)
            continue
        # work stealing: MOTH Cloud prepares an unclaimed (or, after the wait, any outstanding) chunk itself
        with ctx.db.tx() as c:
            c.execute(training_jobs.update().where(training_jobs.c.id == take, training_jobs.c.status != "completed")
                      .values(status="cancelled", error="prepared by MOTH Cloud", lease_expires_at=None, updated_at=now()))
        spec = json.loads(rows[take]["spec"])["prep"]
        if not Path(spec["out"]).exists():
            from moth.datafactory.build import chunk_bytes

            _atomic_write(Path(spec["out"]), chunk_bytes(_encode_local(tok, Path(spec["chunk"]))))
            by_server += 1
    out: dict[str, list[dict]] = {}
    for jid, (d, ch) in jobs.items():
        out.setdefault(d, []).append(load_chunk((prep / (ch.stem + ".npz")).read_bytes()))
    by_workers = len(jobs) - by_server
    log(f"prepared {len(jobs)} chunk(s): {by_workers} by workers, {by_server} by MOTH Cloud")
    MEM.event(ctx, "data.distributed", f"Dataset build {bid}: {by_workers} of {len(jobs)} chunks were tokenized by "
              f"workers (each verified), {by_server} by MOTH Cloud.", build=bid, by_workers=by_workers,
              by_server=by_server)
    return out


def _atomic_write(p: Path, data: bytes) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(p)


def files(ctx: Ctx, spec: dict) -> tuple[Path, Path]:
    return Path(spec["prep"]["tokenizer"]), Path(spec["prep"]["chunk"])


def verify(tok, chunk: Path, arrays: dict, checks: int = SPOT_CHECKS, seed: int | None = None) -> list[str]:
    """Reasons to refuse a worker's chunk (empty: accepted)."""
    from moth.datafactory.build import _encode, _iter_jsonl, record_hash

    reasons = []
    records = list(_iter_jsonl(chunk))
    ids, mask, offs, hashes = arrays["ids"], arrays["mask"], arrays["offsets"], arrays["hashes"]
    if len(offs) != len(records) + 1 or int(offs[0]) != 0 or int(offs[-1]) != len(ids) or len(mask) != len(ids):
        return ["the result does not match the chunk's records"]
    if hashes.shape != (len(records), 16):
        return ["record hashes are missing"]
    if any(int(offs[i + 1]) < int(offs[i]) for i in range(len(records))):
        return ["record offsets are not in order"]
    if len(ids) and int(ids.max()) >= tok.vocab_size:
        return ["token ids outside the tokenizer's vocabulary"]
    rng = random.Random(seed)
    sample = sorted({0, len(records) - 1, *rng.sample(range(len(records)), min(checks, len(records)))})
    for r in sample:
        want_ids, want_mask = _encode(tok, records[r])
        a, b = int(offs[r]), int(offs[r + 1])
        if ids[a:b].tolist() != want_ids or mask[a:b].tolist() != want_mask or bytes(hashes[r]) != record_hash(records[r]):
            reasons.append(f"record {r} was not tokenized correctly")
            break
    return reasons


def accept(ctx: Ctx, job_row: dict, meta: dict, payload: bytes) -> dict:
    from moth.community.validation import tensor_bytes_sha256
    from moth.datafactory.build import load_chunk
    from moth.model.tokenizer import Tokenizer

    spec = json.loads(job_row["spec"])
    p = spec["prep"]
    if meta.get("base_sha256") != spec["base_sha256"] or _sha(Path(p["tokenizer"])) != spec["base_sha256"]:
        return {"accepted": False, "reasons": ["prepared with a different tokenizer"]}
    if tensor_bytes_sha256(payload) != meta.get("delta_sha256"):
        return {"accepted": False, "reasons": ["checksum mismatch"]}
    if Path(p["out"]).exists():
        return {"accepted": False, "reasons": ["this chunk was already prepared"]}
    try:
        arrays = load_chunk(payload)
    except Exception as e:  # noqa: BLE001
        return {"accepted": False, "reasons": [f"unreadable result: {e}"]}
    reasons = verify(Tokenizer.load(Path(p["tokenizer"])), Path(p["chunk"]), arrays)
    if reasons:
        return {"accepted": False, "reasons": reasons}
    _atomic_write(Path(p["out"]), payload)
    return {"accepted": True, "tokens": int(len(arrays["ids"])), "records": int(len(arrays["offsets"]) - 1)}
