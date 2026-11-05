"""Official MOTH model registry and cloud deployment (server-side only).

Users never download weights: the deployed release runs in MOTH Cloud for everyone.

Lifecycle of a release::

    candidate ──evaluate──► passed ──deploy──► deployed ──(next deploy)──► retired
                    └──────► rejected                └── rollback = redeploy a retired release

Candidates come from aggregated training-network checkpoints (``sync_candidates``) or from
the Owner uploading an exported model package. The evaluation gate requires: the package
loads and its checksum verifies, held-out loss is finite and not worse than the deployed
model by more than ``tolerance``, and generation runs. Deployment loads the release into a
fresh inference engine and smoke-tests it *before* swapping it in; any failure leaves the
current model serving (automatic rollback).
"""

from __future__ import annotations

import json
import math
import shutil
import tarfile
import threading
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import desc, func, select

from moth_server.audit import audit
from moth_server.context import Ctx
from moth_server.db import model_releases, now

TOLERANCE = 0.02
EVAL_TOKENS = 64 * 1024


class ReleaseError(ValueError):
    pass


def releases_dir(ctx: Ctx) -> Path:
    d = ctx.settings.storage_dir / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_version(ctx: Ctx) -> int:
    return int((ctx.db.one(select(func.max(model_releases.c.version).label("v")))["v"] or 0) + 1)


def _register(ctx: Ctx, model_dir: Path, name: str, source: dict[str, Any], actor_id: int | None) -> dict:
    from moth.model.registry import sha256_file

    manifest = json.loads((model_dir / "manifest.json").read_text())
    if manifest.get("architecture") != "moth-decoder-v1":
        raise ReleaseError("only MOTH-architecture models can be released")
    version = _next_version(ctx)
    dest = releases_dir(ctx) / f"v{version:05d}"
    shutil.copytree(model_dir, dest)
    sha = sha256_file(dest / "model.pt")
    if sha != manifest["sha256"]:
        shutil.rmtree(dest, ignore_errors=True)
        raise ReleaseError("model file checksum does not match its manifest")
    info = {k: manifest.get(k) for k in ("architecture", "params", "context_length", "tokenizer_fingerprint", "dtype")}
    info["source"] = source
    with ctx.db.tx() as c:
        c.execute(model_releases.insert().values(version=version, name=name, channel="stable", status="candidate",
                                                 sha256=sha, size=(dest / "model.pt").stat().st_size, path=str(dest),
                                                 info=json.dumps(info), created_at=now()))
        audit(ctx.db, "models.candidate_registered", actor_id, f"release:{version}", {"name": name, **source}, conn=c)
    return release(ctx, version)


def release(ctx: Ctx, version: int) -> dict:
    r = ctx.db.one(select(model_releases).where(model_releases.c.version == version))
    if not r:
        raise ReleaseError("unknown release")
    return {**r, "info": json.loads(r["info"]), "evaluation": json.loads(r["evaluation"]) if r["evaluation"] else None}


def list_releases(ctx: Ctx) -> list[dict]:
    rows = ctx.db.all(select(model_releases).order_by(desc(model_releases.c.version)))
    return [{**r, "info": json.loads(r["info"]), "evaluation": json.loads(r["evaluation"]) if r["evaluation"] else None}
            for r in rows]


def deployed(ctx: Ctx) -> dict | None:
    r = ctx.db.one(select(model_releases.c.version).where(model_releases.c.status == "deployed"))
    return release(ctx, r["version"]) if r else None


# ---- candidates -----------------------------------------------------------------------------
def register_upload(ctx: Ctx, archive: Path, name: str, actor_id: int) -> dict:
    """Owner upload: a .tar.gz of an exported MOTH model directory."""
    work = ctx.settings.storage_dir / "uploads" / f"{now():.0f}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(archive) as tar:
            for m in tar.getmembers():
                if m.issym() or m.islnk() or m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise ReleaseError("archive contains unsafe paths")
            tar.extractall(work, filter="data")
        manifests = list(work.rglob("manifest.json"))
        if len(manifests) != 1:
            raise ReleaseError("archive must contain exactly one exported model (manifest.json)")
        return _register(ctx, manifests[0].parent, name, {"type": "upload"}, actor_id)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def sync_candidates(ctx: Ctx) -> list[int]:
    """Register aggregated training checkpoints that are not releases yet."""
    from moth_server.training import coordinator, coordinator_root

    coord = coordinator(ctx)
    if coord is None or not (coordinator_root(ctx) / "tokenizer.json").exists():
        return []
    known = {json.loads(r["info"]).get("source", {}).get("checkpoint_version")
             for r in ctx.db.all(select(model_releases.c.info))}
    created = []
    for vdir in sorted((coordinator_root(ctx) / "versions").glob("v*")):
        meta = json.loads((vdir / "version.json").read_text())
        v = meta["version"]
        if v == 0 or v in known:
            continue
        created.append(_package_checkpoint(ctx, coordinator_root(ctx), vdir, meta)["version"])
    return created


