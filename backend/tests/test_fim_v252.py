"""2.5.2: about half of the code documents are trained as fill-in-the-middle, deterministically."""
from moth.datafactory.build import _encode, fim_encode
from moth.model.tokenizer import Tokenizer


def test_fim_rewrites_about_half_of_code_and_is_deterministic():
    tok = Tokenizer([])
    docs = [f"def f{i}(x):\n    y = x * {i}\n    return y + {i}  # helper number {i}\n" for i in range(200)]
    fim = [fim_encode(tok, d) for d in docs]
    share = sum(f is not None for f in fim) / len(docs)
    assert 0.35 < share < 0.65
    sp = tok.special_ids
    for d, f in zip(docs, fim):
        if f is None:
            continue
        assert f[0] == sp["<|fim_prefix|>"] and sp["<|fim_suffix|>"] in f and sp["<|fim_middle|>"] in f
        p, s_, m = f.index(sp["<|fim_prefix|>"]), f.index(sp["<|fim_suffix|>"]), f.index(sp["<|fim_middle|>"])
        before, after, middle = tok.decode(f[p + 1:s_]), tok.decode(f[s_ + 1:m]), tok.decode(f[m + 1:])
        assert before + middle + after == d          # nothing lost: the three parts are the document
        assert fim_encode(tok, d) == f               # same record, same encoding (workers are re-checked)


def test_only_code_is_rewritten_and_short_text_is_left_alone():
    tok = Tokenizer([])
    text = "x = 1\n" * 40
    plain, _ = _encode(tok, {"text": text, "domain": "conversation"})
    assert plain[:-1] == tok.encode(text)
    assert fim_encode(tok, "x = 1") is None
