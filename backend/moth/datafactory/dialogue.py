"""Multi-turn conversations that depend on earlier turns (0.8.0), generated and checked by MOTH.

Each conversation tests one conversational skill and its final answer is derived from the earlier
messages by code, then re-checked against the text of those messages before it is kept:

* ``remember`` — a fact the user stated earlier (name, favourite, home town), possibly with an unrelated
  turn in between, then asked for later;
* ``correction`` — the user corrects an earlier statement; the answer must use the corrected value;
* ``list_recall`` — an item of a list given earlier, by position;
* ``follow_up`` — "now do X with that": arithmetic on the previous answer;
* ``clarify`` — an ambiguous request without context gets a clarifying question, not a guess;
* ``unknown`` — a question the conversation cannot answer gets "I don't know", not an invention;
* ``greeting`` — natural greetings and small talk that end the turn properly;
* ``format`` — an instruction with a checkable format (a numbered list of exactly N items).

Training and evaluation use **disjoint value lists** (``TRAIN`` vs ``EVAL``), so a benchmark answer can
never be memorised from training data. The skill (``kind``) of every conversation is recorded so the
evaluation can report each one separately.
"""

from __future__ import annotations

import random
import re
from typing import Any, Iterator

TRAIN = {
    "names": ["Alex", "Maya", "Jonas", "Priya", "Leo", "Sara", "Tom", "Nina", "Omar", "Lucia", "Felix", "Zoe"],
    "colors": ["blue", "green", "red", "orange", "purple", "yellow"],
    "foods": ["pizza", "sushi", "pasta", "curry", "tacos", "soup"],
    "cities": ["Berlin", "Lisbon", "Toronto", "Osaka", "Dublin", "Nairobi", "Lima", "Oslo"],
    "items": ["milk", "bread", "eggs", "rice", "apples", "cheese", "tea", "butter", "onions", "beans"],
    "langs": ["Python", "Rust", "Go", "Java", "Ruby"],
}
EVAL = {
    "names": ["Hiroshi", "Amara", "Bjorn", "Ines", "Kwame", "Freya", "Tariq", "Elena"],
    "colors": ["teal", "violet", "silver", "maroon"],
    "foods": ["ramen", "falafel", "paella", "dumplings"],
    "cities": ["Quito", "Tallinn", "Hanoi", "Accra", "Porto"],
    "items": ["flour", "lemons", "yogurt", "spinach", "honey", "garlic", "oats", "salt"],
    "langs": ["Kotlin", "Haskell", "Elixir", "Swift"],
}
CATEGORIES = {"fruits": ["apple", "banana", "cherry", "grape", "mango", "pear", "plum"],
              "planets": ["Mercury", "Venus", "Earth", "Mars", "Jupiter", "Saturn"],
              "programming languages": ["Python", "JavaScript", "TypeScript", "C++", "C#", "Java"],
              "colors": ["red", "blue", "green", "yellow", "purple", "orange"]}
UNKNOWN = [("What did I have for breakfast today?", "what you had for breakfast"),
           ("What is my dog's name?", "your dog's name"),
           ("Which city was I born in?", "where you were born"),
           ("What time did I wake up this morning?", "when you woke up")]
AMBIGUOUS = [("Can you fix it?", "fix"), ("Make it better.", "improve"), ("Why doesn't it work?", "look at"),
             ("Change that to the other one.", "change")]
ORD = ["first", "second", "third", "fourth"]
KINDS = ("remember", "correction", "list_recall", "follow_up", "clarify", "unknown", "greeting", "format")


def _u(t: str) -> dict:
    return {"role": "user", "content": t}


def _a(t: str) -> dict:
    return {"role": "assistant", "content": t}


def _remember(rng, v):
    n, c, f, city = rng.choice(v["names"]), rng.choice(v["colors"]), rng.choice(v["foods"]), rng.choice(v["cities"])
    fact = rng.choice([("name", f"my name is {n}", f"Nice to meet you, {n}!", "What is my name?", f"Your name is {n}.", n),
                       ("color", f"my favourite colour is {c}", f"{c.capitalize()} is a great colour.",
                        "What is my favourite colour?", f"Your favourite colour is {c}.", c),
                       ("food", f"I love {f}", f"{f.capitalize()} sounds delicious.", "What food did I say I love?",
                        f"You said you love {f}.", f),
                       ("city", f"I live in {city}", f"{city} sounds like a nice place to live.", "Where do I live?",
                        f"You live in {city}.", city)])
    _, said, ack, q, ans, value = fact
    msgs = [_u(f"Hi, {said}."), _a(ack)]
    if rng.random() < 0.6:  # an unrelated turn in between: the fact must survive it
        a, b = rng.randint(2, 20), rng.randint(2, 20)
        msgs += [_u(f"Quick question: what is {a} + {b}?"), _a(f"{a} + {b} = {a + b}.")]
    msgs += [_u(q), _a(ans)]
    return msgs, [value]


