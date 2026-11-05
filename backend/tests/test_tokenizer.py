import random

from moth.model.tokenizer import SPECIAL_TOKENS, Tokenizer, train_bpe

TEXTS = ["def foo(bar):\n    return bar * 2\n", "Hello world! Hello MOTH.\n", "x = [1, 2, 3]\n"] * 30


def test_roundtrip_arbitrary_unicode():
    tok = train_bpe(TEXTS, vocab_size=400)
    rng = random.Random(0)
    for _ in range(50):
        s = "".join(chr(rng.choice([rng.randint(32, 126), rng.randint(0x80, 0x2FFF), 10, 9])) for _ in range(rng.randint(0, 80)))
        assert tok.decode(tok.encode(s)) == s


def test_merges_compress_and_vocab_size():
    tok = train_bpe(TEXTS, vocab_size=400)
    assert tok.vocab_size <= 400
    text = TEXTS[0]
    assert len(tok.encode(text)) < len(text.encode()) / 2


def test_special_tokens():
    tok = train_bpe(TEXTS, vocab_size=320)
    ids = tok.encode("<|user|>hi<|end|>", allow_special=True)
    assert ids[0] == tok.token_id("<|user|>") and ids[-1] == tok.end_id
    # Without allow_special the literal text is encoded as ordinary bytes (no injection).
    assert tok.token_id("<|user|>") not in tok.encode("<|user|>hi")
    assert tok.decode(ids) == "hi"
    assert tok.decode(ids, skip_special=False) == "<|user|>hi<|end|>"
    assert tok.n_special == len(SPECIAL_TOKENS)


def test_save_load_and_fingerprint(tmp_path):
    tok = train_bpe(TEXTS, vocab_size=350)
    tok.save(tmp_path / "t.json")
    tok2 = Tokenizer.load(tmp_path / "t.json")
    assert tok2.fingerprint() == tok.fingerprint()
    assert tok2.encode(TEXTS[1]) == tok.encode(TEXTS[1])


def test_training_is_deterministic():
    assert train_bpe(TEXTS, 380).merges == train_bpe(TEXTS, 380).merges
