"""Official MOTH model registry and cloud deployment (server-side only).

Users never download weights: the deployed release runs in MOTH Cloud for everyone.

Lifecycle (persistent ``model_releases.status``)::

    uploading ─► uploaded ─► evaluating ─► published ─► deploying ─► deployed
                    │             │  └────► evaluated (passed every real check but scored worse than
                    │             │          the deployed model; the Owner may still publish it)
                    └─────────────┴───────► failed (with a reason and a retry path)

* **Upload** — resumable chunked uploads (``routes/uploads.py``) or aggregated training-network
  checkpoints (``sync_candidates``). Every package is validated (``moth.model.package``) before it
  is accepted; a failed package never leaves the ``failed`` state without a new upload.
* **Evaluate** — the model is actually loaded and run in an isolated subprocess
  (``moth.model.evaluate``): generation, held-out score on an evaluation dataset chosen by
  ``evalsets.select_for``, resources. Passing every check publishes the release (eligible to
  deploy); publishing never activates it.
* **Deploy** — checks memory/disk, loads the release in a fresh engine on the detected hardware
  (CUDA if present, else CPU), runs a real inference health check, and only then swaps it in.
  Any failure leaves the previous model serving. The previous release stays available for rollback.

Interrupted work (server restart mid-evaluation/deployment) is recovered at startup; releases that
failed only because no evaluation dataset was available are re-evaluated automatically once one is.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import desc, func, select

from moth_server.audit import audit
from moth_server.context import Ctx
from moth_server.db import model_releases, now

log = logging.getLogger("moth_server.models")

TOLERANCE = 0.02  # relative: a candidate may score up to 2% worse than the deployed model
EVAL_TIMEOUT_S = 1800
STATES = ("uploading", "uploaded", "evaluating", "evaluated", "published", "deploying", "deployed", "failed")
AUTO_RETRY_REASONS = ("no_eval_dataset", "interrupted")
MAX_AUTO_RETRIES = 3


class ReleaseError(ValueError):
    pass


def releases_dir(ctx: Ctx) -> Path:
    d = ctx.settings.storage_dir / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_version(ctx: Ctx, conn=None) -> int:
    q = select(func.max(model_releases.c.version).label("v"))
    return int(((ctx.db.one(q, conn) or {}).get("v") or 0) + 1)


def release(ctx: Ctx, version: int) -> dict:
    r = ctx.db.one(select(model_releases).where(model_releases.c.version == version))
    if not r:
        raise ReleaseError("unknown release")
    return {**r, "info": json.loads(r["info"] or "{}"),
            "evaluation": json.loads(r["evaluation"]) if r["evaluation"] else None}


def list_releases(ctx: Ctx) -> list[dict]:
    rows = ctx.db.all(select(model_releases).order_by(desc(model_releases.c.version)))
    return [{**r, "info": json.loads(r["info"] or "{}"),
             "evaluation": json.loads(r["evaluation"]) if r["evaluation"] else None} for r in rows]


def deployed(ctx: Ctx) -> dict | None:
    r = ctx.db.one(select(model_releases.c.version).where(model_releases.c.status == "deployed"))
    return release(ctx, r["version"]) if r else None


def _set(ctx: Ctx, version: int, status: str | None = None, conn=None, **values: Any) -> None:
    if status:
        assert status in STATES, status
        values["status"] = status
        values["state_changed_at"] = now()
    if "evaluation" in values and not isinstance(values["evaluation"], (str, type(None))):
        values["evaluation"] = json.dumps(values["evaluation"])
    stmt = model_releases.update().where(model_releases.c.version == version).values(**values)
    if conn is not None:
        conn.execute(stmt)
    else:
        with ctx.db.tx() as c:
            c.execute(stmt)


# ---- registration ---------------------------------------------------------------------------------
def reserve(ctx: Ctx, name: str, source: dict[str, Any], actor_id: int | None, sha256: str = "", size: int = 0,
            info: dict | None = None) -> int:
    """Create the release row (status ``uploading``) so the Owner Dashboard shows it immediately."""
    with ctx.db.tx() as c:
        version = _next_version(ctx, c)
        c.execute(model_releases.insert().values(
            version=version, name=name[:128], channel="stable", status="uploading", sha256=sha256 or "", size=size,
            path="", info=json.dumps({**(info or {}), "source": source}), created_at=now(), state_changed_at=now()))
        audit(ctx.db, "models.upload_started", actor_id, f"release:{version}", {"name": name, **source}, conn=c)
    return version


def finalize(ctx: Ctx, version: int, model_dir: Path, actor_id: int | None) -> dict:
    """Validate an extracted package and store it as release ``version`` (status ``uploaded``)."""
    from moth.model.package import inspect_package

    rel = release(ctx, version)
    check = inspect_package(model_dir, deep=True)
    if not check["ok"]:
        _set(ctx, version, "failed", error="Package validation failed: " + "; ".join(check["problems"]),
             evaluation={"passed": False, "reason": "package_invalid", "problems": check["problems"], "ts": now()})
        raise ReleaseError("the model package is not valid: " + "; ".join(check["problems"]))
    dup = ctx.db.one(select(model_releases.c.version).where(model_releases.c.sha256 == check["info"]["sha256"],
                                                            model_releases.c.version != version,
                                                            model_releases.c.status != "failed"))
    if dup:
        _set(ctx, version, "failed", error=f"Duplicate of release v{dup['version']} (same weights).")
        raise ReleaseError(f"these weights are already registered as release v{dup['version']}")
    dest = releases_dir(ctx) / f"v{version:05d}"
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(model_dir, dest)
    info = {k: check["info"].get(k) for k in ("architecture", "params", "context_length", "tokenizer_fingerprint",
                                              "dtype", "config", "training", "resources")}
    info["source"] = rel["info"].get("source", {})
    _set(ctx, version, "uploaded", sha256=check["info"]["sha256"], size=check["info"]["size"], path=str(dest),
         info=json.dumps(info), error=None)
    src_type = (info["source"] or {}).get("type")
    if src_type != "evolution":  # evolution records its own lineage (parent, cycle, experiment, data)
        from moth_server.evolution.memory import record_lineage

        record_lineage(ctx, version, None, "network" if src_type == "training-network" else "upload")
    audit(ctx.db, "models.uploaded", actor_id, f"release:{version}", {"sha256": check["info"]["sha256"]})
    return release(ctx, version)


def _register(ctx: Ctx, model_dir: Path, name: str, source: dict[str, Any], actor_id: int | None) -> dict:
    version = reserve(ctx, name, source, actor_id)
    return finalize(ctx, version, model_dir, actor_id)


def safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive) as tar:
        for m in tar.getmembers():
            if m.issym() or m.islnk() or m.isdev() or m.name.startswith("/") or ".." in Path(m.name).parts:
                raise ReleaseError("archive contains unsafe paths")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(dest, filter="data")
        else:  # Python < 3.10.12 / 3.11.4: members were checked above
            tar.extractall(dest)


def register_upload(ctx: Ctx, archive: Path, name: str, actor_id: int, version: int | None = None) -> dict:
    """An uploaded archive (.tar or .tar.gz) of one exported MOTH model directory."""
    if version is None:
        version = reserve(ctx, name, {"type": "upload"}, actor_id)
    work = ctx.settings.storage_dir / "uploads" / f"extract-{version}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        try:
            safe_extract(archive, work)
        except (tarfile.TarError, OSError) as e:
            _set(ctx, version, "failed", error=f"The upload is not a readable model archive: {e}")
            raise ReleaseError(f"the upload is not a readable model archive: {e}") from None
        except ReleaseError as e:
            _set(ctx, version, "failed", error=str(e))
            raise
        manifests = list(work.rglob("manifest.json"))
        if len(manifests) != 1:
            _set(ctx, version, "failed", error="The archive must contain exactly one exported model (manifest.json).")
            raise ReleaseError("archive must contain exactly one exported model (manifest.json)")
        return finalize(ctx, version, manifests[0].parent, actor_id)
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- candidates -----------------------------------------------------------------------------
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


# ---- evaluation gate ----------------------------------------------------------------------------
_eval_lock = threading.Lock()


def _run_eval_subprocess(package: Path, dataset: dict, timeout: int = EVAL_TIMEOUT_S) -> dict:
    """Run ``moth.model.evaluate`` in a separate process: a crash, hang or out-of-memory in the
    model cannot take MOTH Cloud down, and the timeout bounds it."""
    from moth_server import evalsets

    with tempfile.TemporaryDirectory(prefix="moth-eval-") as tmp:
        spec, out = Path(tmp) / "dataset.json", Path(tmp) / "report.json"
        spec.write_text(json.dumps(evalsets.spec(dataset)))
        import os

        import moth

        env = dict(os.environ)
        roots = [str(Path(moth.__file__).resolve().parents[1])]
        env["PYTHONPATH"] = os.pathsep.join(roots + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run([sys.executable, "-m", "moth.model.evaluate", "--package", str(package),
                                   "--dataset", str(spec), "--out", str(out)],
                                  capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"evaluation did not finish within {timeout // 60} minutes"}
        if out.exists():
            return json.loads(out.read_text())
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        return {"ok": False, "error": "the evaluation process crashed (exit code "
                                      f"{proc.returncode}): {' '.join(tail)[:500] or 'no output'}"}


def _baseline(ctx: Ctx, current: dict, dataset: dict) -> dict | None:
    """The deployed model's score on the same dataset (evaluated now if it was never scored on it)."""
    ev = current.get("evaluation") or {}
    scores = ev.get("scores") or {}
    if dataset["sha256"] in scores:
        return scores[dataset["sha256"]]
    rep = _run_eval_subprocess(Path(current["path"]), dataset)
    if not rep.get("ok"):
        return None
    scores[dataset["sha256"]] = rep["score"]
    ev["scores"] = scores
    _set(ctx, current["version"], evaluation=ev)
    return rep["score"]


