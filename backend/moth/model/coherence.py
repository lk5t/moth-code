"""Why does MOTH produce incoherent text? Measured checks of the tokenizer, decoding and the replies.

Run against a real model package (deterministic seeds), it reports:

* **tokenizer** — does ``decode(encode(text))`` give back plain text, code and accented text exactly,
  and how many tokens per character it needs (byte-level tokenizers need far more, which shortens
  the usable context);
* **replies** — a fixed set of simple prompts answered with greedy decoding and with the sampling
  settings MOTH serves with: the share of empty replies, replies that never end, the repetition of
  word pairs, and characters that are not printable text;
* **decoding** — whether the serving settings produce clearly less repetitive replies than greedy
  decoding (a decoding problem has a decoding fix; it is not a reason to grow the model).

The verdict names the most likely cause in plain words. Nothing here is estimated: every number is
counted from the model's own output.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from moth.model.chat_format import Message, encode_chat
from moth.model.generation import GenerationParams, GenerationStats, generate_stream

ROUND_TRIP = ["The quick brown fox jumps over the lazy dog.",
              "def add(a, b):\n    return a + b\n",
              "Café, naïve, 東京 — ünïcode ✓"]
PROMPTS = ["Hello! How are you?", "What is 2 + 3?", "Write a Python function that adds two numbers.",
           "Explain what a variable is in one sentence."]


def _pairs_distinct(text: str) -> float:
    w = text.split()
    return len(set(zip(w, w[1:]))) / max(1, len(w) - 1) if len(w) > 2 else 1.0


def _garbage(text: str) -> float:
    if not text:
        return 0.0
    bad = sum(1 for ch in text if ch not in "\n\t" and (unicodedata.category(ch)[0] == "C" or ch == "�"))
    return bad / len(text)


def _replies(model, tok, params: GenerationParams, max_new: int) -> dict[str, Any]:
    out = []
    for i, p in enumerate(PROMPTS):
        ids, _ = encode_chat(tok, [Message("user", p)], add_generation_prompt=True)
        ids = ids[-(model.cfg.max_seq_len - max_new):]
        stats = GenerationStats()
        text = "".join(generate_stream(model, tok, ids, GenerationParams(**{**params.__dict__, "seed": 1234 + i,
                                                                            "max_new_tokens": max_new}), stats=stats))
        out.append({"prompt": p, "reply": text[:240], "ended": stats.stop_reason in ("eos", "stop_string"),
                    "distinct_pairs": round(_pairs_distinct(text), 3), "garbage": round(_garbage(text), 3)})
    n = len(out)
    return {"empty": sum(1 for r in out if not r["reply"].strip()) / n,
            "unended": sum(1 for r in out if not r["ended"]) / n,
            "repetition": round(1 - sum(r["distinct_pairs"] for r in out) / n, 3),
            "garbage": round(sum(r["garbage"] for r in out) / n, 3), "samples": out}


def diagnose(model, tok, serving: GenerationParams | None = None, max_new: int = 48) -> dict[str, Any]:
    model.eval()
    trips = [{"text": t, "ok": tok.decode(tok.encode(t)) == t} for t in ROUND_TRIP]
    chars = sum(len(t) for t in ROUND_TRIP)
    tokens_per_char = round(sum(len(tok.encode(t)) for t in ROUND_TRIP) / chars, 3)
    greedy = _replies(model, tok, GenerationParams(temperature=0.0, top_k=0, top_p=1.0, repetition_penalty=1.0), max_new)
    served = _replies(model, tok, serving or GenerationParams(), max_new)
    tokenizer_broken = not all(t["ok"] for t in trips)
    decoding_helps = greedy["repetition"] - served["repetition"] >= 0.2
    incoherent = served["garbage"] > 0.05 or served["repetition"] > 0.5 or served["empty"] > 0.5
    if tokenizer_broken:
        cause = "tokenizer", "The tokenizer does not turn text back into the same text, so replies are garbled."
    elif served["garbage"] > 0.05:  # the tokenizer itself round-trips: the model emits invalid byte sequences
        cause = "training", ("Replies contain broken characters although the tokenizer works: the model still produces "
                             "invalid byte sequences and needs more training.")
    elif decoding_helps and served["repetition"] <= 0.5:
        cause = "decoding", "Greedy decoding repeats itself; the serving sampling settings already avoid most of it."
    elif incoherent and served["unended"] > 0.5:
        cause = "training", "Replies run on without ending: MOTH needs more training on complete conversations."
    elif incoherent:
        cause = "training", "Replies are still repetitive or empty: MOTH needs more training before it can be coherent."
    else:
        cause = None, "Replies are readable text that ends on its own."
    return {"tokenizer": {"round_trip": trips, "ok": not tokenizer_broken, "tokens_per_char": tokens_per_char,
                          "vocab_size": getattr(tok, "vocab_size", None)},
            "greedy": greedy, "served": served, "decoding_helps": decoding_helps, "incoherent": incoherent,
            "cause": cause[0], "explanation": cause[1]}
