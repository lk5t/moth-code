"""Tokenizer, dataset, training-run, evaluation and job routes."""

from __future__ import annotations

import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from moth.jobs import Job, JobManager
from moth.model.config import PRESETS
from moth.model.tokenizer import Tokenizer
from moth.server.services import NotFound, Services
from moth.training.sources import CATALOG, LicenseError, SourceSpec, resolve_license
from moth.training.trainer import TrainConfig


class SourceIn(BaseModel):
    spec: str
    license: str = ""
    max_documents: int | None = None
    max_bytes: int | None = None
    options: dict[str, Any] = {}


class TokenizerIn(BaseModel):
    name: str
    sources: list[SourceIn]
    vocab_size: int = 16384
    max_mb: float = 200.0


class DatasetIn(BaseModel):
    name: str
    tokenizer: str
    sources: list[SourceIn]
    val_fraction: float = 0.02


class RunIn(BaseModel):
    name: str
    dataset: str
    preset: str = "moth-50m"
    config: dict[str, Any] = {}


class ResumeIn(BaseModel):
    max_steps: int | None = None


class ExportIn(BaseModel):
    name: str
    which: str = "best"  # best | latest
    dtype: str = "float16"


class EvalIn(BaseModel):
    dataset: str | None = None
    device: str = "cpu"


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip("-.")
    if not s:
        raise HTTPException(422, "name must contain letters or digits")
    return s