def evaluate(ctx: Ctx, version: int, tolerance: float = TOLERANCE, actor_id: int | None = None) -> dict:
    """Evaluate a stored release (also used to retry a rejected one; no re-upload needed)."""
    from moth_server import evalsets

    rel = release(ctx, version)
    if rel["status"] in ("uploading", "deploying", "deployed"):
        raise ReleaseError(f"a release that is {rel['status']} cannot be evaluated now")
    if rel["status"] == "failed" and (rel["evaluation"] or {}).get("reason") == "package_invalid" or not rel["path"]:
        raise ReleaseError("this package failed validation; upload a corrected model instead")
    with _eval_lock:
        previous = rel["evaluation"] or {}
        attempts = int(previous.get("attempts", 0)) + 1
        dataset, skipped = evalsets.select_for(ctx, rel["info"].get("tokenizer_fingerprint"))
        if dataset is None:
            report = {"ts": now(), "passed": False, "reason": "no_eval_dataset", "attempts": attempts,
                      "skipped_datasets": skipped,
                      "guidance": "Upload held-out text in Owner Dashboard → Models → Evaluation data. The release "
                                  "will be evaluated automatically as soon as a compatible dataset exists."}
            _set(ctx, version, "failed", evaluation=report,
                 error="No compatible evaluation dataset is available. Upload one in Owner Dashboard → Models → "
                       "Evaluation data; this release will then be re-evaluated automatically.")
            audit(ctx.db, "models.evaluated", actor_id, f"release:{version}", {"passed": False, "reason": "no_eval_dataset"})
            return release(ctx, version)
        _set(ctx, version, "evaluating", error=None)
        result = _run_eval_subprocess(Path(rel["path"]), dataset)
        report: dict[str, Any] = {"ts": now(), "attempts": attempts, "dataset": evalsets.public(dataset),
                                  "skipped_datasets": skipped, "tolerance": tolerance}
        if not result.get("ok"):
            report.update(passed=False, reason="eval_failed", error=result.get("error"),
                          peak_memory_bytes=result.get("peak_memory_bytes"))
            _set(ctx, version, "failed", evaluation=report, error=f"Evaluation failed: {result.get('error')}")
            audit(ctx.db, "models.evaluated", actor_id, f"release:{version}", {"passed": False, "error": result.get("error")})
            return release(ctx, version)
        report.update({k: result.get(k) for k in ("checks", "samples", "tokens_per_second", "load_seconds",
                                                  "peak_memory_bytes", "score", "params")})
        report["eval_loss"] = result["score"]["value"]  # shown in older dashboards
        report["scores"] = {dataset["sha256"]: result["score"]}
        training = json.dumps((rel["info"].get("training") or {}).get("sources") or "").lower()
        if dataset["source"] == "builtin" and ("stdlib" in training or "python" in training):
            report["note"] = ("This model may have been trained on Python standard library code, so the built-in "
                              "dataset is not fully held-out. Upload your own held-out text for a fairer score.")
        real_checks = all(result["checks"].values())
        current = deployed(ctx)
        regression_ok = True
        if real_checks and current and current["version"] != version:
            base = _baseline(ctx, current, dataset)
            if base and base.get("metric") == result["score"]["metric"]:
                limit = base["value"] * (1 + tolerance)
                regression_ok = result["score"]["value"] <= limit
                report["baseline"] = {"version": current["version"], "score": base, "limit": limit}
                report["checks"]["not_worse_than_deployed"] = regression_ok
        report["passed"] = real_checks and regression_ok
        if not real_checks:
            failed = [k for k, v in result["checks"].items() if not v]
            report["reason"] = "eval_failed"
            _set(ctx, version, "failed", evaluation=report, error=f"Evaluation checks failed: {', '.join(failed)}")
        elif not regression_ok:
            report["reason"] = "regression"
            _set(ctx, version, "evaluated", evaluation=report,
                 error=f"Scores worse than the deployed model v{current['version']} "
                       f"({result['score']['value']:.3f} vs {report['baseline']['score']['value']:.3f}). "
                       "You can still publish it explicitly.")
        else:
            _set(ctx, version, "published", evaluation=report, error=None, published_at=now())
        audit(ctx.db, "models.evaluated", actor_id, f"release:{version}",
              {"passed": report["passed"], "score": result["score"]["value"], "dataset": dataset["id"]})
    return release(ctx, version)


