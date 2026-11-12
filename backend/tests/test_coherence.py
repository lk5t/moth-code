"""Incoherent output is diagnosed from the model's own replies, the tokenizer and the decoding settings."""
import torch

from moth.model import coherence
from moth.model.config import preset
from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel


def _model():
    torch.manual_seed(0)
    tok = Tokenizer([])
    return MothModel(preset("moth-tiny", vocab_size=tok.vocab_size)), tok


def test_an_untrained_model_needs_training_not_a_new_tokenizer():
    model, tok = _model()
    d = coherence.diagnose(model, tok, max_new=24)
    assert d["tokenizer"]["ok"] and all(t["ok"] for t in d["tokenizer"]["round_trip"])
    assert d["incoherent"] and d["cause"] == "training"
    assert len(d["served"]["samples"]) == len(coherence.PROMPTS)
    assert 0 <= d["served"]["repetition"] <= 1 and 0 <= d["served"]["garbage"] <= 1


def test_a_tokenizer_that_does_not_round_trip_is_named(monkeypatch):
    model, tok = _model()
    real = tok.decode
    monkeypatch.setattr(tok, "decode", lambda ids, skip_special=True: real(ids, skip_special).replace("e", "?"))
    d = coherence.diagnose(model, tok, max_new=8)
    assert not d["tokenizer"]["ok"] and d["cause"] == "tokenizer"


def test_measures():
    assert coherence._pairs_distinct("a b a b a b a b") < 0.5
    assert coherence._pairs_distinct("the cat sat on the mat today") == 1.0
    assert coherence._garbage("ok�\x07") == 0.5
