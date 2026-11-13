"""Self-training (0.9.0): MOTH quizzes itself, finds its own weaknesses and learns from the results.

Every ``INTERVAL`` the deployed model answers fresh problems from MOTH's verified generators
(arithmetic, instructions, reasoning, language). The generators know the correct answer, so every
answer is checked automatically. Nothing is taken on trust:

* a **correct** answer (its key — the number, name, ordering or text the problem asks for — matches
  the generator's) is kept as a *self-verified* training example in MOTH's own words;
* a **wrong** answer is replaced by the generator's checked answer and kept as a *correction*: MOTH
  trains on exactly what it got wrong.

The per-kind pass rates are MOTH's measured weaknesses on new problems, and they steer the curriculum
(weak kinds get more data). The examples are written to ``self_training/records.jsonl`` (capped) and
included in the next data preparation as a CC0 source, like the other generated data. The held-out
benchmarks never use these problems, so promotion still measures real progress.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

from moth_server.context import Ctx

INTERVAL = 3600.0
PER_KIND = 40
SAMPLES = 2                       # attempts per problem (sampled): any verified one is kept
MAX_RECORDS = 200_000
KINDS = {"arithmetic": "math", "instructions": "conversation", "reasoning": "reasoning", "language": "language"}
CAPABILITY = {"arithmetic": "math", "instructions": "instruction", "reasoning": "reasoning", "language": "language"}
KEY = "self_training"
NUM = re.compile(r"-?\d+(?:\.\d+)?")


def path(ctx: Ctx) -> Path:
    return Path(ctx.settings.data_dir) / "self_training" / "records.jsonl"


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", s.lower()).split())


def key_of(reference: str) -> tuple[str, str]:
    """What a correct answer must contain: ("number", "4230") or ("text", "the youngest is ben")."""
    m = re.search(r"[Tt]he answer is\s+(-?\d+(?:\.\d+)?)", reference)
    if m:
        return "number", m.group(1)
    last = [p for p in re.split(r"(?<=[.!?])\s+", reference.strip()) if p.strip()][-1]
    nums = NUM.findall(last)
    if nums:
        return "number", nums[-1]
    return "text", _norm(last.split(":")[-1])


def correct(answer: str, reference: str) -> bool:
    kind, want = key_of(reference)
    if kind == "number":
        got = NUM.findall(answer)
        return bool(got) and got[-1] == want
    return bool(want) and want in _norm(answer)


def _ask(engine, question: str, temperature: float) -> str:
    from moth.model.chat_format import Message
    from moth.model.generation import GenerationParams

    params = GenerationParams.from_dict({"max_new_tokens": 96, "temperature": temperature, "top_p": 0.95})
    parts: list[str] = []
    engine.chat([Message("user", question)], params, parts.append, threading.Event())
    return "".join(parts).strip()


def run_round(ctx: Ctx, per_kind: int = PER_KIND, samples: int = SAMPLES, seed: int | None = None) -> dict[str, Any] | None:
    """One self-quiz. None when no model is serving."""
    from moth.datafactory import synthetic

    from moth_server.evolution import memory as MEM

    engine = ctx.extras.get("inference_engine")
    if engine is None or not getattr(engine, "manifest", None):
        return None
    seed = int(time.time()) if seed is None else seed
    version = ctx.extras.get("deployed_version")
    stats: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for kind, domain in KINDS.items():
        rng = random.Random(f"self:{kind}:{seed}")
        tried = right = 0
        while tried < per_kind:
            ex = synthetic.GENERATORS[kind](rng)
            if ex is None:
                continue
            q, ref = ex
            tried += 1
            good = None
            for i in range(samples):
                try:
                    ans = _ask(engine, q, 0.0 if i == 0 else 0.8)
                except Exception:  # noqa: BLE001 — a failed generation counts as a wrong answer
                    ans = ""
                if ans and correct(ans, ref):
                    good = ans
                    break
            uid = f"self:{seed}:{kind}:{tried}"
            if good:
                right += 1
                records.append({"uid": uid, "source": "self-verified", "domain": domain, "kind": kind,
                                "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": good}]})
            else:  # learn exactly what was missed, from the generator's checked answer
                records.append({"uid": uid, "source": "self-corrections", "domain": domain, "kind": kind,
                                "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": ref}]})
        stats[kind] = {"tried": tried, "correct": right, "rate": round(right / max(1, tried), 3)}
    p = path(ctx)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = (p.read_text(encoding="utf-8").splitlines() if p.exists() else []) + [json.dumps(r) for r in records]
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(lines[-MAX_RECORDS:]) + "\n", encoding="utf-8")
    tmp.replace(p)
    st = state(ctx)
    entry = {"at": time.time(), "version": version, "kinds": stats,
             "verified": sum(1 for r in records if r["source"] == "self-verified"),
             "corrections": sum(1 for r in records if r["source"] == "self-corrections")}
    st = {"rounds": int(st.get("rounds", 0)) + 1, "last": entry, "history": (st.get("history") or [])[-19:] + [entry],
          "records": min(MAX_RECORDS, len(lines))}
    ctx.db.set_config(KEY, st)
    rates = ", ".join(f"{k} {v['correct']}/{v['tried']}" for k, v in stats.items())
    MEM.event(ctx, "self.quiz", f"MOTH{f' v{version}' if version else ''} quizzed itself on "
              f"{sum(v['tried'] for v in stats.values())} new, automatically checked problems ({rates}). "
              f"{entry['verified']} correct answers were kept as self-verified examples and {entry['corrections']} "
              "mistakes as corrections with the checked answer; both join the next data preparation.",
              kinds=stats, version=version)
    return entry


def state(ctx: Ctx) -> dict[str, Any]:
    return ctx.db.get_config(KEY, {}) or {}


def weakness_scores(ctx: Ctx) -> dict[str, float]:
    """Capability → weakness (1 − pass rate) from the latest self-quiz."""
    last = (state(ctx).get("last") or {}).get("kinds") or {}
    return {CAPABILITY[k]: round(1 - float(v["rate"]), 3) for k, v in last.items() if k in CAPABILITY and v.get("tried")}


def records(ctx: Ctx) -> list[dict[str, Any]]:
    p = path(ctx)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def generation(ctx: Ctx) -> int:
    """Changes when the self-training data has doubled: the next automatic preparation includes it."""
    n = int(state(ctx).get("records") or 0)
    return n.bit_length()


def maybe_run(ctx: Ctx) -> bool:
    """Start a self-quiz in the background when one is due (called by the supervisor every minute)."""
    from moth_server.evolution import settings as S
    from moth_server.evolution.native_reset import fenced

    s = S.get(ctx)
    if not s.get("enabled") or s.get("paused") or fenced(ctx) or not (s.get("self_training") or {}).get("enabled", True):
        return False
    if ctx.extras.get("inference_engine") is None or ctx.extras.get("self_quiz_running"):
        return False
    last = float((state(ctx).get("last") or {}).get("at") or 0)
    if time.time() - last < INTERVAL:
        return False
    ctx.extras["self_quiz_running"] = True

    def work():
        try:
            run_round(ctx)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger("moth_server.self_training").exception("self-quiz failed")
        finally:
            ctx.extras["self_quiz_running"] = False

    threading.Thread(target=work, daemon=True, name="moth-self-quiz").start()
    return True
