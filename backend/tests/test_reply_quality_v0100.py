"""0.10.0: chat replies stop looping, drop unlikely tokens and end cleanly."""
import torch

from moth.model.config import MothConfig
from moth.model.generation import GenerationParams, _banned, _looping, chat_quality, generate_stream
from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel


def test_chat_quality_keeps_what_the_request_set():
    p = chat_quality(GenerationParams(frequency_penalty=0.5))
    assert p.frequency_penalty == 0.5 and p.min_p == 0.05 and p.stop_loops and p.soft_end
    assert chat_quality(GenerationParams(), byte_level=True).no_repeat_ngram == 24
    tool = GenerationParams(include_special=True)
    assert chat_quality(tool) is tool  # tool calls are never altered


def test_loops_and_repeated_ngrams_are_detected():
    assert _looping("Hello there. I am. I am. I am.") and not _looping("I am here and I am fine.")
    tok = Tokenizer([])
    ids = tok.encode("abcab")
    assert _banned(ids, 3, tok) == {tok.encode("c")[0]}  # "ab" was followed by "c": no second "abc"
    assert _banned(tok.encode("    x    "), 3, tok) == set()  # indentation may repeat


def test_replies_never_repeat_an_ngram_and_end_by_the_limit():
    torch.manual_seed(0)
    tok = Tokenizer([])
    m = MothModel(MothConfig.from_dict({"vocab_size": 512, "d_model": 32, "n_layers": 1, "n_heads": 2,
                                        "n_kv_heads": 2, "ffn_hidden": 64, "max_seq_len": 256})).eval()
    params = chat_quality(GenerationParams(max_new_tokens=80, temperature=0.0, seed=1), byte_level=True)
    out = "".join(generate_stream(m, tok, tok.encode("hi"), params))
    b = out.encode()
    grams = [b[i:i + 24] for i in range(len(b) - 23) if b[i:i + 24].strip()]
    assert len(grams) == len(set(grams))
