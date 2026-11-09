"""The Smart Dataset Library on MOTH Cloud: the approved catalog, verified downloads and corpus builds.

* ``status`` — every approved dataset with its license, pinned revision and whether each file is
  downloaded and verified (downloads happen once and are reused).
* ``start_build`` — runs the Data Factory in the background: download/verify, clean, deduplicate,
  decontaminate, then tokenize with the model lineage's tokenizer. Approved, consented feedback is added
  as its own source. Each domain of the result is registered as an approved training dataset, so the
  evolution engine can continue training on it.
* ``check_updates`` / ``approve_update`` — detect newer upstream revisions; a new revision is used only
  after the Owner approves it, and then pinned with its own checksums.
"""

from __future__ import annotations

import json
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Any

from sqlalchemy import select

from moth_server.context import Ctx
from moth_server.db import library_builds, now


def root(ctx: Ctx) -> Path:
    p = Path(ctx.settings.data_dir) / "library"
    p.mkdir(parents=True, exist_ok=True)
    return p


def recover(ctx: Ctx) -> None:
    """Called once at server startup, before accepting requests. Keep reusable downloads."""
    with ctx.db.tx() as c:
        c.execute(library_builds.update().where(library_builds.c.status.in_(('queued', 'running')))
                  .values(status='failed', error='Preparation interrupted by server restart; verified downloads retained', finished_at=now()))


def _fetch_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "moth-server"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def pins(ctx: Ctx) -> dict[str, Any]:
    return ctx.db.get_config("library_pins", {}) or {}


def status(ctx: Ctx) -> dict[str, Any]:
    from moth.datafactory import catalog, fetch

    cache = root(ctx) / "cache"
    ver = fetch.verified(cache) if cache.exists() else {}
    p = pins(ctx)
    out = []
    for s in catalog.SOURCES:
        src = catalog.with_pin(s, p.get(s["id"]))
        pub = catalog.public(src)
        for f in pub["files"]:
            key = f"{src['repo']}@{src['revision']}/{f['path']}" if src["repo"] else None
            f["verified"] = bool(key and ver.get(key, {}).get("sha256") == f["sha256"])
        pub["downloaded"] = all(f["verified"] for f in pub["files"]) if pub["files"] else True
        pub["pinned_update"] = s["id"] in p
        out.append(pub)
    builds = [{**_public_build(b), "progress": ctx.db.get_config(f"library_progress_{b['id']}", None)}
              for b in ctx.db.all(select(library_builds).order_by(library_builds.c.id.desc())
                                                   .limit(10))]
    from moth_server.evolution import memory as MEM
    lineage = MEM.lineage(ctx)
    for b in builds:
        b['used_by_releases'] = [r['version'] for r in lineage if b['content_sha256'] in r.get('datasets', [])]
    return {"datasets": out, "builds": builds, "updates": ctx.db.get_config("library_updates", None)}


def _public_build(b: dict) -> dict:
    m = json.loads(b["manifest"] or "{}")
    return {"id": b["id"], "status": b["status"], "content_sha256": b["content_sha256"], "error": b["error"],
            "created_at": b["created_at"], "finished_at": b["finished_at"],
            "tokenizer_fingerprint": b["tokenizer_fingerprint"], "domains": m.get("domains"),
            "token_counts": m.get("token_counts"),
            "sources": [{"id": s["id"], "license": s["license"], "stats": s.get("stats")} for s in m.get("sources", [])],
            "eval_items": m.get("eval_items")}


def latest_ready(ctx: Ctx) -> dict | None:
    return ctx.db.one(select(library_builds).where(library_builds.c.status == "ready")
                      .order_by(library_builds.c.id.desc()))


def eval_dir(ctx: Ctx) -> Path | None:
    b = latest_ready(ctx)
    if b and b["path"] and (Path(b["path"]) / "eval").is_dir():
        return Path(b["path"]) / "eval"
    return None


def _lineage_tokenizer(ctx: Ctx) -> Path | None:
    """The tokenizer of the deployed model (one lineage keeps one tokenizer)."""
    from moth_server import models as M

    d = M.deployed(ctx) or next((r for r in M.list_releases(ctx) if r.get("path")), None)
    if not d:
        return None
    for cand in (Path(d["path"]) / "tokenizer.json",) if d.get("path") else ():
        if cand.exists():
            return cand
    return None


def start_build(ctx: Ctx, actor_id: int | None, config: dict[str, Any] | None = None,
                wait: bool = False) -> int:
    running = ctx.db.one(select(library_builds).where(library_builds.c.status.in_(("queued", "running"))))
    if running:
        return running["id"]
    with ctx.db.tx() as c:
        bid = c.execute(library_builds.insert().values(status="queued", created_at=now())).inserted_primary_key[0]
    from moth_server.evolution.native_reset import spawn
    t=spawn(ctx,lambda:_run_build(ctx,bid,config or {}),f"library-build-{bid}")
    if wait:
        t.join()
    from moth_server.audit import audit

    audit(ctx.db, "library.build", actor_id, f"library_build:{bid}", {})
    return bid


