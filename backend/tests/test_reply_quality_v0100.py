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


def test_mixture_schedule_phases():
    from moth.training.trainer import TrainConfig, phase_weights

    cfg = TrainConfig(run_name="t", dataset="d", out_dir="o", max_steps=100,
                      mixture={"conversation": 0.5, "code": 0.5},
                      mixture_schedule=[{"until": 0.1, "weights": {"conversation": 1.0}},
                                        {"until": 0.8, "weights": {"conversation": 0.5, "code": 0.5}},
                                        {"until": 1.01, "weights": {"conversation": 0.7, "code": 0.3}}])
    assert phase_weights(cfg, 0) == {"conversation": 1.0}
    assert phase_weights(cfg, 50)["code"] == 0.5
    assert phase_weights(cfg, 99)["conversation"] == 0.7


def test_long_chats_are_compacted_not_cut():
    from moth.model.chat_format import Message, compact, encode_chat

    tok = Tokenizer([])
    msgs = [Message("system", "You are MOTH.")]
    for i in range(30):
        msgs += [Message("user", f"Question number {i}: what is {i} plus {i}? Please explain."),
                 Message("assistant", f"The answer is {2 * i}. Adding {i} twice gives {2 * i}.")]
    msgs.append(Message("user", "And what was my first question?"))
    out, did = compact(tok, msgs, 600)
    assert did and len(encode_chat(tok, out)[0]) <= 600
    assert out[0].content == "You are MOTH." and out[-1].content == "And what was my first question?"
    assert any("Earlier in this conversation" in m.content for m in out)
    short, did = compact(tok, msgs[:3], 600)
    assert not did and short == msgs[:3]


def test_remember_requests_are_recognised():
    from moth.server.routes_model import remember_request

    assert remember_request("Remember that I use TypeScript with React") == "I use TypeScript with React."
    assert remember_request("my name is Sam") == "my name is Sam."
    assert remember_request("I prefer short answers.") == "I prefer short answers."
    assert remember_request("never mind, how do loops work?") is None
    assert remember_request("Can you remember how loops work?") is None