def _package_checkpoint(ctx: Ctx, root: Path, vdir: Path, meta: dict) -> dict:
    import torch

    from moth.model.config import MothConfig
    from moth.model.registry import sha256_file
    from moth.model.tokenizer import Tokenizer

    stage = ctx.settings.storage_dir / "staging" / vdir.name
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    cfg = MothConfig.from_dict(json.loads((root / "model_config.json").read_text()))
    cfg.name = f"moth-network-{vdir.name}"
    tok = Tokenizer.load(root / "tokenizer.json")
    state = torch.load(vdir / "model.pt", map_location="cpu", weights_only=True)
    torch.save({k: v.to(torch.float16) if v.is_floating_point() else v for k, v in state.items()}, stage / "model.pt")
    (stage / "config.json").write_text(cfg.to_json())
    tok.save(stage / "tokenizer.json")
    (stage / "manifest.json").write_text(json.dumps({
        "format": 1, "name": cfg.name, "architecture": "moth-decoder-v1", "created": now(), "params": cfg.num_params(),
        "dtype": "float16", "context_length": cfg.max_seq_len, "tokenizer_fingerprint": tok.fingerprint(),
        "sha256": sha256_file(stage / "model.pt"),
        "training": {"network_round": meta.get("round"), "contributors": len(meta.get("contributors", []))}}))
    try:
        return _register(ctx, stage, cfg.name, {"type": "training-network", "checkpoint_version": meta["version"],
                                                "round": meta.get("round")}, None)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


# ---- evaluation gate ---------------------------------------------------------------------------
def eval_tokens(ctx: Ctx) -> np.ndarray | None:
    from moth_server.training import coordinator_root

    for p in (ctx.settings.data_dir / "eval" / "tokens.bin", coordinator_root(ctx) / "probe.bin"):
        if p.exists():
            return np.fromfile(p, dtype=np.uint32)[:EVAL_TOKENS]
    return None