def evaluate_in_background(ctx: Ctx, version: int, actor_id: int | None = None) -> None:
    def run() -> None:
        try:
            evaluate(ctx, version, actor_id=actor_id)
        except Exception as e:  # noqa: BLE001
            log.exception("evaluation of release %s failed", version)
            try:
                _set(ctx, version, "failed", error=f"Evaluation could not run: {e}",
                     evaluation={"passed": False, "reason": "interrupted", "ts": now(), "error": str(e)})
            except Exception:  # noqa: BLE001
                pass

    if ctx.extras.get("synchronous_jobs"):
        run()
    else:
        threading.Thread(target=run, name=f"evaluate-v{version}", daemon=True).start()


def publish(ctx: Ctx, version: int, actor_id: int, override_regression: bool = False) -> dict:
    """Mark an evaluated release as eligible for deployment. Only a release that passed every real
    check can be published; ``override_regression`` accepts a lower score than the deployed model."""
    rel = release(ctx, version)
    ev = rel["evaluation"] or {}
    if rel["status"] == "published":
        return rel
    if rel["status"] != "evaluated":
        raise ReleaseError("only evaluated releases can be published" if rel["status"] != "failed" else
                           "this release failed evaluation; retry the evaluation first")
    checks = {k: v for k, v in (ev.get("checks") or {}).items() if k != "not_worse_than_deployed"}
    if not checks or not all(checks.values()):
        raise ReleaseError("this release has not passed every evaluation check")
    if not ev.get("passed") and not override_regression:
        raise ReleaseError("this release scored worse than the deployed model; confirm to publish it anyway")
    _set(ctx, version, "published", published_at=now(), published_by=actor_id, error=None)
    audit(ctx.db, "models.published", actor_id, f"release:{version}", {"override_regression": override_regression})
    return release(ctx, version)


