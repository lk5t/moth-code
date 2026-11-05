"""MOTH software releases: signed manifests, staged rollouts, update eligibility and reports.

One approved release of MOTH is one **signed manifest** (``moth-release-<version>.json`` plus an
ed25519 signature made in CI with the private release key). It lists every component built from
the same commit — the cloud server bundle, the Windows desktop update and the MOTH Worker — with
SHA-256 digests, schema/API versions and rollout policy. Nothing is installed or offered to
clients unless the manifest signature verifies against the release public key configured on
this server *and* each file matches its digest.

The local update agent discovers releases and hands them to the server (``/v1/agent/*``). The
server then:

* updates **desktops** through the Tauri updater endpoint, in stages (e.g. 10% → 50% → 100% of
  installs, by a stable hash of the install id), advancing on a timer and **halting
  automatically** if the reported failure rate exceeds the manifest's limit;
* offers **workers** the new worker bundle the same way;
* records **server** deployments that the agent performs, with logs, for the Owner Dashboard.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import and_, desc, func, select

from moth_server import compat
from moth_server.audit import audit
from moth_server.context import Ctx
from moth_server.db import deployments, software_releases, update_reports, now, users
from moth_server.ed25519_verify import verify_b64

log = logging.getLogger("moth_server.releases")

COMPONENTS = ("server", "desktop", "worker")
ACTIVE = ("rolling_out", "complete")
DEFAULT_ROLLOUT = {"stages": [10, 50, 100], "interval_hours": 6, "max_failure_rate": 0.2, "min_reports": 5}
_SAFE_NAME = re.compile(r"^[A-Za-z0-9._+-]{1,200}$")


class ReleaseError(ValueError):
    pass


# ---- manifests ----------------------------------------------------------------------------------
def verify_manifest(ctx: Ctx, manifest_bytes: bytes, signature_b64: str) -> dict:
    if not ctx.settings.release_pubkey:
        raise ReleaseError("no release public key is configured (MOTH_RELEASE_PUBKEY); refusing unsigned releases")
    if not verify_b64(ctx.settings.release_pubkey, manifest_bytes, signature_b64):
        raise ReleaseError("release manifest signature is invalid")
    try:
        m = json.loads(manifest_bytes)
        compat.parse_version(m["version"])
    except (ValueError, KeyError, TypeError) as e:
        raise ReleaseError(f"malformed release manifest: {e}") from None
    if m.get("format") != 1:
        raise ReleaseError("unsupported release manifest format")
    for comp, spec in (m.get("components") or {}).items():
        if comp not in COMPONENTS:
            continue
        for f in _files(comp, spec):
            if not _SAFE_NAME.match(f["file"]) or not re.fullmatch(r"[0-9a-f]{64}", f.get("sha256", "")):
                raise ReleaseError(f"manifest entry for {comp} is malformed")
    return m


def _files(component: str, spec: dict) -> list[dict]:
    """Files of one component entry. Desktop entries are keyed by platform (windows-x86_64, …)."""
    if component == "desktop":
        return [dict(v, platform=k) for k, v in spec.items()]
    return [spec]


def manifest_dir(ctx: Ctx) -> Path:
    d = ctx.settings.releases_dir / "manifests"
    d.mkdir(parents=True, exist_ok=True)
    return d


def register(ctx: Ctx, manifest_bytes: bytes, signature_b64: str) -> dict:
    """Store a verified manifest and create one release row per component it contains."""
    m = verify_manifest(ctx, manifest_bytes, signature_b64)
    version = m["version"]
    (manifest_dir(ctx) / f"{version}.json").write_bytes(manifest_bytes)
    (manifest_dir(ctx) / f"{version}.json.sig").write_text(signature_b64.strip())
    t = now()
    created = []
    with ctx.db.tx() as c:
        for comp in COMPONENTS:
            spec = (m.get("components") or {}).get(comp)
            if not spec:
                continue
            row = c.execute(select(software_releases.c.id).where(
                software_releases.c.component == comp, software_releases.c.version == version)).first()
            if row:
                continue
            status = "available" if comp == "server" else "rolling_out"
            pct = 100 if comp == "server" else _stages(m, comp)[0]
            c.execute(software_releases.insert().values(
                component=comp, version=version, channel=m.get("channel", "stable"), status=status,
                rollout_percent=pct, manifest=json.dumps({"stage": 0, "stage_started_at": t}),
                notes=(m.get("notes") or "")[:4000], created_at=t, updated_at=t))
            created.append(comp)
        if created:
            audit(ctx.db, "releases.registered", None, f"release:{version}", {"components": created}, conn=c)
    return {"version": version, "registered": created}


def load_manifest(ctx: Ctx, version: str) -> tuple[dict, bytes, str] | None:
    p = manifest_dir(ctx) / f"{version}.json"
    if not p.exists():
        return None
    raw = p.read_bytes()
    sig = (manifest_dir(ctx) / f"{version}.json.sig").read_text()
    return json.loads(raw), raw, sig


def _stages(m: dict, comp: str) -> list[int]:
    pol = {**DEFAULT_ROLLOUT, **((m.get("rollout") or {}).get(comp) or {})}
    stages = [max(1, min(100, int(s))) for s in pol["stages"]] or [100]
    return stages if stages[-1] == 100 else stages + [100]


def _policy(m: dict, comp: str) -> dict:
    return {**DEFAULT_ROLLOUT, **((m.get("rollout") or {}).get(comp) or {})}


# ---- files ----------------------------------------------------------------------------------------
def file_dir(ctx: Ctx, component: str, version: str) -> Path:
    return ctx.settings.releases_dir / component / version


def accept_file(ctx: Ctx, component: str, version: str, src: Path) -> Path:
    """Verify a downloaded file against the signed manifest and move it into the served area."""
    loaded = load_manifest(ctx, version)
    if not loaded:
        raise ReleaseError("unknown release")
    spec = (loaded[0].get("components") or {}).get(component)
    entry = next((f for f in _files(component, spec or {}) if f["file"] == src.name), None)
    if not entry:
        raise ReleaseError(f"{src.name} is not part of release {version}")
    h = hashlib.sha256()
    with open(src, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != entry["sha256"]:
        src.unlink(missing_ok=True)
        raise ReleaseError(f"{src.name} does not match its SHA-256 in the signed manifest")
    dest = file_dir(ctx, component, version)
    dest.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), dest / src.name)
    return dest / src.name


def served_file(ctx: Ctx, component: str, version: str, name: str) -> Path | None:
    if not _SAFE_NAME.match(name) or not _SAFE_NAME.match(version) or component not in COMPONENTS:
        return None
    p = file_dir(ctx, component, version) / name
    return p if p.is_file() else None


def files_ready(ctx: Ctx, component: str, version: str, platform: str | None = None) -> dict | None:
    loaded = load_manifest(ctx, version)
    if not loaded:
        return None
    spec = (loaded[0].get("components") or {}).get(component) or {}
    for f in _files(component, spec):
        if platform and f.get("platform") != platform:
            continue
        if served_file(ctx, component, version, f["file"]):
            return f
    return None


# ---- eligibility ------------------------------------------------------------------------------------
def bucket(install_id: str, version: str) -> int:
    """Stable 0–99 bucket: the same install keeps its place within one release's rollout."""
    return int.from_bytes(hashlib.sha256(f"{version}:{install_id}".encode()).digest()[:4], "big") % 100


