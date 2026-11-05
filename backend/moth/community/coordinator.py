"""Reference community training coordinator.

Not operated publicly yet — this is the implementation MOTH will run, and
anyone can run it today for a private group::

    moth coordinator init  --dir coord --model ~/.moth/models/base --dataset ~/.moth/datasets/public --shards 16
    moth coordinator serve --dir coord --port 8900 --admin-token SECRET

Contributions are validated (protocol, base version, checksum, tensor shapes,
finite values, update size, and a held-out probe loss that must not get
worse) before they are aggregated into the next checkpoint version.
"""

from __future__ import annotations

import argparse
import json
import secrets
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from moth.community.aggregation import apply_delta, federated_average, write_version
from moth.community.protocol import PROTOCOL, ContributionMeta, JobSpec, TrainSpec
from moth.community.validation import deserialize_state, tensor_bytes_sha256, validate_delta
from moth.model.config import MothConfig
from moth.model.registry import sha256_file
from moth.model.transformer import MothModel

PROBE_TOLERANCE = 0.05  # allow tiny noise in probe loss


def init_coordinator(root: Path, model_dir: Path, dataset_dir: Path, shards: int = 8, train: TrainSpec | None = None,
                     min_contributions: int = 2) -> dict:
    root = Path(root)
    if (root / "config.json").exists():
        raise FileExistsError(f"{root} is already initialised")
    manifest = json.loads((Path(model_dir) / "manifest.json").read_text())
    meta = json.loads((Path(dataset_dir) / "meta.json").read_text())
    if meta["tokenizer_fingerprint"] != manifest["tokenizer_fingerprint"]:
        raise ValueError("dataset tokenizer does not match the base model tokenizer")
    (root / "shards").mkdir(parents=True)
    tokens = np.fromfile(Path(dataset_dir) / "train.bin", dtype=np.dtype(meta["dtype"]))
    val = np.fromfile(Path(dataset_dir) / "val.bin", dtype=np.dtype(meta["dtype"]))
    shard_ids = []
    for i, part in enumerate(np.array_split(tokens, shards)):
        sid = f"shard-{i:04d}"
        part.astype(np.uint32).tofile(root / "shards" / f"{sid}.bin")
        shard_ids.append({"id": sid, "sha256": sha256_file(root / "shards" / f"{sid}.bin"), "tokens": int(len(part))})
    val[: 64 * 1024].astype(np.uint32).tofile(root / "probe.bin")
    state = torch.load(Path(model_dir) / "model.pt", map_location="cpu", weights_only=True)
    state = {k: v.float() for k, v in state.items()}
    licenses = sorted({s["license"] for s in meta.get("sources", [])})
    v0 = write_version(root / "versions", 0, state, None, {"round": 0, "contributions": 0,
                                                           "base_model": manifest["name"]})
    config = {
        "protocol": PROTOCOL, "model_config": json.loads((Path(model_dir) / "config.json").read_text()),
        "tokenizer_fingerprint": manifest["tokenizer_fingerprint"], "shards": shard_ids,
        "shard_license": ", ".join(licenses) or "unspecified", "train": (train or TrainSpec()).__dict__,
        "min_contributions": min_contributions, "round": 0, "version": 0, "version_sha256": v0["sha256"],
    }
    (root / "config.json").write_text(json.dumps(config, indent=2))
    return config