# ---- deployment ---------------------------------------------------------------------------------
_deploy_lock = threading.Lock()


def resource_problems(rel: dict, device: str) -> list[str]:
    from moth_server.routes.system import memory

    need = (rel["info"].get("resources") or {})
    problems = []
    mem = memory()
    if device == "cpu" and mem and need.get("ram_cpu_bytes") and mem["available"] < need["ram_cpu_bytes"]:
        problems.append(f"not enough free memory: the model needs about {need['ram_cpu_bytes'] / 2**30:.1f} GB, "
                        f"{mem['available'] / 2**30:.1f} GB is available")
    return problems


def deploy(ctx: Ctx, version: int, actor_id: int | None = None, device: str = "auto") -> dict:
    """Load + health-check the release in a fresh engine, then swap it in. Failure keeps the current model."""
    from moth.inference.local import LocalInference
    from moth.model.generation import GenerationParams
    from moth.training.trainer import pick_device

    rel = release(ctx, version)
    if rel["status"] not in ("published", "deployed"):
        raise ReleaseError("only published releases (evaluated and passed) can be deployed"
                           if rel["status"] != "deploying" else "this release is already being deployed")
    with _deploy_lock:
        dev = pick_device(device)
        problems = resource_problems(rel, "cuda" if dev.startswith("cuda") else "cpu")
        if problems:
            _set(ctx, version, error="Deployment blocked: " + "; ".join(problems))
            audit(ctx.db, "models.deploy_failed", actor_id, f"release:{version}", {"error": problems})
            raise ReleaseError("deployment blocked, previous model still serving: " + "; ".join(problems))
        prior_status = rel["status"]
        _set(ctx, version, "deploying")
        path = Path(rel["path"])
        try:
            engine = LocalInference(path.parent)
            engine.load(path.name, dev)
            if engine.manifest["sha256"] != rel["sha256"]:
                raise ReleaseError("deployed weights do not match the release checksum")
            out, stats = engine.complete("def ", GenerationParams(max_new_tokens=8, temperature=0.0, top_k=1))
            if stats.generated_tokens < 1:
                raise ReleaseError("health check failed: the model produced no tokens")
        except Exception as e:  # noqa: BLE001 — rollback: the previous engine keeps serving
            corrupted = "corrupted" in str(e) or "checksum" in str(e)
            _set(ctx, version, "failed" if corrupted else prior_status, error=f"Deployment failed: {e}")
            audit(ctx.db, "models.deploy_failed", actor_id, f"release:{version}", {"error": str(e)})
            raise ReleaseError(f"deployment failed, previous model still serving: {e}") from None
        previous = ctx.extras.get("inference_engine")
        ctx.extras["inference_engine"] = engine  # atomic swap for new requests
        ctx.extras["deployed_version"] = version
        t = now()
        with ctx.db.tx() as c:
            c.execute(model_releases.update().where(model_releases.c.status == "deployed",
                                                    model_releases.c.version != version)
                      .values(status="published", previously_deployed=True, state_changed_at=t))
            _set(ctx, version, "deployed", conn=c, deployed_at=t, published_by=actor_id, error=None,
                 info=json.dumps({**rel["info"], "serving": {"device": dev, "health_check": out[:120],
                                                             "tokens_per_second": round(stats.tokens_per_sec, 1)}}))
            ctx.db.set_config("deployed_release", version, conn=c)
            audit(ctx.db, "models.deployed", actor_id, f"release:{version}",
                  {"previous": getattr(previous, "model_id", None), "device": dev}, conn=c)
    return release(ctx, version)