def eligible(ctx: Ctx, component: str, current: str, install_id: str, channel: str = "stable",
             platform: str | None = None) -> tuple[dict, dict] | None:
    """The newest release of ``component`` this install should move to now, with its file entry."""
    try:
        cur = compat.parse_version(current)
    except ValueError:
        return None
    channels = ("stable",) if channel == "stable" else ("stable", channel)
    rows = ctx.db.all(select(software_releases).where(software_releases.c.component == component,
                                                      software_releases.c.status.in_(ACTIVE),
                                                      software_releases.c.channel.in_(channels)))
    rows.sort(key=lambda r: compat.parse_version(r["version"]), reverse=True)
    for r in rows:
        if compat.parse_version(r["version"]) <= cur:
            return None
        if r["status"] == "rolling_out" and bucket(install_id, r["version"]) >= r["rollout_percent"]:
            continue  # not this install's turn yet; an older active release may still apply
        f = files_ready(ctx, component, r["version"], platform)
        if f:
            return r, f
    return None


# ---- reports & staged rollout -------------------------------------------------------------------------
def record_report(ctx: Ctx, component: str, client_id: str, from_v: str | None, to_v: str, ok: bool,
                  error: str | None) -> None:
    with ctx.db.tx() as c:
        c.execute(update_reports.insert().values(component=component, client_id=client_id[:64],
                                                 from_version=(from_v or "")[:32] or None, to_version=to_v[:32],
                                                 ok=ok, error=(error or "")[:2000] or None, created_at=now()))