class Coordinator:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.config = json.loads((self.root / "config.json").read_text())
        self.jobs: dict[str, JobSpec] = {}
        self._next_shard = 0

    def save(self) -> None:
        tmp = self.root / "config.json.tmp"
        tmp.write_text(json.dumps(self.config, indent=2))
        tmp.replace(self.root / "config.json")

    def version_dir(self, version: int | None = None) -> Path:
        return self.root / "versions" / f"v{(self.config['version'] if version is None else version):05d}"

    def round_dir(self) -> Path:
        d = self.root / "contributions" / f"round_{self.config['round']:05d}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def next_job(self, client_id: str) -> JobSpec:
        with self.lock:
            shard = self.config["shards"][self._next_shard % len(self.config["shards"])]
            self._next_shard += 1
            job = JobSpec(uuid.uuid4().hex[:16], self.config["round"], self.config["version"],
                          self.config["version_sha256"], self.config["model_config"],
                          self.config["tokenizer_fingerprint"], shard["id"], shard["sha256"],
                          self.config["shard_license"], TrainSpec(**self.config["train"]))
            self.jobs[job.job_id] = job
            return job

    def probe_loss(self, state: dict[str, torch.Tensor]) -> float:
        cfg = MothConfig.from_dict(self.config["model_config"])
        model = MothModel(cfg)
        model.load_state_dict(state)
        model.eval()
        tokens = torch.from_numpy(np.fromfile(self.root / "probe.bin", dtype=np.uint32).astype(np.int64))
        seq = min(256, cfg.max_seq_len, len(tokens) - 1)
        n = max(1, min(8, (len(tokens) - 1) // seq))
        x = torch.stack([tokens[i * seq : i * seq + seq] for i in range(n)])
        y = torch.stack([tokens[i * seq + 1 : i * seq + seq + 1] for i in range(n)])
        with torch.no_grad():
            _, loss = model(x, y)
        return float(loss)

    def submit(self, meta: dict, body: bytes) -> dict:
        with self.lock:
            m = ContributionMeta(**{k: v for k, v in meta.items() if k in ContributionMeta.__dataclass_fields__})
            reasons = []
            if m.protocol != PROTOCOL:
                reasons.append("protocol mismatch")
            job = self.jobs.get(m.job_id)
            if job is None:
                reasons.append("unknown job")
            elif job.round != self.config["round"]:
                reasons.append("stale round")
            if m.base_sha256 != self.config["version_sha256"]:
                reasons.append("contribution is based on an outdated checkpoint")
            if tensor_bytes_sha256(body) != m.delta_sha256:
                reasons.append("checksum mismatch")
            if reasons:
                return {"accepted": False, "reasons": reasons}
            try:
                delta = deserialize_state(body)
            except Exception as e:
                return {"accepted": False, "reasons": [f"unreadable update: {e}"]}
            base = torch.load(self.version_dir() / "model.pt", map_location="cpu", weights_only=True)
            report = validate_delta(base, delta)
            if not report.ok:
                return {"accepted": False, "reasons": report.reasons}
            before = self.probe_loss(base)
            after = self.probe_loss(apply_delta(base, delta))
            if after > before + PROBE_TOLERANCE:
                return {"accepted": False, "reasons": [f"update makes held-out loss worse ({before:.3f} → {after:.3f})"]}
            cid = uuid.uuid4().hex[:12]
            (self.round_dir() / f"{cid}.pt").write_bytes(body)
            (self.round_dir() / f"{cid}.json").write_text(json.dumps({**m.to_dict(), "probe_before": before,
                                                                     "probe_after": after, "received": time.time()}))
            self.jobs.pop(m.job_id, None)
            result = {"accepted": True, "id": cid, "probe_before": before, "probe_after": after, **report.stats}
            if len(list(self.round_dir().glob("*.json"))) >= self.config["min_contributions"]:
                result["aggregated"] = self.aggregate()
            return result

    def aggregate(self) -> dict:
        with self.lock:
            rd = self.round_dir()
            metas = [json.loads(p.read_text()) for p in sorted(rd.glob("*.json"))]
            if not metas:
                raise ValueError("no contributions in this round")
            deltas = [(deserialize_state((rd / f"{p.stem}.pt").read_bytes()), float(json.loads(p.read_text())["tokens"]))
                      for p in sorted(rd.glob("*.json"))]
            base = torch.load(self.version_dir() / "model.pt", map_location="cpu", weights_only=True)
            new_state = apply_delta(base, federated_average(deltas))
            version = self.config["version"] + 1
            info = write_version(self.root / "versions", version, new_state, self.config["version_sha256"],
                                 {"round": self.config["round"], "contributions": len(metas),
                                  "probe_loss": self.probe_loss(new_state),
                                  "contributors": sorted({m["client_id"] for m in metas})})
            self.config.update({"version": version, "version_sha256": info["sha256"], "round": self.config["round"] + 1})
            self.jobs.clear()
            self.save()
            return info

    def info(self) -> dict:
        versions = [json.loads(p.read_text()) for p in sorted((self.root / "versions").glob("v*/version.json"))]
        return {"protocol": PROTOCOL, "round": self.config["round"], "version": self.config["version"],
                "version_sha256": self.config["version_sha256"], "shards": len(self.config["shards"]),
                "min_contributions": self.config["min_contributions"],
                "pending_contributions": len(list(self.round_dir().glob("*.json"))), "versions": versions}


def create_coordinator_app(root: Path, admin_token: str | None = None) -> FastAPI:
    coord = Coordinator(root)
    app = FastAPI(title="MOTH community coordinator")
    app.state.coordinator = coord

    @app.get("/v1/info")
    def info():
        return coord.info()

    @app.get("/v1/jobs/next")
    def next_job(client_id: str):
        return coord.next_job(client_id).to_dict()

    @app.get("/v1/models/{version}/weights")
    def weights(version: int):
        p = coord.version_dir(version) / "model.pt"
        if not p.exists():
            raise HTTPException(404, "unknown version")
        return FileResponse(p, media_type="application/octet-stream")

    @app.get("/v1/shards/{shard_id}")
    def shard(shard_id: str):
        if not any(s["id"] == shard_id for s in coord.config["shards"]):
            raise HTTPException(404, "unknown shard")
        return FileResponse(coord.root / "shards" / f"{shard_id}.bin", media_type="application/octet-stream")

    @app.post("/v1/contributions")
    async def contribute(request: Request):
        try:
            meta = json.loads(request.headers.get("x-moth-contribution", ""))
        except json.JSONDecodeError:
            raise HTTPException(400, "missing contribution metadata") from None
        body = await request.body()
        if len(body) > 2 * 1024**3:
            raise HTTPException(413, "update too large")
        return coord.submit(meta, body)

    @app.post("/v1/aggregate")
    def aggregate(request: Request):
        if not admin_token or not secrets.compare_digest(request.headers.get("authorization", ""), f"Bearer {admin_token}"):
            raise HTTPException(401, "admin token required")
        try:
            return coord.aggregate()
        except ValueError as e:
            raise HTTPException(409, str(e)) from None

    return app


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="moth coordinator")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init")
    i.add_argument("--dir", required=True)
    i.add_argument("--model", required=True)
    i.add_argument("--dataset", required=True)
    i.add_argument("--shards", type=int, default=8)
    i.add_argument("--min-contributions", type=int, default=2)
    i.add_argument("--steps", type=int, default=50)
    s = sub.add_parser("serve")
    s.add_argument("--dir", required=True)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8900)
    s.add_argument("--admin-token", default=None)
    a = p.parse_args(argv)
    if a.cmd == "init":
        cfg = init_coordinator(Path(a.dir), Path(a.model), Path(a.dataset), a.shards, TrainSpec(steps=a.steps),
                               a.min_contributions)
        print(json.dumps({"initialised": a.dir, "shards": len(cfg["shards"])}))
    else:
        import uvicorn

        uvicorn.run(create_coordinator_app(Path(a.dir), a.admin_token), host=a.host, port=a.port)