def rollback(ctx: Ctx, actor_id: int | None) -> dict:
    current = deployed(ctx)
    q = (select(model_releases.c.version).where(model_releases.c.status == "published",
                                                model_releases.c.previously_deployed.is_(True))
         .order_by(desc(model_releases.c.deployed_at)))
    prev = ctx.db.one(q)
    if not prev:
        raise ReleaseError("there is no previous deployment to roll back to")
    out = deploy(ctx, prev["version"], actor_id)
    audit(ctx.db, "models.rolled_back", actor_id, f"release:{prev['version']}",
          {"from": current["version"] if current else None})
    return out


def recover_interrupted(ctx: Ctx) -> list[int]:
    """After a restart nothing may stay stuck in a transient state."""
    fixed = []
    deployed_version = ctx.db.get_config("deployed_release")
    for r in ctx.db.all(select(model_releases).where(model_releases.c.status.in_(("evaluating", "deploying")))):
        if r["status"] == "evaluating":
            ev = json.loads(r["evaluation"] or "{}")
            ev.update(passed=False, reason="interrupted", ts=now())
            _set(ctx, r["version"], "failed", evaluation=ev,
                 error="Evaluation was interrupted by a server restart; it will be retried automatically.")
        else:
            _set(ctx, r["version"], "deployed" if deployed_version == r["version"] else "published",
                 error="Deployment was interrupted by a server restart; deploy it again.")
        fixed.append(r["version"])
    return fixed


