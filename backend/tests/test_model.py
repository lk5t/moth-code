import torch

from moth.model.config import PRESETS, MothConfig, preset
from moth.model.generation import GenerationParams, generate_stream
from moth.model.transformer import MothModel


def tiny(**kw):
    return MothModel(preset("moth-tiny", **kw))


def test_param_count_matches_analytic():
    for name in ("moth-tiny", "moth-small"):
        cfg = PRESETS[name]
        assert MothModel(cfg).num_params() == cfg.num_params()
    assert 45e6 < PRESETS["moth-50m"].num_params() < 55e6


def test_forward_shapes_and_loss():
    torch.manual_seed(0)
    m = tiny()
    x = torch.randint(0, m.cfg.vocab_size, (2, 16))
    y = torch.randint(0, m.cfg.vocab_size, (2, 16))
    logits, loss = m(x, y)
    assert logits.shape == (2, 16, m.cfg.vocab_size)
    # Random init → loss close to ln(vocab) for unrelated targets
    assert abs(loss.item() - torch.log(torch.tensor(float(m.cfg.vocab_size))).item()) < 1.0


def test_causality():
    torch.manual_seed(0)
    m = tiny().eval()
    x = torch.randint(0, m.cfg.vocab_size, (1, 12))
    y = x.clone()
    y[0, 8:] = (y[0, 8:] + 1) % m.cfg.vocab_size
    a, _ = m(x)
    b, _ = m(y)
    assert torch.allclose(a[0, :8], b[0, :8], atol=1e-5)
    assert not torch.allclose(a[0, 8:], b[0, 8:], atol=1e-5)


def test_kv_cache_matches_full_recompute():
    torch.manual_seed(0)
    m = tiny().eval()
    x = torch.randint(0, m.cfg.vocab_size, (1, 10))
    full, _ = m(x)
    cache = m.new_cache()
    out, _ = m(x[:, :6], cache=cache, start_pos=0)
    assert torch.allclose(out[0, -1], full[0, 5], atol=1e-4)
    for t in range(6, 10):
        out, _ = m(x[:, t : t + 1], cache=cache, start_pos=t)
        assert torch.allclose(out[0, -1], full[0, t], atol=1e-4)


def test_grouped_query_attention_runs():
    m = MothModel(MothConfig(name="gqa", vocab_size=128, d_model=64, n_layers=1, n_heads=4, n_kv_heads=2,
                             ffn_hidden=128, max_seq_len=64))
    x = torch.randint(0, 128, (2, 8))
    _, loss = m(x, x)
    loss.backward()
    assert m.cfg.num_params() == m.num_params()


def test_backprop_updates_every_trainable_weight():
    torch.manual_seed(0)
    m = tiny()
    before = {n: p.detach().clone() for n, p in m.named_parameters()}
    opt = m.configure_optimizer(1e-2, 0.0)
    x = torch.randint(0, m.cfg.vocab_size, (4, 32))
    _, loss = m(x[:, :-1], x[:, 1:])
    loss.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in m.parameters())
    opt.step()
    changed = [n for n, p in m.named_parameters() if not torch.equal(before[n], p.detach())]
    assert set(changed) == set(before), "every parameter must receive an update"


def test_generation_greedy_is_deterministic_and_respects_max_tokens(tiny_pipeline):
    torch.manual_seed(0)
    tok = tiny_pipeline["tokenizer"]
    m = tiny(vocab_size=448).eval()
    p = GenerationParams(max_new_tokens=15, temperature=0.0)
    a = "".join(generate_stream(m, tok, [tok.bos_id] + tok.encode("def "), p, stop_ids=set()))
    b = "".join(generate_stream(m, tok, [tok.bos_id] + tok.encode("def "), p, stop_ids=set()))
    assert a == b
    assert len(tok.encode(a)) <= 15 + 2


def test_generation_cancellation(tiny_pipeline):
    import threading

    tok = tiny_pipeline["tokenizer"]
    m = tiny(vocab_size=448).eval()
    cancel = threading.Event()
    cancel.set()
    from moth.model.generation import GenerationStats

    stats = GenerationStats()
    out = "".join(generate_stream(m, tok, [tok.bos_id], GenerationParams(max_new_tokens=50), stop_ids=set(),
                                  cancel_event=cancel, stats=stats))
    assert out == "" and stats.stop_reason == "cancelled"
