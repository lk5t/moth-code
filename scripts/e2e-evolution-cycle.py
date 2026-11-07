"""A real end-to-end improvement cycle of a trained MOTH model (0.5.3 verification).

    python scripts/e2e-evolution-cycle.py --package MOTH_0.1_DIR --cache DATA/cache --out report.json

Real processes and real data only: a MOTH Cloud server (``moth-server serve``) with the model deployed,
the dataset library built from the verified dataset cache, two MOTH Worker processes that enroll over
HTTP and train shards of one distributed experiment, the server's evaluation gates (capability
benchmarks on held-out data), staged rollout, monitoring and promotion. The report records every
measurement — including a rejection, if the candidate is not better.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "crimson wings 2026!"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package", required=True, type=Path)
    ap.add_argument("--cache", required=True, type=Path, help="verified dataset cache (reused, not downloaded)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--steps", type=int, default=450)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--work", type=Path, default=None)
    a = ap.parse_args()
    work = a.work or Path(tempfile.mkdtemp(prefix="moth-e2e-evolution-"))
    data = work / "server"
    env = {**os.environ, "MOTH_SERVER_DATA_DIR": str(data), "PYTHONPATH": os.pathsep.join(
        [str(ROOT / "server"), str(ROOT / "backend"), str(ROOT / "worker")]), "OMP_NUM_THREADS": "2"}
    os.environ.update({k: env[k] for k in ("MOTH_SERVER_DATA_DIR", "PYTHONPATH")})
    for p in env["PYTHONPATH"].split(os.pathsep):
        sys.path.insert(0, p)
    t0 = time.time()
    log = lambda m: print(f"[{time.time() - t0:7.0f}s] {m}", flush=True)  # noqa: E731

    # ---- 1. the server: Owner, the model deployed, the dataset library built ----------------------------
    from moth_server import cli

    sys.stdin = io.StringIO(PASSWORD + "\n")
    cli.main(["init-owner", "--email", "owner@moth.test", "--password-stdin"])
    from fastapi.testclient import TestClient

    from moth_server import models as M
    from moth_server.app import create_app
    from moth_server.config import Settings
    from moth_server.intelligence import library

    (data / "library").mkdir(parents=True, exist_ok=True)
    os.symlink(a.cache.resolve(), data / "library" / "cache")
    with TestClient(create_app(Settings.from_env(), extras={"synchronous_jobs": True, "disable_background": True})) as c:
        ctx = c.app.state.ctx
        rel = M._register(ctx, a.package, "MOTH 0.1 — Foundation", {"type": "official", "model_version": "0.1",
                                                                     "method": "foundation"}, None)
        log(f"model registered as release v{rel['version']} ({rel['info']['params']:,} parameters)")
        log(f"evaluation: {M.evaluate(ctx, rel['version'])['status']}")
        M.deploy(ctx, rel["version"])
        ctx.db.set_config("feature_flags", {"cloud_inference_enabled": True})
        bid = library.start_build(ctx, None, {}, wait=True)
        b = library.latest_ready(ctx)
        assert b and b["id"] == bid, library.status(ctx)["builds"][:1]
        log(f"dataset library build {bid}: {b['content_sha256'][:12]} (tokenizer {b['tokenizer_fingerprint']})")
    # ---- 2. serve ------------------------------------------------------------------------------------------
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    procs = [subprocess.Popen([sys.executable, "-m", "moth_server.cli", "serve", "--port", str(port)], env=env,
                              stdout=open(work / "server.log", "w"), stderr=subprocess.STDOUT, start_new_session=True)]
    try:
        h = httpx.Client(base_url=base, timeout=60)
        for _ in range(120):
            try:
                if h.get("/v1/health").status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        tok = h.post("/v1/auth/login", json={"username": "LK5T", "password": PASSWORD}).json()["token"]
        H = {"Authorization": f"Bearer {tok}"}
        # evolution: distributed rounds on workers, staged rollout, short monitoring
        r = h.put("/v1/admin/evolution/settings", headers=H, json={
            "training": {"steps": a.steps, "lr": 2e-4, "batch_size": 4, "seq_len": 256, "eval_interval": 50,
                         "checkpoint_interval": 50},
            "backends": {"local_cpu": False, "local_gpu": False, "workers": True},
            "distributed": {"enabled": True, "min_participants": 2, "rounds": a.rounds, "eval_on_workers": True},
            "monitoring": {"minutes": 1.0, "min_requests": 1000}, "max_experiments_per_cycle": 1,
            "limits": {"min_free_memory_gb": 0.5, "min_free_disk_gb": 1.0}})
        assert r.status_code == 200, r.text
        # ---- 3. two real MOTH Worker processes -------------------------------------------------------------
        for name in ("worker-a", "worker-b"):
            e = h.post("/v1/training/enrollments", headers=H, json={"name": name}).json()
            home = work / name
            wenv = {**env, "MOTH_WORKER_INSTANCE": name}  # two workers on this one machine
            subprocess.run([sys.executable, "-m", "moth_worker.cli", "--home", str(home), "enroll", "--server", base,
                            "--token", e["token"]], env=wenv, check=True, capture_output=True)
            procs.append(subprocess.Popen([sys.executable, "-m", "moth_worker.cli", "--home", str(home), "run"],
                                          env=wenv, stdout=open(work / f"{name}.log", "w"), stderr=subprocess.STDOUT,
                                          start_new_session=True))
        time.sleep(15)
        log(f"workers online: {[w['name'] for w in h.get('/v1/training/workers', headers=H).json()['workers']]}")
        # ---- 4. one evolution cycle ---------------------------------------------------------------------
        r = h.post("/v1/admin/evolution/run", headers=H)
        assert r.status_code == 200, r.text
        last = None
        while True:
            st = h.get("/v1/admin/evolution/status", headers=H).json()
            cyc = st["cycle"]
            msg = f"cycle {cyc['id']}: {cyc['status']}"
            con = h.get("/v1/admin/evolution/contributions", headers=H).json().get("experiment")
            if con:
                msg += f" · round {con['round']}/{con['rounds']}"
            if msg != last:
                log(msg)
                last = msg
            if cyc["status"] in ("completed", "rejected", "failed", "cancelled", "rolled_back"):
                break
            time.sleep(10)
        cycle = h.get(f"/v1/admin/evolution/cycles/{cyc['id']}", headers=H).json()
        exps = [h.get(f"/v1/admin/evolution/experiments/{e['id']}", headers=H).json() for e in cycle.get("experiments", [])]
        progress = h.get("/v1/intelligence/progress", headers=H).json()
        report = {"duration_s": round(time.time() - t0), "cycle": {k: cycle.get(k) for k in ("id", "status", "candidate_version",
                                                                                            "error", "result")},
                  "experiments": [{k: e.get(k) for k in ("id", "status", "backend", "config", "metrics", "error")}
                                  for e in exps],
                  "contributions": h.get("/v1/admin/evolution/contributions", headers=H).json(),
                  "timeline": progress["timeline"], "current": progress["current"]}
        a.out.write_text(json.dumps(report, indent=1, default=str))
        log(f"cycle {cycle['id']} ended: {cycle['status']}; report written to {a.out}")
        return 0
    finally:
        for p in procs:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
