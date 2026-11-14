"""1.0.3: training conversations start with MOTH's system prompt as often as real chats need them to."""
from moth.datafactory.build import with_system
from moth.policy.engine import DEFAULT_POLICY


def _rec(i):
    return {"uid": f"oasst1:{i}", "domain": "conversation",
            "messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]}


def test_about_half_of_conversations_get_the_system_prompt_deterministically():
    out = [with_system(_rec(i)) for i in range(2000)]
    withsys = [r for r in out if r["messages"][0]["role"] == "system"]
    assert 0.4 < len(withsys) / len(out) < 0.6
    assert all(r["messages"][0]["content"] == DEFAULT_POLICY["system_prompt"] for r in withsys)
    assert [with_system(_rec(i)) for i in range(50)] == out[:50]  # same on every build and machine


def test_plain_text_and_existing_system_messages_are_left_alone():
    assert with_system({"uid": "x", "text": "a story"}) == {"uid": "x", "text": "a story"}
    r = {"uid": "y", "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "q"}]}
    assert with_system(r) == r
