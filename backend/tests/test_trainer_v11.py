"""1.1: mistakes-first domain focus and the learning-rate probe."""
from moth.training import trainer as T


def test_focus_multipliers_are_bounded_and_favour_weak_domains():
    m = T.focus_multipliers({"code": 3.0, "conversation": 1.0, "math": 2.0})
    assert m["code"] > m["math"] > m["conversation"]
    assert all(T.FOCUS_MIN <= v <= T.FOCUS_MAX for v in m.values())
    assert T.focus_multipliers({"all": 2.0}) == {}
    w = T.focused({"code": 0.5, "conversation": 0.5}, {"code": 1.5, "conversation": 0.5})
    assert w == {"code": 0.75, "conversation": 0.25}
    assert T.focused({"a": 1.0}, {}) == {"a": 1.0}


def test_real_run_probes_the_rate_and_focuses(tmp_path, monkeypatch):
    import json

    from tests.test_continue_v053 import _mixture, _spec
    from moth.training.continue_run import run

    monkeypatch.setattr(T, "LR_PROBE_MIN_RUN", 10)
    mix, base = _mixture(tmp_path)
    r = run(_spec(tmp_path, "p1", mix, base, lr_probe=True, focus_weak=True))
    assert r["reason"] == "completed"
    ev = [json.loads(x) for x in (tmp_path / "p1" / "events.jsonl").read_text().splitlines()]
    probe = next(e for e in ev if e["kind"] == "lr_probe")
    assert probe["factor"] in T.LR_PROBE_FACTORS and len(probe["val_loss"]) == 3
    assert ev.index(probe) < next(i for i, e in enumerate(ev) if e["kind"] == "start")
    focus = [e for e in ev if e["kind"] == "focus"]
    assert focus and set(focus[0]["multipliers"]) == {"language", "code"}


def test_transfer_state_copies_the_overlap_into_a_bigger_shape():
    import torch

    from moth.model.config import preset
    from moth.model.growth import transfer_state
    from moth.model.transformer import MothModel

    small = MothModel(preset("moth-tiny", vocab_size=448)).state_dict()
    big_cfg = preset("moth-tiny", vocab_size=448, d_model=96, n_layers=3, ffn_hidden=256)
    big = MothModel(big_cfg).state_dict()
    out, frac = transfer_state(small, big)
    assert 0 < frac < 1 and set(out) == set(big)
    assert torch.equal(out["embed.weight"][:, :64], small["embed.weight"])
    assert torch.equal(out["layers.0.mlp.w1.weight"][:192, :64], small["layers.0.mlp.w1.weight"])
    assert torch.equal(out["layers.2.mlp.w1.weight"], big["layers.2.mlp.w1.weight"])  # a new layer stays fresh
    MothModel(big_cfg).load_state_dict(out)


def test_bigger_successor_starts_from_the_current_model(tmp_path):
    import json

    from tests.test_continue_v053 import _mixture, _spec
    from moth.training.continue_run import run

    mix, base = _mixture(tmp_path)
    r = run(_spec(tmp_path, "s1", mix, base, from_scratch=True, transfer_from_base=True,
                  architecture={"d_model": 96, "n_heads": 4, "n_kv_heads": 4, "n_layers": 3, "ffn_hidden": 256}))
    assert r["reason"] == "completed" and r["params"] > 0
    ev = [json.loads(x) for x in (tmp_path / "s1" / "events.jsonl").read_text().splitlines()]
    assert 0 < next(e for e in ev if e["kind"] == "transfer")["fraction"] < 1
