"""Instruction following reports why replies fail, so a format problem is not mistaken for a size limit."""
import json

import torch

from moth.model.capabilities import instruction_suite
from moth.model.config import preset
from moth.model.tokenizer import Tokenizer
from moth.model.transformer import MothModel


def test_instruction_suite_counts_every_reply_once(tmp_path):
    torch.manual_seed(0)
    tok = Tokenizer([])
    model = MothModel(preset("moth-tiny", vocab_size=tok.vocab_size)).eval()
    path = tmp_path / "conv.jsonl"
    path.write_text("\n".join(json.dumps({"messages": [{"role": "user", "content": f"Say hello {i}"},
                                                       {"role": "assistant", "content": "Hello!"}]}) for i in range(6)))
    r = instruction_suite(model, tok, str(path), limit=6, max_new=12)
    assert r["n"] == 6 and set(r["failures"]) == {"empty", "no_end", "repetitive"}
    assert round(r["value"] * 6) + sum(r["failures"].values()) == 6
