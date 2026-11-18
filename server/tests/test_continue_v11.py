"""1.1 continuous model: the next run keeps training the newest declined candidate of the same live model."""
from types import SimpleNamespace

from moth_server.evolution import backends as B
from moth_server.evolution import v2


def _setup(monkeypatch, tmp_path, cand_val):
    ck = tmp_path / "cand.pt"
    ck.write_bytes(b"weights")
    from moth.training.checkpoint import file_sha256

    sha = file_sha256(ck)
    exps = [{"id": 7, "status": "rejected", "base_version": 3, "candidate_version": 9, "config": {"method": "continued"}},
            {"id": 6, "status": "rejected", "base_version": 2, "candidate_version": 8, "config": {}}]
    rels = {9: {"version": 9, "info": {"training": {"val_loss": cand_val}, "dev_checkpoint": {"path": str(ck), "sha256": sha}}}}
    monkeypatch.setattr(v2.MEM, "experiments", lambda ctx, limit=200: exps)
    import moth_server.models as M
    monkeypatch.setattr(M, "release", lambda ctx, v: rels[v])
    return {"version": 3, "info": {"training": {"val_loss": 2.0}}}, sha


def test_newest_healthy_candidate_is_continued(monkeypatch, tmp_path):
    base, sha = _setup(monkeypatch, tmp_path, 2.05)
    c = v2.continue_from(SimpleNamespace(), base)
    assert c and c["version"] == 9 and c["sha256"] == sha
    spec = B._v2_spec({"version": 3, "info": {"dev_checkpoint": {"path": "/x/dev.pt", "sha256": "d"}}},
                      {"continue_from": c, "steps": 10}, {})
    assert spec["init_checkpoint"] == c["path"] and spec["init_checkpoint_sha256"] == sha


def test_collapsed_candidate_is_not_continued(monkeypatch, tmp_path):
    base, _ = _setup(monkeypatch, tmp_path, 2.5)
    assert v2.continue_from(SimpleNamespace(), base) is None
