"""0.8.3: MOTH Cloud and the workers train the *same* experiment, conversation data included.

Shared (distributed) rounds used to carry no loss mask, so any mixture with conversation data (which
learns only the assistant's replies) could never be shared: MOTH Cloud and a worker each trained a
separate experiment instead. Each round's shard now carries its mask, checked by SHA-256 like the shard.
"""
import json

from sqlalchemy import select

from conftest import H
from moth_server.db import training_jobs
from moth_server.evolution import engine as EN, memory as MEM
from test_evolution import drive
from test_network_v063 import _enroll, _world


def test_shared_rounds_carry_the_conversation_mask(client, owner, tmp_path, monkeypatch):
    from moth.model.transformer import MothModel
    from moth_worker.client import WorkerClient
    from moth_worker.runner import WorkerRunner

    from test_evolution import FAST

    ctx = _world(client, owner, tmp_path, monkeypatch, training={**FAST["training"], "steps": 8},
                 backends={"local_cpu": False, "local_gpu": False, "workers": True},
                 distributed={"min_participants": 2, "rounds": 1})
    ws = [_enroll(client, owner), _enroll(client, owner)]
    cyc = drive(ctx, lambda c: any(e["backend"] == "distributed" for e in MEM.experiments(ctx, c["id"]))
                or c["status"] in MEM.TERMINAL_CYCLE, timeout=300)
    exp = next(e for e in MEM.experiments(ctx, cyc["id"]) if e["backend"] == "distributed")
    jobs = ctx.db.all(select(training_jobs).where(training_jobs.c.kind == "dist_shard"))
    assert len(jobs) == 2
    for j in jobs:
        spec = json.loads(j["spec"])
        assert spec["mask_sha256"] and spec["min_worker_version"] == "0.6.4"
    seen = []
    real = MothModel.forward

    def forward(self, idx, targets=None, loss_mask=None, *a, **k):
        if targets is not None and self.training:
            seen.append(None if loss_mask is None else (int(loss_mask.numel()), int(loss_mask.sum())))
        return real(self, idx, targets, loss_mask, *a, **k)

    monkeypatch.setattr(MothModel, "forward", forward)
    for i, w in enumerate(ws):
        job = client.post("/v1/worker/jobs/claim", headers=H(w["worker_token"])).json()
        assert job["kind"] == "dist_shard"
        # the mask is served for shared rounds too, and matches the shard
        m = client.get(f"/v1/worker/jobs/{job['id']}/mask", headers=H(w["worker_token"]))
        assert m.status_code == 200 and len(m.content) * 4 == len(
            client.get(f"/v1/worker/jobs/{job['id']}/shard", headers=H(w["worker_token"])).content)
        r = WorkerRunner(WorkerClient("http://t", w["worker_token"], http=client), tmp_path / f"w{i}",
                         allow_cpu=True, log=lambda m: None, heartbeat_seconds=3600, update_check_seconds=None)
        assert r.run_job(job)["accepted"]
    masked = [s for s in seen if s]
    assert masked and None not in seen and any(ones < n for n, ones in masked)  # replies only, never nothing
    EN.tick(ctx)
    st = MEM.experiment(ctx, exp["id"])["resources"]["distributed"]
    assert st["round"] == 1 and st["history"][0]["participants"] == 2


def test_private_data_is_never_shared(client, owner, tmp_path, monkeypatch):
    """Private training data still trains only on MOTH Cloud, never in shared rounds."""
    from moth_server.evolution import backends as B

    ctx = _world(client, owner, tmp_path, monkeypatch, distributed={"min_participants": 2, "rounds": 1},
                 backends={"local_cpu": True, "local_gpu": False, "workers": True})
    _enroll(client, owner), _enroll(client, owner)
    monkeypatch.setattr(B, "worker_training_supported", lambda ctx, exp, masks=False: False)
    cyc = drive(ctx, lambda c: any(e["status"] == "running" for e in MEM.experiments(ctx, c["id"]))
                or c["status"] in MEM.TERMINAL_CYCLE, timeout=300)
    exps = MEM.experiments(ctx, cyc["id"])
    assert exps and all(e["backend"] in (None, "local") for e in exps), [(e["backend"], e["status"]) for e in exps]
    assert not ctx.db.all(select(training_jobs).where(training_jobs.c.kind.in_(("dist_shard", "evolve_train"))))
