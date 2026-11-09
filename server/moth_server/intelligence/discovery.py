"""Bounded automatic preparation from the existing, pinned trusted catalog.

Discovery never adds arbitrary URLs, accepts new upstream revisions, or reapproves
revoked datasets. Owners explicitly select remote sources before unattended use.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import time
import threading

from moth_server.context import Ctx

KEY = "library_discovery"
DEFAULTS = {"enabled": True, "approved_sources": ["python-stdlib"],
            "max_download_bytes": 256_000_000, "max_source_chars": 500_000, "retry_seconds": 3600,
            "check_updates_seconds": 86400}
LICENSES = {"PSF-2.0", "MIT", "Apache-2.0", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "CDLA-Sharing-1.0"}


def policy(ctx: Ctx) -> dict:
    return {**DEFAULTS, **(ctx.db.get_config(KEY, {}) or {})}


def update(ctx: Ctx, changes: dict) -> dict:
    from moth.datafactory import catalog

    if set(changes) - set(DEFAULTS):
        raise ValueError("Unknown discovery policy setting")
    p = {**policy(ctx), **changes}
    if not isinstance(p['enabled'], bool) or not isinstance(p['approved_sources'], list):
        raise ValueError("Invalid discovery switches or sources")
    for sid in p['approved_sources']:
        try:
            src = catalog.source(sid)
        except (KeyError, TypeError):
            raise ValueError("Only trusted catalog sources may be approved") from None
        if src['license'] not in LICENSES or not src.get('attribution'):
            raise ValueError(f"Unverified training license or attribution for {sid}")
    for key, lo, hi in (("max_download_bytes", 0, 10**11), ("max_source_chars", 10000, 10**8),
                        ("retry_seconds", 60, 86400 * 30), ('check_updates_seconds', 3600, 86400 * 30)):
        if type(p[key]) is not int or not lo <= p[key] <= hi:
            raise ValueError(f"{key} must be an integer between {lo} and {hi}")
    ctx.db.set_config(KEY, p)
    return p


def status(ctx: Ctx) -> dict:
    from moth.datafactory import catalog
    from moth_server.intelligence import library

    p = policy(ctx)
    state = ctx.db.get_config(KEY + "_state", {}) or {}
    if state.get('build'):
        b = next((b for b in library.status(ctx)['builds'] if b['id'] == state['build']), None)
        if b:
            state = {**state, 'status': b['status'], 'error': b.get('error'), 'progress': b.get('progress')}
    return {"policy": p, "state": state,
            "discovered": [{**catalog.public(catalog.with_pin(s, library.pins(ctx).get(s['id']))),
                            "approved": s['id'] in p['approved_sources'],
                            "license_verified": s['license'] in LICENSES and bool(s.get('attribution'))}
                           for s in catalog.SOURCES]}


def ensure_data(ctx: Ctx, wait: bool = False) -> dict:
    from moth.datafactory import catalog
    from moth.training.checkpoint import RunLock
    from moth_server.intelligence import library

    from moth_server.evolution.native_reset import fenced,empty
    if fenced(ctx) or empty(ctx):return {"status":"native_reset"}
    with RunLock(library.root(ctx) / "discovery", "automatic data preparation"):
        p = policy(ctx)
        st = ctx.db.get_config(KEY + "_state", {}) or {}
        if not p['enabled']:
            return {"status": "disabled"}
        approved = [s for s in catalog.SOURCES if s['id'] in p['approved_sources']
                    and s['license'] in LICENSES and s.get('attribution')]
        from moth_server.evolution import datasets as DS

        revoked_sources = {s.get('spec') for d in DS.all_(ctx) if d['status'] == 'revoked'
                           for s in json.loads(d.get('sources') or '[]')}
        approved = [s for s in approved if f"factory:{s['id']}" not in revoked_sources]
        if not approved:
            return {"status": "awaiting_source_approval"}
        required = sum(f['size'] for s in approved for f in catalog.with_pin(s, library.pins(ctx).get(s['id']))['files'])
        from moth_server.evolution import settings as S

        reserve = S.get(ctx)['limits']['min_free_disk_gb'] * 1024**3
        if required > p['max_download_bytes'] or shutil.disk_usage(library.root(ctx)).free < reserve + required * 3 + len(approved) * p['max_source_chars'] * 8:
            return {"status": "storage_budget", "download_bytes": required}
        remote = [s for s in approved if s.get('repo')]
        checked = ctx.db.get_config(KEY + '_scan_at', 0) or 0
        if remote and time.time() - checked > p['check_updates_seconds'] and not ctx.extras.get('discovery_scan'):
            ctx.db.set_config(KEY + '_scan_at', time.time())
            ctx.extras['discovery_scan'] = True
            def scan():
                try:
                    library.check_updates(ctx, sources=remote)
                finally:
                    ctx.extras['discovery_scan'] = False
            from moth_server.evolution.native_reset import spawn
            spawn(ctx,scan,'trusted-dataset-discovery')
        sig = hashlib.sha256(json.dumps({"sources": approved, "pins": library.pins(ctx),
                                        "factory_policy": 2, "policy": p, "tokenizer": str(library._lineage_tokenizer(ctx))},
                                       sort_keys=True).encode()).hexdigest()
        if st.get('signature') == sig:
            if st.get('build'):
                from sqlalchemy import select
                from moth_server.db import library_builds

                b = ctx.db.one(select(library_builds).where(library_builds.c.id == st['build']))
                if b and b['status'] in ('queued', 'running', 'ready'):
                    return {**st, 'status': b['status']}
            if time.time() < st.get('retry_at', 0):
                return {**st, 'status': 'backoff'}
        from moth_server.evalsets import BUILTIN_FILES
        bid = library.start_build(ctx, None, {"automatic": True, "excluded_stdlib_files": list(BUILTIN_FILES),
                                            "sources": [s['id'] for s in approved],
                                            "max_chars": {s['id']: p['max_source_chars'] for s in approved}}, wait=wait)
        st = {"signature": sig, "build": bid, "requested_at": time.time(),
              "retry_at": time.time() + p['retry_seconds'], "status": "preparing"}
        ctx.db.set_config(KEY + "_state", st)
        return st
