import pytest

from moth.policy.engine import DEFAULT_POLICY, PolicyEngine, PolicyError
from moth.security.redaction import redact


def test_default_policy_has_no_topic_restrictions():
    eng = PolicyEngine()
    assert DEFAULT_POLICY["content_rules"] == []
    for text in ["How do lock picks work?", "Write a villain's monologue", "explain malware analysis"]:
        assert eng.check_input(text).allowed and eng.filter_output(text).text == text


def test_owner_rules_block_redact_warn():
    eng = PolicyEngine({"content_rules": [
        {"id": "b", "action": "block", "applies_to": "input", "match": {"type": "keywords", "patterns": ["forbidden"]},
         "message": "Not here."},
        {"id": "r", "action": "redact", "applies_to": "output", "match": {"type": "regex", "patterns": [r"\bfoo\d+"]}},
        {"id": "w", "action": "warn", "applies_to": "both", "match": {"type": "keywords", "patterns": ["beta"]}},
    ]})
    d = eng.check_input("this is FORBIDDEN text")
    assert not d.allowed and d.message == "Not here."
    assert eng.check_input("forbiddenness is a different word").allowed  # whole-word match
    out = eng.filter_output("value foo123 and beta")
    assert out.allowed and "foo123" not in out.text and {t["id"] for t in out.triggered} == {"r", "w"}


@pytest.mark.parametrize("bad", [
    {"content_rules": [{"id": "x", "action": "explode", "match": {"type": "keywords", "patterns": []}}]},
    {"content_rules": [{"id": "x", "action": "block", "match": {"type": "regex", "patterns": ["("]}}]},
    {"content_rules": [{"action": "block", "match": {"type": "keywords", "patterns": []}}]},
    {"system_prompt": 5},
])
def test_invalid_policy_rejected(bad):
    with pytest.raises(PolicyError):
        PolicyEngine(bad)


def test_policy_persistence(tmp_path):
    eng = PolicyEngine({"system_prompt": "Be terse."})
    eng.save(tmp_path / "p.json")
    assert PolicyEngine.load(tmp_path / "p.json").system_prompt == "Be terse."


def test_secret_redaction_is_independent_of_policy():
    text = ("key=AKIAABCDEFGHIJKLMNOP\nGITHUB_TOKEN=ghp_" + "a" * 36 +
            "\n-----BEGIN RSA PRIVATE KEY-----\nabc\n-----END RSA PRIVATE KEY-----\nAPI_KEY='supersecretvalue'")
    out, found = redact(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in out and "ghp_" not in out and "abc" not in out
    assert "supersecretvalue" not in out
    assert {"aws_access_key", "private_key"} <= set(found)
    assert redact("def add(a, b): return a + b")[1] == []
