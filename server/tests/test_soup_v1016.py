"""1.0.16: the cycle's candidates are averaged; the average replaces the best only if it scores higher."""
import json
import shutil

import torch

from moth_server import models as M
from moth_server.evolution import engine as EN, evaluation as EV, memory as MEM
from moth_server.evolution.backends import register_candidate
from moth.model.registry import sha256_file
from test_evolution import add_dataset, world  # noqa: F401


def _variant(base_path, dest, seed):
    shutil.copytree(base_path, dest)
    st = torch.load(dest / "model.pt", weights_only=True)
    torch.manual_seed(seed)
    torch.save({k: v + torch.randn_like(v) * 0.001 if v.is_floating_point() else v for k, v in st.items()}, dest / "model.pt")
    man = json.loads((dest / "manifest.json").read_text())
    man["sha256"] = sha256_file(dest / "model.pt")
    (dest / "manifest.json").write_text(json.dumps(man))
    return dest


def test_average_of_candidates_wins_only_when_better(client, settings, world, tmp_path, monkeypatch):
    ctx, o = world["ctx"], world["o"]
    d = add_dataset(client, o)
    client.post(f"/v1/admin/evolution/datasets/{d['id']}/approve", json={}, headers=o)
    EN.tick(ctx)
    cyc = MEM.cycles(ctx, 1)[0]
    exp = MEM.experiments(ctx, cyc["id"])[0]
    base = M.release(ctx, world["base"])
    ids = []
    for i in range(2):
        cand = register_candidate(ctx, exp, _variant(base["path"], tmp_path / f"c{i}", i))
        if i == 0:
            MEM.update_experiment(ctx, exp["id"], status="passed", candidate_version=cand["version"],
                                  metrics={"primary_improvement": 0.01})
        else:
            e2 = dict(exp)
            ids.append(cand["version"])
    # a second experiment record for the second candidate
    from moth_server.db import evolution_experiments
    with ctx.db.tx() as c:
        row = {k: v for k, v in ctx.db.one(evolution_experiments.select().where(evolution_experiments.c.id == exp["id"])).items()
               if k != "id"}
        row.update(status="rejected", candidate_version=ids[0], metrics=json.dumps({"primary_improvement": 0.004}))
        c.execute(evolution_experiments.insert().values(**row))
    monkeypatch.setattr(EV, "gate", lambda *a, **k: {"passed": True, "gates": [], "primary_improvement": 0.02,
                                                     "performance": {}})
    EN._try_soup(ctx, MEM.cycle(ctx, cyc["id"]), base, {})
    best = MEM.experiment(ctx, exp["id"])
    assert best["metrics"]["soup_of"] and best["candidate_version"] not in (ids[0],)
    assert any(e["kind"] == "soup.passed" for e in MEM.events(ctx, limit=20))
    EN._try_soup(ctx, MEM.cycle(ctx, cyc["id"]), base, {})  # once per cycle
    assert sum(e["kind"].startswith("soup.") for e in MEM.events(ctx, limit=40)) == 1