def register(app: FastAPI, svc: Services, deps) -> None:
    jobs = JobManager(svc.paths.home / "jobs", svc.bus.publish)
    svc.extras["jobs"] = jobs

    # Runs left "running" by a crash/forced exit are resumable.
    svc.db.execute("UPDATE training_runs SET status='interrupted' WHERE status='running'")

    def specs(sources: list[SourceIn]) -> list[dict]:
        out = []
        for s in sources:
            spec = SourceSpec(s.spec, s.license, s.max_documents, s.max_bytes, s.options)
            try:
                resolve_license(spec)
            except LicenseError as e:
                raise HTTPException(422, str(e)) from None
            out.append(spec.to_dict())
        return out

    # ---- catalog/presets ---------------------------------------------------------
    @app.get("/api/training/presets", dependencies=deps)
    def presets():
        return [{**c.to_dict(), "params": c.num_params()} for c in PRESETS.values()]

    @app.get("/api/training/catalog", dependencies=deps)
    def catalog():
        return CATALOG

    # ---- tokenizers ------------------------------------------------------------------
    @app.get("/api/tokenizers", dependencies=deps)
    def tokenizers():
        out = []
        for p in sorted(svc.paths.tokenizers.glob("*.json")):
            try:
                t = Tokenizer.load(p)
                out.append({"name": p.stem, "path": str(p), "vocab_size": t.vocab_size, "fingerprint": t.fingerprint()})
            except Exception:
                continue
        return out

    @app.post("/api/tokenizers", dependencies=deps)
    def train_tokenizer(body: TokenizerIn):
        name = _slug(body.name)
        out = svc.paths.tokenizers / f"{name}.json"
        if out.exists():
            raise HTTPException(409, f"tokenizer {name} already exists")
        args = ["tokenizer", "--vocab-size", str(body.vocab_size), "--max-mb", str(body.max_mb), "--out", str(out)]
        for s in specs(body.sources):
            args += ["--source", json.dumps(s)]
        job = jobs.start("tokenizer", f"Train tokenizer {name}", args, {"name": name})
        svc.db.log_activity("training", f"Started tokenizer training: {name}")
        return job.public()

    # ---- datasets -------------------------------------------------------------------
    @app.get("/api/datasets", dependencies=deps)
    def datasets():
        out = []
        for d in sorted(svc.paths.datasets.iterdir()):
            mf = d / "meta.json"
            if mf.exists():
                out.append({"name": d.name, "path": str(d), **json.loads(mf.read_text())})
        return out

    @app.post("/api/datasets", dependencies=deps)
    def prepare(body: DatasetIn):
        name = _slug(body.name)
        out = svc.paths.datasets / name
        if (out / "meta.json").exists():
            raise HTTPException(409, f"dataset {name} already exists")
        tok = svc.paths.tokenizers / f"{_slug(body.tokenizer)}.json"
        if not tok.exists():
            raise NotFound(f"tokenizer {body.tokenizer} not found")
        args = ["prepare", "--tokenizer", str(tok), "--out", str(out), "--val-fraction", str(body.val_fraction)]
        for s in specs(body.sources):
            args += ["--source", json.dumps(s)]
        job = jobs.start("dataset", f"Prepare dataset {name}", args, {"name": name})
        svc.db.log_activity("training", f"Started dataset preparation: {name}")
        return job.public()

    @app.delete("/api/datasets/{name}", dependencies=deps)
    def delete_dataset(name: str):
        d = svc.paths.datasets / _slug(name)
        if not d.exists():
            raise NotFound("dataset not found")
        shutil.rmtree(d)
        return {"ok": True}

    # ---- training runs ------------------------------------------------------------
    def on_train_event(run_id: str):
        def handler(job: Job, e: dict) -> None:
            kind = e.get("kind")
            now = time.time()
            if kind == "metrics":
                svc.db.execute(
                    "INSERT INTO training_metrics(run_id, step, split, loss, lr, tokens_per_sec, ts) VALUES (?,?,?,?,?,?,?)",
                    (run_id, e["step"], e["split"], e["loss"], e.get("lr"), e.get("tokens_per_sec"), now))
                svc.db.execute("UPDATE training_runs SET step=?, updated_at=? WHERE id=?", (e["step"], now, run_id))
            elif kind == "start":
                svc.db.execute("UPDATE training_runs SET status='running', error=NULL, updated_at=? WHERE id=?",
                               (now, run_id))
            elif kind == "error":
                svc.db.execute("UPDATE training_runs SET error=?, updated_at=? WHERE id=?", (e.get("message"), now, run_id))
            elif kind == "exit":
                status = {"completed": "completed", "cancelled": "stopped"}.get(job.status, "failed")
                if status == "completed" and job.result and job.result.get("reason") == "stopped":
                    status = "stopped"
                err = job.error if status == "failed" else None
                svc.db.execute("UPDATE training_runs SET status=?, error=COALESCE(?, error), updated_at=? WHERE id=?",
                               (status, err, now, run_id))
                svc.db.log_activity("training", f"Training run {run_id} {status}")
            svc.bus.publish("training", {"run_id": run_id, **e,
                                         "status": _run(run_id)["status"] if kind in ("exit", "start") else "running"})
        return handler

    def _run(run_id: str) -> dict:
        r = svc.db.one("SELECT * FROM training_runs WHERE id=?", (run_id,))
        if not r:
            raise NotFound("training run not found")
        r["config"] = json.loads(r["config"])
        return r

    def launch(run_id: str) -> Job:
        if jobs.running("train"):
            raise HTTPException(409, "another training run is in progress; stop it first")
        run = _run(run_id)
        cfg_path = Path(run["out_dir"]) / "config.json"
        cfg_path.write_text(json.dumps(run["config"], indent=2))
        stop_file = Path(run["out_dir"]) / "STOP"
        job = jobs.start("train", f"Train {run['name']}", ["train", "--config", str(cfg_path)],
                         {"run_id": run_id}, on_event=on_train_event(run_id), stop_file=stop_file)
        svc.db.execute("UPDATE training_runs SET status='running', updated_at=? WHERE id=?", (time.time(), run_id))
        return job

    @app.get("/api/training/runs", dependencies=deps)
    def runs():
        rows = svc.db.query("SELECT * FROM training_runs ORDER BY created_at DESC")
        for r in rows:
            r["config"] = json.loads(r["config"])
            best = svc.db.one("SELECT MIN(loss) AS best FROM training_metrics WHERE run_id=? AND split='val'", (r["id"],))
            r["best_val"] = best["best"] if best else None
            r["job"] = next((j.id for j in jobs.running("train") if j.meta.get("run_id") == r["id"]), None)
        return rows

    @app.post("/api/training/runs", dependencies=deps)
    def create_run(body: RunIn):
        if body.preset not in PRESETS:
            raise HTTPException(422, f"unknown preset {body.preset}")
        if jobs.running("train"):
            raise HTTPException(409, "another training run is in progress; stop it first")
        ds = svc.paths.datasets / _slug(body.dataset)
        if not (ds / "meta.json").exists():
            raise NotFound(f"dataset {body.dataset} not found")
        run_id = uuid.uuid4().hex[:10]
        out_dir = svc.paths.runs / f"{_slug(body.name)}-{run_id}"
        out_dir.mkdir(parents=True)
        try:
            cfg = TrainConfig.from_dict({**body.config, "run_name": body.name, "dataset": str(ds),
                                         "out_dir": str(out_dir), "preset": body.preset})
        except TypeError as e:
            raise HTTPException(422, str(e)) from None
        now = time.time()
        svc.db.execute("INSERT INTO training_runs(id, name, status, config, out_dir, created_at, updated_at) "
                       "VALUES (?,?,?,?,?,?,?)", (run_id, body.name, "created", json.dumps(cfg.to_dict()),
                                                  str(out_dir), now, now))
        try:
            launch(run_id)
        except Exception:
            svc.db.execute("DELETE FROM training_runs WHERE id=?", (run_id,))
            shutil.rmtree(out_dir, ignore_errors=True)
            raise
        svc.db.log_activity("training", f"Started training run {body.name} ({body.preset})")
        return _run(run_id)

    @app.post("/api/training/runs/{run_id}/stop", dependencies=deps)
    def stop_run(run_id: str):
        _run(run_id)
        job = next((j for j in jobs.running("train") if j.meta.get("run_id") == run_id), None)
        if not job:
            raise HTTPException(409, "run is not active")
        jobs.stop(job.id, grace=300)  # trainer saves a checkpoint before exiting
        return {"ok": True}

    @app.post("/api/training/runs/{run_id}/resume", dependencies=deps)
    def resume_run(run_id: str, body: ResumeIn):
        run = _run(run_id)
        if body.max_steps:
            run["config"]["max_steps"] = body.max_steps
            svc.db.execute("UPDATE training_runs SET config=? WHERE id=?", (json.dumps(run["config"]), run_id))
        launch(run_id)
        return _run(run_id)

    @app.get("/api/training/runs/{run_id}/metrics", dependencies=deps)
    def run_metrics(run_id: str):
        _run(run_id)
        return svc.db.query("SELECT step, split, loss, lr, tokens_per_sec, ts FROM training_metrics WHERE run_id=? "
                            "ORDER BY step", (run_id,))

    @app.delete("/api/training/runs/{run_id}", dependencies=deps)
    def delete_run(run_id: str):
        run = _run(run_id)
        if any(j.meta.get("run_id") == run_id for j in jobs.running("train")):
            raise HTTPException(409, "stop the run before deleting it")
        shutil.rmtree(run["out_dir"], ignore_errors=True)
        svc.db.execute("DELETE FROM training_metrics WHERE run_id=?", (run_id,))
        svc.db.execute("DELETE FROM training_runs WHERE id=?", (run_id,))
        return {"ok": True}

    @app.post("/api/training/runs/{run_id}/export", dependencies=deps)
    def export_run(run_id: str, body: ExportIn):
        from moth.model.registry import export_model
        from moth.training.checkpoint import latest_checkpoint

        run = _run(run_id)
        ckpt_dir = Path(run["out_dir"]) / "checkpoints"
        ckpt = ckpt_dir / "best.pt" if body.which == "best" else latest_checkpoint(Path(run["out_dir"]))
        if ckpt is None or not ckpt.exists():
            raise HTTPException(409, "this run has no checkpoint yet" if body.which != "best"
                                else "no best checkpoint yet (it is written after the first validation)")
        try:
            info = export_model(ckpt, svc.paths.models, body.name, body.dtype)
        except FileExistsError as e:
            raise HTTPException(409, str(e)) from None
        svc.db.log_activity("model", f"Exported model {info['name']} from run {run['name']}")
        svc.bus.publish("model", {"exported": info["id"]})
        return info

    # ---- evaluation & jobs --------------------------------------------------------
    @app.post("/api/models/{model_id}/evaluate", dependencies=deps)
    def evaluate(model_id: str, body: EvalIn):
        mdir = svc.paths.models / model_id
        if not (mdir / "manifest.json").exists():
            raise NotFound("model not found")
        args = ["eval", "--model", str(mdir), "--device", body.device]
        if body.dataset:
            args += ["--dataset", str(svc.paths.datasets / _slug(body.dataset))]

        def save(job: Job, e: dict) -> None:
            if e.get("kind") == "done":
                (mdir / "evaluation.json").write_text(json.dumps({**e["report"], "ts": time.time(),
                                                                  "dataset": body.dataset}, indent=2))

        return jobs.start("eval", f"Evaluate {model_id}", args, {"model": model_id}, on_event=save).public()

    @app.get("/api/models/{model_id}/evaluation", dependencies=deps)
    def evaluation(model_id: str):
        p = svc.paths.models / model_id / "evaluation.json"
        if not p.exists():
            raise NotFound("no evaluation yet")
        return json.loads(p.read_text())

    @app.get("/api/jobs", dependencies=deps)
    def list_jobs():
        return jobs.list()

    @app.post("/api/jobs/{job_id}/stop", dependencies=deps)
    def stop_job(job_id: str):
        if not jobs.stop(job_id):
            raise HTTPException(409, "job is not running")
        return {"ok": True}
