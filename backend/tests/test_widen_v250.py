"""2.5: a bigger MOTH starts exactly as good as the current one (function-preserving width and depth growth)."""
import pytest
import torch

from moth.model.config import MothConfig
from moth.model.growth import assert_function_preserved, can_widen, grow_into, preserving_shape, widen_state
from moth.model.transformer import MothModel

OLD = MothConfig(name="t", vocab_size=300, d_model=64, n_layers=2, n_heads=4, n_kv_heads=4, ffn_hidden=160, max_seq_len=128)


def _state(cfg, seed=0):
    torch.manual_seed(seed)
    m = MothModel(cfg)
    for p in m.parameters():  # trained-looking weights, not the tiny init
        p.data.normal_(0, 0.08)
    return m.state_dict()


@pytest.mark.parametrize("target", [
    dict(d_model=128, n_layers=2, ffn_hidden=160),          # wider only
    dict(d_model=96, n_layers=4, ffn_hidden=320),            # wider, deeper, bigger FFN
    dict(d_model=64, n_layers=3, ffn_hidden=200),            # same width (old growth path)
])
def test_grown_model_gives_the_same_answers(target):
    old_state = _state(OLD)
    new = preserving_shape(OLD, **target)
    assert can_widen(OLD, new) is None and new.head_dim == OLD.head_dim
    grown = widen_state(old_state, OLD, new, seed=1)
    tokens = torch.randint(0, 300, (2, 40))
    diff = assert_function_preserved(old_state, OLD, grown, new, tokens, atol=5e-3)
    assert diff < 5e-3
    assert MothModel(new).num_params() if hasattr(MothModel(new), "num_params") else True


def test_grouped_query_attention_is_preserved():
    old = MothConfig(name="g", vocab_size=300, d_model=64, n_layers=2, n_heads=4, n_kv_heads=2, ffn_hidden=128, max_seq_len=64)
    new = preserving_shape(old, d_model=128, n_layers=2, ffn_hidden=128)
    assert new.n_heads == 8 and new.n_kv_heads == 4
    s = _state(old)
    assert_function_preserved(s, old, widen_state(s, old, new), new, torch.randint(0, 300, (1, 30)), atol=5e-3)


def test_grown_model_still_learns_its_new_width():
    old_state = _state(OLD)
    new = preserving_shape(OLD, d_model=128, n_layers=2, ffn_hidden=160)
    m = MothModel(new)
    m.load_state_dict(widen_state(old_state, OLD, new))
    x = torch.randint(0, 300, (4, 32))
    _, loss = m(x, targets=x)
    loss.backward()
    assert float(m.embed.weight.grad[:, 64:].abs().sum()) > 0  # new dimensions get gradient (symmetry broken)
    assert float(m.layers[0].attn.wo.weight.grad[:, 64:].abs().sum()) > 0  # new heads learn


def test_shapes_that_cannot_be_preserved_fall_back_to_a_partial_copy():
    other = MothConfig(name="o", vocab_size=400, d_model=96, n_layers=2, n_heads=3, n_kv_heads=3, ffn_hidden=160, max_seq_len=128)
    assert can_widen(OLD, other)
    fresh = MothModel(other).state_dict()
    state, how = grow_into(_state(OLD), OLD, other, fresh)
    assert how == "partial" and state["embed.weight"].shape == (400, 96)
    new = preserving_shape(OLD, d_model=96, n_layers=3, ffn_hidden=200)
    _, how = grow_into(_state(OLD), OLD, new, MothModel(new).state_dict())
    assert how == "preserving"


def test_updates_to_zero_started_weights_are_accepted():
    """A grown model's new layers start some weights at zero; training them is a normal update, not an attack."""
    import torch

    from moth.community.validation import validate_delta

    base = {"new.wo": torch.zeros(64, 64), "old.w": torch.randn(64, 64) * 0.02}
    ok = validate_delta(base, {"new.wo": torch.randn(64, 64) * 0.01, "old.w": torch.randn(64, 64) * 0.001}, 1000.0)
    assert ok.ok, ok.reasons
    huge = validate_delta(base, {"new.wo": torch.full((64, 64), 1e6), "old.w": torch.zeros(64, 64)}, 1000.0)
    assert not huge.ok and "update too large" in huge.reasons[0]