def restore_on_startup(ctx: Ctx) -> None:
    recover_interrupted(ctx)
    version = ctx.db.get_config("deployed_release")
    if version and "inference_engine" not in ctx.extras:
        try:
            deploy(ctx, int(version))
        except ReleaseError:
            log.error("the deployed model v%s could not be restored after restart", version)


def retry_candidates(ctx: Ctx) -> list[int]:
    """Releases that failed only for a recoverable reason: no evaluation data yet (retried whenever a
    dataset becomes available) or an interrupted evaluation (retried a few times)."""
    out = []
    for r in ctx.db.all(select(model_releases).where(model_releases.c.status == "failed")):
        ev = json.loads(r["evaluation"] or "{}")
        if not r["path"]:
            continue
        if "no evaluation set is configured" in str(ev.get("error", "")):  # v0.2 rejection, before reason codes
            ev["reason"] = "no_eval_dataset"
        if ev.get("reason") == "no_eval_dataset" or (ev.get("reason") == "interrupted"
                                                     and int(ev.get("attempts", 0)) <= MAX_AUTO_RETRIES):
            out.append(r["version"])
    return out


def auto_pipeline(ctx: Ctx) -> dict[str, Any]:
    """Register network checkpoints, evaluate new and recoverable releases, optionally auto-deploy."""
    from moth_server import evalsets
    from moth_server.routes.admin import flags

    created = sync_candidates(ctx)
    results: dict[str, Any] = {"created": created, "evaluated": [], "passed": [], "deployed": None}
    def evolution(v: int) -> bool:  # evolution candidates are evaluated by their own cycle
        return release(ctx, v)["info"].get("source", {}).get("type") == "evolution"

    pending = [r["version"] for r in ctx.db.all(select(model_releases.c.version).where(model_releases.c.status == "uploaded"))
               if not evolution(r["version"])]
    for v in [v for v in retry_candidates(ctx) if not evolution(v)]:
        rel = release(ctx, v)
        if (rel["evaluation"] or {}).get("reason") == "no_eval_dataset" or "no evaluation set" in str((rel["evaluation"] or {}).get("error", "")):
            ds, _ = evalsets.select_for(ctx, rel["info"].get("tokenizer_fingerprint"))
            if ds is None:
                continue  # still nothing to evaluate with; don't burn attempts
        pending.append(v)
    for v in sorted(set(pending)):
        try:
            st = evaluate(ctx, v)["status"]
        except ReleaseError:
            continue
        results["evaluated"].append(v)
        if st == "published":
            results["passed"].append(v)
    network = [v for v in results["passed"] if release(ctx, v)["info"].get("source", {}).get("type") == "training-network"]
    if network and flags(ctx).get("auto_deploy_models"):
        try:
            results["deployed"] = deploy(ctx, max(network))["version"]
        except ReleaseError as e:
            results["deploy_error"] = str(e)
    return results
