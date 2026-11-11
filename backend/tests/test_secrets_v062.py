"""0.6.2: credentials never become training data; quality inspection reports them."""
import json

from moth.datafactory import clean
from moth.training.sources import SourceSpec


def test_scrub_removes_credentials_with_the_shared_patterns():
    text = ("key = AKIAABCDEFGHIJKLMNOP\nPASSWORD='hunter2hunter2'\n"
            "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAKj34GkxFhD90vcNLYLInFEX6Ppy1tPf9Cnzj4p4WGeKLs1Pt8Qu\n-----END RSA PRIVATE KEY-----\n"
            "tok github_pat_" + "A" * 50 + " mail me@example.com")
    out, n = clean.scrub(text)
    for leaked in ("AKIAABCDEFGHIJKLMNOP", "hunter2hunter2", "MIIBOgIB", "github_pat_", "me@example.com"):
        assert leaked not in out
    assert n >= 5 and "PASSWORD=" in out  # the variable name stays, the value does not


def test_quality_report_flags_secrets(tmp_path, tiny_pipeline):
    from moth.training.quality import inspect

    tok = tiny_pipeline["tokenizer"]
    assert tiny_pipeline["meta"]["secrets_removed"] == 0
    f = tmp_path / "d.jsonl"
    f.write_text(json.dumps({"prompt": "configure", "answer": "export API_KEY=sk_live_" + "x" * 24}) + "\n"
                 + json.dumps({"prompt": "hi", "answer": "hello there friend"}) + "\n")
    r = inspect([SourceSpec(f"jsonl:{f}", license="MIT")], tok)
    assert r["secrets"] == 1 and r["status"] == "needs_review"
    assert any(i["kind"] == "secret" for i in r["issues"])