def report_stats(ctx: Ctx, component: str, version: str) -> dict:
    rows = ctx.db.all(select(update_reports.c.ok, func.count().label("n"))
                      .where(update_reports.c.component == component, update_reports.c.to_version == version)
                      .group_by(update_reports.c.ok))
    ok = sum(r["n"] for r in rows if r["ok"])
    failed = sum(r["n"] for r in rows if not r["ok"])
    return {"succeeded": ok, "failed": failed, "failure_rate": (failed / (ok + failed)) if ok + failed else 0.0}


def advance_rollouts(ctx: Ctx) -> list[dict]:
    """Move staged rollouts forward, or halt them when failures exceed the manifest's limit."""
    changes = []
    for r in ctx.db.all(select(software_releases).where(software_releases.c.status == "rolling_out")):
        loaded = load_manifest(ctx, r["version"])
        if not loaded:
            continue
        m = loaded[0]
        pol = _policy(m, r["component"])
        state = json.loads(r["manifest"] or "{}")
        stats = report_stats(ctx, r["component"], r["version"])
        values: dict[str, Any] = {}
        if stats["failed"] + stats["succeeded"] >= pol["min_reports"] and stats["failure_rate"] > pol["max_failure_rate"]:
            values = {"status": "halted"}
            notify_owner(ctx, f"MOTH {r['component']} {r['version']} rollout halted",
                         f"The {r['component']} update to {r['version']} was halted automatically: "
                         f"{stats['failed']} of {stats['failed'] + stats['succeeded']} installs reported a failure "
                         f"(limit {pol['max_failure_rate']:.0%}). Review it in the Owner Dashboard → Updates.")
        else:
            stages = _stages(m, r["component"])
            i = int(state.get("stage", 0))
            if r["rollout_percent"] >= 100:
                values = {"status": "complete"}
            elif now() - float(state.get("stage_started_at", 0)) >= pol["interval_hours"] * 3600 and i + 1 < len(stages):
                state = {"stage": i + 1, "stage_started_at": now()}
                values = {"rollout_percent": stages[i + 1], "manifest": json.dumps(state)}
        if values:
            values["updated_at"] = now()
            with ctx.db.tx() as c:
                c.execute(software_releases.update().where(software_releases.c.id == r["id"]).values(**values))
                audit(ctx.db, "releases.rollout_changed", None, f"{r['component']}:{r['version']}", values, conn=c)
            changes.append({"component": r["component"], "version": r["version"], **values})
    return changes


def set_status(ctx: Ctx, component: str, version: str, action: str, actor_id: int, percent: int | None = None) -> dict:
    r = ctx.db.one(select(software_releases).where(software_releases.c.component == component,
                                                   software_releases.c.version == version))
    if not r:
        raise ReleaseError("unknown release")
    values: dict[str, Any] = {"updated_at": now()}
    if action == "pause":
        values["status"] = "paused"
    elif action == "resume":
        values["status"] = "available" if component == "server" else ("complete" if r["rollout_percent"] >= 100 else "rolling_out")
        if component != "server":
            values["manifest"] = json.dumps({**json.loads(r["manifest"] or "{}"), "stage_started_at": now()})
    elif action == "withdraw":
        values["status"] = "withdrawn"
    elif action == "promote":
        values.update(status="complete" if component != "server" else "available", rollout_percent=100)
    elif action == "rollout" and percent is not None:
        values.update(rollout_percent=max(0, min(100, int(percent))))
        if r["status"] in ("halted", "paused") and component != "server":
            values["status"] = "rolling_out"
    else:
        raise ReleaseError("unknown action")
    with ctx.db.tx() as c:
        c.execute(software_releases.update().where(software_releases.c.id == r["id"]).values(**values))
        audit(ctx.db, f"releases.{action}", actor_id, f"{component}:{version}", {k: v for k, v in values.items()
                                                                                  if k != "manifest"}, conn=c)
    return public_release(ctx.db.one(select(software_releases).where(software_releases.c.id == r["id"])), ctx)


