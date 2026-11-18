"""1.1: JavaScript tasks run under Node.js; the security exam scores any model between 0 and 1."""
import shutil

import pytest

from moth.model import exams


@pytest.mark.skipif(not shutil.which("node"), reason="Node.js is not installed here")
def test_js_tasks_run_and_only_correct_code_passes():
    tests = dict((n, t) for _, n, t in exams.JS_TASKS)
    assert exams.run_js("function sumAll(a){return a.reduce((x,y)=>x+y,0)}", "sumAll", tests["sumAll"])
    assert not exams.run_js("function sumAll(a){return 0}", "sumAll", tests["sumAll"])
    assert exams.run_js("const unique = a => [...new Set(a)];", "unique", tests["unique"])
    assert not exams.run_js("while(true){}", "sumAll", tests["sumAll"], timeout=1)


def test_security_exam_scores_a_model():
    from moth.model.config import MothConfig
    from moth.model.tokenizer import Tokenizer
    from moth.model.transformer import MothModel

    tok = Tokenizer([])
    model = MothModel(MothConfig.from_dict({"vocab_size": 512, "d_model": 32, "n_layers": 1, "n_heads": 2,
                                            "n_kv_heads": 2, "ffn_hidden": 64, "max_seq_len": 256})).eval()
    r = exams.security_suite(model, tok)
    assert 0 <= r["value"] <= 1 and r["n"] == len(exams.SECURITY_EXAM) == 30 and r["higher_is_better"]
    assert all(0 <= ans < len(c) for _, c, ans in exams.SECURITY_EXAM)