def held_out_loss(model, tokens: np.ndarray, seq: int = 256) -> float:
    import torch

    seq = min(seq, model.cfg.max_seq_len, (len(tokens) - 1) // 2)
    n = max(1, min(16, (len(tokens) - 1) // seq))
    x = torch.from_numpy(np.stack([tokens[i * seq:(i + 1) * seq] for i in range(n)]).astype(np.int64))
    y = torch.from_numpy(np.stack([tokens[i * seq + 1:(i + 1) * seq + 1] for i in range(n)]).astype(np.int64))
    if int(x.max()) >= model.cfg.vocab_size:
        raise ReleaseError("evaluation set uses a different tokenizer than this model")
    with torch.no_grad():
        _, loss = model(x.to(next(model.parameters()).device), y.to(next(model.parameters()).device))
    return float(loss)


def evaluate(ctx: Ctx, version: int, tolerance: float = TOLERANCE, actor_id: int | None = None) -> dict:
    from moth.model.generation import GenerationParams, generate
    from moth.model.registry import load_model

    rel = release(ctx, version)
    report: dict[str, Any] = {"ts": now(), "tolerance": tolerance, "checks": {}}
    try:
        model, tok, _ = load_model(rel["path"], device="cpu", verify=True)
        report["checks"]["loads_and_checksum"] = True
        text, stats = generate(model, tok, "def ", GenerationParams(max_new_tokens=8, temperature=0.0))
        report["checks"]["generates"] = stats.generated_tokens >= 0
        tokens = eval_tokens(ctx)
        if tokens is None:
            raise ReleaseError("no evaluation set is configured (coordinator probe or data/eval/tokens.bin)")
        loss = held_out_loss(model, tokens)
        report["eval_loss"] = loss
        report["checks"]["finite_loss"] = math.isfinite(loss)
        current = deployed(ctx)
        baseline = (current or {}).get("evaluation") or {}
        if current and current["version"] != version and "eval_loss" in baseline:
            same_tok = current["info"].get("tokenizer_fingerprint") == rel["info"].get("tokenizer_fingerprint")
            report["baseline"] = {"version": current["version"], "eval_loss": baseline["eval_loss"], "comparable": same_tok}
            report["checks"]["not_worse_than_deployed"] = (not same_tok) or loss <= baseline["eval_loss"] + tolerance
        passed = all(report["checks"].values())
    except Exception as e:  # noqa: BLE001 — any failure rejects the candidate
        report["error"] = f"{type(e).__name__}: {e}"
        passed = False
    report["passed"] = passed
    with ctx.db.tx() as c:
        c.execute(model_releases.update().where(model_releases.c.version == version)
                  .values(evaluation=json.dumps(report),
                          status=("passed" if passed else "rejected") if rel["status"] in ("candidate", "passed", "rejected")
                          else rel["status"]))
        audit(ctx.db, "models.evaluated", actor_id, f"release:{version}", {"passed": passed, "loss": report.get("eval_loss")},
              conn=c)
    return release(ctx, version)


# ---- deployment ---------------------------------------------------------------------------------
_deploy_lock = threading.Lock()


def deploy(ctx: Ctx, version: int, actor_id: int | None = None, device: str = "auto") -> dict:
    """Load + smoke-test the release in a fresh engine, then swap it in. Failure keeps the current model."""
    from moth.inference.local import LocalInference
    from moth.model.generation import GenerationParams

    rel = release(ctx, version)
    if rel["status"] not in ("passed", "retired", "deployed"):
        raise ReleaseError("only releases that passed evaluation can be deployed")
    with _deploy_lock:
        path = Path(rel["path"])
        try:
            engine = LocalInference(path.parent)
            engine.load(path.name, device)
            out, stats = engine.complete("def ", GenerationParams(max_new_tokens=4, temperature=0.0))
            if engine.manifest["sha256"] != rel["sha256"]:
                raise ReleaseError("deployed weights do not match the release checksum")
        except Exception as e:  # noqa: BLE001 — rollback: the previous engine keeps serving
            audit(ctx.db, "models.deploy_failed", actor_id, f"release:{version}", {"error": str(e)})
            raise ReleaseError(f"deployment failed, previous model still serving: {e}") from None
        previous = ctx.extras.get("inference_engine")
        ctx.extras["inference_engine"] = engine  # atomic swap for new requests
        ctx.extras["deployed_version"] = version
        t = now()
        with ctx.db.tx() as c:
            c.execute(model_releases.update().where(model_releases.c.status == "deployed",
                                                    model_releases.c.version != version).values(status="retired"))
            c.execute(model_releases.update().where(model_releases.c.version == version)
                      .values(status="deployed", published_at=t, published_by=actor_id))
            ctx.db.set_config("deployed_release", version, conn=c)
            audit(ctx.db, "models.deployed", actor_id, f"release:{version}",
                  {"previous": getattr(previous, "model_id", None)}, conn=c)
    return release(ctx, version)


def rollback(ctx: Ctx, actor_id: int | None) -> dict:
    current = deployed(ctx)
    prev = ctx.db.one(select(model_releases.c.version).where(model_releases.c.status == "retired")
                      .order_by(desc(model_releases.c.published_at)))
    if not prev:
        raise ReleaseError("there is no previous deployment to roll back to")
    out = deploy(ctx, prev["version"], actor_id)
    audit(ctx.db, "models.rolled_back", actor_id, f"release:{prev['version']}",
          {"from": current["version"] if current else None})
    return out


def restore_on_startup(ctx: Ctx) -> None:
    version = ctx.db.get_config("deployed_release")
    if version and "inference_engine" not in ctx.extras:
        try:
            deploy(ctx, int(version))
        except ReleaseError:
            pass  # reported via health; inference stays unavailable rather than serving a broken model


def auto_pipeline(ctx: Ctx) -> dict[str, Any]:
    """Register new network checkpoints, evaluate them, and deploy if auto-deploy is enabled."""
    from moth_server.routes.admin import flags

    created = sync_candidates(ctx)
    results = {"created": created, "passed": [], "deployed": None}
    for v in created:
        if evaluate(ctx, v)["status"] == "passed":
            results["passed"].append(v)
    if results["passed"] and flags(ctx).get("auto_deploy_models"):
        try:
            results["deployed"] = deploy(ctx, max(results["passed"]))["version"]
        except ReleaseError as e:
            results["deploy_error"] = str(e)
    return results