def public_release(r: dict, ctx: Ctx | None = None) -> dict:
    out = {k: r[k] for k in ("component", "version", "channel", "status", "rollout_percent", "notes", "created_at",
                             "updated_at")}
    if ctx is not None and r["component"] != "server":
        out["reports"] = report_stats(ctx, r["component"], r["version"])
    return out


def list_releases(ctx: Ctx, component: str | None = None, limit: int = 30) -> list[dict]:
    q = select(software_releases).order_by(desc(software_releases.c.created_at)).limit(limit)
    if component:
        q = q.where(software_releases.c.component == component)
    return [public_release(r, ctx) for r in ctx.db.all(q)]


# ---- deployments (performed by the agent) ---------------------------------------------------------------
def deployment_event(ctx: Ctx, body: dict) -> dict:
    t = now()
    with ctx.db.tx() as c:
        if body.get("id"):
            row = c.execute(select(deployments).where(deployments.c.id == int(body["id"]))).mappings().first()
            if not row:
                raise ReleaseError("unknown deployment")
            values: dict[str, Any] = {}
            for k in ("status", "step", "error"):
                if body.get(k) is not None:
                    values[k] = str(body[k])[:4000 if k == "error" else 64]
            if body.get("log"):
                values["log"] = (row["log"] + str(body["log"]))[-60000:]
            if values.get("status") in ("succeeded", "failed", "rolled_back", "needs_approval", "skipped"):
                values["finished_at"] = t
            c.execute(deployments.update().where(deployments.c.id == row["id"]).values(**values))
            did = row["id"]
        else:
            res = c.execute(deployments.insert().values(
                component=str(body.get("component", "server"))[:16], from_version=body.get("from_version"),
                to_version=str(body["to_version"])[:32], status=str(body.get("status", "started"))[:16],
                step=body.get("step"), log=str(body.get("log", ""))[-60000:], started_at=t))
            did = res.inserted_primary_key[0]
    d = ctx.db.one(select(deployments).where(deployments.c.id == did))
    if d["status"] in ("failed", "rolled_back", "needs_approval") and body.get("status"):
        what = {"failed": "failed", "rolled_back": "failed and was rolled back",
                "needs_approval": "is waiting for your approval"}[d["status"]]
        notify_owner(ctx, f"MOTH Cloud update {d['to_version']} {what}",
                     f"The MOTH Cloud update from {d['from_version'] or '?'} to {d['to_version']} {what}.\n\n"
                     f"{d['error'] or ''}\n\nOpen the Owner Dashboard → Updates for details.")
    return d


def list_deployments(ctx: Ctx, limit: int = 30) -> list[dict]:
    return ctx.db.all(select(deployments).order_by(desc(deployments.c.id)).limit(limit))


def notify_owner(ctx: Ctx, subject: str, body: str) -> None:
    """Failure notifications: error log (dashboard) and an email to the Owner, best effort."""
    log.error("%s", subject)
    owner = ctx.db.one(select(users.c.email).where(and_(users.c.role == "owner", users.c.status == "active")))
    if owner:
        try:
            ctx.mailer.send(owner["email"], subject, body)
        except Exception:  # noqa: BLE001 — notification must never break the caller
            log.warning("could not email the owner about: %s", subject)


def encode_manifest(raw: bytes) -> str:
    return base64.b64encode(raw).decode()
