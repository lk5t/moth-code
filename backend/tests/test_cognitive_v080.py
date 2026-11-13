"""0.8.0: conversation and coding curricula are checked; benchmarks score real behaviour."""
import re

from moth.datafactory import clean, coding, dialogue, synthetic
from moth.model import capabilities as C
from moth.model.generation import GenerationStats


class _Stats(GenerationStats):
    def __init__(self, reason="eos"):
        super().__init__()
        self.stop_reason = reason


def test_dialogues_are_checked_and_eval_values_never_appear_in_training():
    train = list(dialogue.conversations(3000, 1))
    assert {c["kind"] for c in train} == set(dialogue.KINDS)
    assert all(dialogue.check(c["kind"], c["messages"], c["expect"]) for c in train)
    assert all(clean.conversation_issue(c["messages"]) is None for c in train)
    train_text = " ".join(m["content"] for c in train for m in c["messages"])
    for key in ("names", "cities", "items", "colors", "foods"):
        assert not set(dialogue.EVAL[key]) & set(dialogue.TRAIN[key])
        assert not any(re.search(rf"\b{v}\b", train_text) for v in dialogue.EVAL[key])
    # a wrong final answer is caught by the check
    c = next(x for x in train if x["kind"] == "follow_up")
    bad = [*c["messages"][:-1], {"role": "assistant", "content": "17 × 2 = 999."}]
    assert not dialogue.check("follow_up", bad, c["expect"])


def test_conversation_filters():
    u, a = (lambda t: {"role": "user", "content": t}), (lambda t: {"role": "assistant", "content": t})
    assert clean.conversation_issue([u("hi"), a("hello")]) is None
    assert clean.conversation_issue([u("hi"), u("again"), a("x")]) == "roles_not_alternating"
    assert clean.conversation_issue([u("a"), a("same"), u("b"), a("same")]) == "repeated_reply"
    assert clean.conversation_issue([u("a"), a("the cat " * 30)]) == "repetitive_reply"
    assert clean.conversation_issue([a("starts with the assistant"), u("x")]) == "bad_roles"


def test_coding_examples_are_executed_and_eval_tasks_are_held_out():
    assert not {t[1] for t in coding.EVAL_TASKS} & {t[1] for t in synthetic.PY_TASKS}
    for kind in coding.GENERATORS:
        assert sum(1 for _ in coding.generate(kind, 100, 3)) == 100
    for task, name, code, tests in synthetic.PY_TASKS:
        buggy = coding.inject_bug(code, name, tests, __import__("random").Random(1))
        if buggy:
            assert synthetic.passes(code, name, tests) and not synthetic.passes(buggy, name, tests)
    assert len(coding.eval_items("codegen")) == len(coding.EVAL_TASKS) == len(coding.eval_items("debugging"))


def test_dialogue_suite_rewards_right_answers_only(monkeypatch):
    items = {tuple(m["content"] for m in c["messages"][:-1]): c for c in dialogue.conversations(48, 0, "eval")}
    gold = lambda model, tok, msgs, max_new: (items[tuple(m["content"] for m in msgs)]["messages"][-1]["content"], _Stats())
    monkeypatch.setattr(C, "_chat_history", gold)
    r = C.dialogue_suite(None, None)
    assert r["value"] == 1.0 and r["context_retention"] == 1.0 and r["ended_turn"] == 1.0
    monkeypatch.setattr(C, "_chat_history", lambda *a: ("I like turtles.", _Stats()))
    r = C.dialogue_suite(None, None)
    assert r["value"] < 0.2 and r["skills"]["remember"] == 0 and r["skills"]["unknown"] == 0
    monkeypatch.setattr(C, "_chat_history", lambda *a: ("blah blah " * 20, _Stats("max_tokens")))
    r = C.dialogue_suite(None, None)
    assert r["repetitive"] == 1.0 and r["value"] == 0.0


def test_coding_suite_executes_tests(monkeypatch):
    sols = {t[1]: t[2] for t in coding.EVAL_TASKS}
    gold = lambda model, tok, prompt, max_new: ("```python\n" + sols[re.search(r"`(\w+)`|def (\w+)", prompt).group(1)
                                                or re.search(r"def (\w+)", prompt).group(1)] + "\n```", _Stats())
    monkeypatch.setattr(C, "_chat", gold)
    assert C.coding_suite(None, None, "codegen")["value"] == 1.0
    assert C.coding_suite(None, None, "debugging")["value"] == 1.0
    # returning the buggy code unchanged must fail the debugging benchmark
    monkeypatch.setattr(C, "_chat", lambda m, t, prompt, mx: (prompt.split("```python\n")[1].split("```")[0], _Stats()))
    r = C.coding_suite(None, None, "debugging")
    assert r["value"] == 0.0 and r["valid_python"] == 1.0