def _correction(rng, v):
    a, b = rng.sample(v["cities"], 2)
    msgs = [_u(f"I live in {a}."), _a(f"Got it, you live in {a}."), _u(f"Sorry, I meant {b}, not {a}."),
            _a(f"No problem, you live in {b}."), _u("Where do I live?"), _a(f"You live in {b}.")]
    return msgs, [b]


def _list_recall(rng, v):
    items = rng.sample(v["items"], rng.randint(3, 4))
    i = rng.randrange(len(items))
    listed = ", ".join(items[:-1]) + f" and {items[-1]}"
    msgs = [_u(f"My shopping list is: {', '.join(items)}."), _a(f"Got it: {listed}."),
            _u(f"What was the {ORD[i]} item on my list?"), _a(f"The {ORD[i]} item was {items[i]}.")]
    return msgs, [items[i]]


def _follow_up(rng, v):
    a, b, m = rng.randint(2, 40), rng.randint(2, 40), rng.randint(2, 6)
    s = a + b
    msgs = [_u(f"What is {a} + {b}?"), _a(f"{a} + {b} = {s}."), _u(f"Now multiply that by {m}."),
            _a(f"{s} × {m} = {s * m}.")]
    return msgs, [str(s * m)]


def _clarify(rng, v):
    q, verb = rng.choice(AMBIGUOUS)
    return [_u(q), _a(f"I'm happy to help, but I'm not sure what you'd like me to {verb}. Could you share the "
                      "code or describe what you mean?")], ["?"]


def _unknown(rng, v):
    q, what = rng.choice(UNKNOWN)
    return [_u(q), _a(f"I don't know {what} — you haven't told me. If you tell me, I can remember it for this "
                      "conversation.")], ["don't know", "do not know", "not sure", "haven't told"]


def _greeting(rng, v):
    n = rng.choice(v["names"])
    turns = [[_u("Hello!"), _a("Hello! How can I help you today?")],
             [_u(f"Hi, I'm {n}."), _a(f"Hi {n}! What would you like to work on?")],
             [_u("How are you?"), _a("I'm doing well, thanks for asking. What can I help you with?")],
             [_u("Thanks for your help!"), _a("You're welcome! Let me know if you need anything else.")]]
    msgs = rng.choice(turns)
    return msgs, []


def _format(rng, v):
    cat = rng.choice(sorted(CATEGORIES))
    n = rng.randint(2, 4)
    picks = rng.sample(CATEGORIES[cat], n)
    return [_u(f"List {n} {cat} as a numbered list."), _a("\n".join(f"{i + 1}. {p}" for i, p in enumerate(picks)))], \
        [f"{n}."]


GEN = {"remember": _remember, "correction": _correction, "list_recall": _list_recall, "follow_up": _follow_up,
       "clarify": _clarify, "unknown": _unknown, "greeting": _greeting, "format": _format}


def check(kind: str, msgs: list[dict], expect: list[str]) -> bool:
    """Re-derive the final answer from the earlier messages; False if the conversation is wrong."""
    if len(msgs) < 2 or msgs[-1]["role"] != "assistant" or any(not m["content"].strip() for m in msgs):
        return False
    if any(msgs[i]["role"] == msgs[i + 1]["role"] for i in range(len(msgs) - 1)) or msgs[0]["role"] != "user":
        return False
    final = msgs[-1]["content"]
    history = " ".join(m["content"] for m in msgs[:-1] if m["role"] == "user")
    if kind in ("remember", "correction", "list_recall"):
        value = expect[0]
        if kind == "correction":
            m = re.search(r"I meant (\w+)", history)
            return bool(m and m.group(1) == value and value in final)
        if kind == "list_recall":
            items = re.search(r"list is: ([^.]+)\.", history).group(1).split(", ")
            pos = ORD.index(re.search(r"the (\w+) item", msgs[-2]["content"]).group(1))
            return items[pos] == value and value in final
        return value in history and value in final
    if kind == "follow_up":
        a, b = (int(x) for x in re.findall(r"\d+", msgs[0]["content"])[:2])
        m = int(re.search(r"by (\d+)", msgs[2]["content"]).group(1))
        return final.endswith(f"= {(a + b) * m}.")
    if kind == "clarify":
        return final.rstrip().endswith("?")
    if kind == "unknown":
        return "don't know" in final
    if kind == "format":
        lines = final.splitlines()
        n = int(re.search(r"List (\d+)", msgs[0]["content"]).group(1))
        return len(lines) == n and all(line.startswith(f"{i + 1}. ") for i, line in enumerate(lines))
    return True


def conversations(n: int, seed: int = 0, split: str = "train") -> Iterator[dict[str, Any]]:
    """``n`` checked conversations (``messages``, ``kind``, ``expect``) from the train or eval value lists."""
    values = TRAIN if split == "train" else EVAL
    rng = random.Random(f"dialogue:{split}:{seed}")
    made = tries = 0
    while made < n and tries < n * 5:
        tries += 1
        kind = KINDS[tries % len(KINDS)] if split == "eval" else rng.choice(KINDS)
        msgs, expect = GEN[kind](rng, values)
        if not check(kind, msgs, expect):
            continue
        yield {"messages": msgs, "kind": kind, "expect": expect}
        made += 1