def _run_build(ctx: Ctx, bid: int, config: dict[str, Any]) -> None:
    from moth.datafactory import build as factory
    from moth.model.tokenizer import Tokenizer, train_bpe

    from moth_server.evolution import datasets as DS
    from moth_server.intelligence import feedback

    def upd(**v):
        with ctx.db.tx() as c:
            c.execute(library_builds.update().where(library_builds.c.id == bid).values(**v))

    upd(status="running")
    def progress(message):
        ctx.db.set_config(f"library_progress_{bid}", {"message": message, "updated_at": time.time()})

    try:
        out = root(ctx) / "builds" / f"build-{bid}"
        extra = []
        fb = feedback.export_dataset(ctx)
        if fb:
            extra.append({"id": "feedback", "name": "Approved user feedback (with consent)", "license": "user-consented",
                          "attribution": "MOTH users who opted in to training use", "records": fb})
        cfg = {**config, "pins": pins(ctx)}
        manifest = factory.build(root(ctx) / "cache", out, cfg, log=progress, extra_sources=extra)
        tok_path = _lineage_tokenizer(ctx)
        if tok_path is None:  # a new lineage: train its tokenizer once from the corpus
            tok_path = out / "tokenizer.json"
            vocab = int(config.get("vocab_size", 16384))
            train_bpe(factory.iter_texts(out, per_domain_chars=int(config.get("tokenizer_chars", 4_000_000))),
                      vocab).save(tok_path)
        tok = Tokenizer.load(tok_path)
        mix = factory.tokenize_build(out, tok, tok_path, log=progress)
        registered = 0
        registration_errors = []
        for d, info in mix["domains"].items():
            ddir = out / "tokens" / info["dir"]
            user_data = bool(fb) and any(r["domain"] == d for r in fb)
            try:
                info = DS.inspect(ddir)
                rows = DS.all_(ctx)
                if config.get("automatic"):
                    revoked = {s.get("spec") for row in rows if row["status"] == "revoked"
                               for s in json.loads(row.get("sources") or "[]")}
                    if any(s.get("spec") in revoked for s in info["meta"].get("sources", [])):
                        continue
                matches = [row for row in rows if row["sha256"] == info["sha256"]]
                if matches:
                    registered += int(any(row["status"] == "approved" for row in matches))
                    continue  # preserve pending/revoked approvals and active dataset files
                row = DS.register_prepared(ctx, ddir, f"Library: {d} (build {bid})", [d, "library"], user_data, None)
                # catalog data is pre-approved; feedback is included only with each user's consent
                DS.approve(ctx, row["id"], None, user_data_permission=user_data)
                registered += 1
            except Exception as exc:  # keep valid domains and report the failed domain
                from moth.security.redaction import redact
                registration_errors.append(f"{d}: {redact(str(exc))[0]}")
        if not registered:
            raise ValueError("No prepared domain could be registered and approved: " + "; ".join(registration_errors))
        manifest["registration_errors"] = registration_errors
        manifest["token_counts"] = {d: i["tokens"] for d, i in mix["domains"].items()}
        progress("Prepared and approved")
        upd(status="ready", path=str(out), content_sha256=manifest["content_sha256"],
            tokenizer_fingerprint=tok.fingerprint(), manifest=json.dumps(manifest), finished_at=now())
        if config.get('automatic'):
            from moth_server.evolution import engine as EN
            EN.wake(ctx)  # new data is ready now; do not wait for the next daily cycle
    except Exception as e:  # noqa: BLE001
        from moth.security.redaction import redact
        upd(status="failed", error=redact(f"{type(e).__name__}: {e}")[0][:2000], finished_at=now())


def check_updates(ctx: Ctx, fetch_json=_fetch_json, sources=None) -> list[dict[str, Any]]:
    from moth.datafactory import catalog

    p = pins(ctx)
    res = []
    for r in catalog.check_updates(fetch_json, sources=sources):
        cur = (p.get(r["id"]) or {}).get("revision") or r["pinned"]
        r["pinned"] = cur
        r["update_available"] = bool(r.get("latest") and r["latest"] != cur)
        res.append(r)
    ctx.db.set_config("library_updates", {"checked_at": time.time(), "results": res})
    return res


def approve_update(ctx: Ctx, sid: str, revision: str, actor_id: int, fetch_json=_fetch_json) -> dict[str, Any]:
    from moth.datafactory import catalog

    pin = catalog.resolve_revision(catalog.source(sid), revision, fetch_json)
    p = pins(ctx)
    p[sid] = pin
    ctx.db.set_config("library_pins", p)
    from moth_server.audit import audit

    audit(ctx.db, "library.pin", actor_id, f"dataset:{sid}", {"revision": revision})
    return pin
