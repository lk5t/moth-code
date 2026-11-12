"""Turn verified dataset files into records.

A record is ``{"uid", "source", "domain", "text"}`` for plain text, or ``{..., "messages": [...]}`` for
conversations (roles ``user`` / ``assistant``). Eval files produce structured benchmark items instead
(``{"uid", "source", "suite", "prompt", "answer", ...}``) that are never written to training data.
"""

from __future__ import annotations

import gzip
import json
import re
from pathlib import Path
from typing import Any, Iterator

from moth.datafactory.catalog import DOLLY_DOMAINS

CALC = re.compile(r"<<[^<>]*>>")


def _parquet_rows(path: Path, columns: list[str] | None = None) -> Iterator[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise RuntimeError("Parquet datasets need the 'pyarrow' package") from e
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=2048, columns=columns):
        yield from batch.to_pylist()


def _json_array_items(path: Path) -> Iterator[dict[str, Any]]:
    """Objects of a top-level JSON array, decoded one at a time (constant memory)."""
    dec = json.JSONDecoder()
    buf, pos = "", 0
    with open(path, encoding="utf-8") as fh:
        while True:
            chunk = fh.read(1 << 20)
            buf = buf[pos:] + chunk
            pos = 0
            while True:
                while pos < len(buf) and buf[pos] in " \t\r\n,[":
                    pos += 1
                if pos >= len(buf) or buf[pos] == "]":
                    break
                try:
                    obj, end = dec.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    break  # incomplete object: read more
                yield obj
                pos = end
            if not chunk:
                return


def _msgs(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"role": r, "content": c} for r, c in pairs]


def gsm8k_solution(answer: str) -> tuple[str, str]:
    """GSM8K answers end with ``#### <number>``; calculator annotations ``<<…>>`` are removed."""
    body, _, final = answer.rpartition("####")
    final = final.strip().replace(",", "")
    steps = CALC.sub("", body).strip()
    return f"{steps}\nThe answer is {final}.", final


def arc_prompt(row: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    labels, texts = row["choices"]["label"], row["choices"]["text"]
    lines = [row["question"].strip(), ""] + [f"{l}. {t}" for l, t in zip(labels, texts)]
    return "\n".join(lines), list(labels), list(texts)


def _oasst_paths(node: dict[str, Any], prefix: list[tuple[str, str]], out: list, branch_budget: list[int]) -> None:
    role = "user" if node.get("role") == "prompter" else "assistant"
    turn = prefix + [(role, node.get("text", ""))]
    replies = [r for r in node.get("replies") or [] if not r.get("deleted") and r.get("lang", "en") == "en"]
    replies.sort(key=lambda r: (r.get("rank") is None, r.get("rank") if r.get("rank") is not None else 0))
    if not replies:
        if role == "assistant":
            out.append(turn)
        return
    # follow the best reply; at the first assistant level also keep the second-best answer
    take = replies[:2] if (role == "user" and len(prefix) == 0 and branch_budget[0] > 0) else replies[:1]
    for i, r in enumerate(take):
        if i:
            branch_budget[0] -= 1
        _oasst_paths(r, turn, out, branch_budget)


def train_records(src: dict[str, Any], f: dict[str, Any], path: Path) -> Iterator[dict[str, Any]]:
    fmt, sid = src["format"], src["id"]
    base = f"{sid}:{f['path']}"
    if fmt == "stories":
        buf: list[str] = []
        n = 0
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.strip() == "<|endoftext|>":
                    text = "".join(buf).strip()
                    buf = []
                    if text:
                        yield {"uid": f"{base}:{n}", "source": sid, "domain": "language", "text": text}
                        n += 1
                else:
                    buf.append(line)
        if "".join(buf).strip():
            yield {"uid": f"{base}:{n}", "source": sid, "domain": "language", "text": "".join(buf).strip()}
    elif fmt == "dolly":
        with open(path, encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                row = json.loads(line)
                q = row["instruction"].strip()
                if row.get("context", "").strip():
                    q = f"{q}\n\n{row['context'].strip()}"
                yield {"uid": f"{base}:{i}", "source": sid, "domain": DOLLY_DOMAINS.get(row.get("category"), "conversation"),
                       "category": row.get("category"), "messages": _msgs(("user", q), ("assistant", row["response"].strip()))}
    elif fmt == "oasst_trees":
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                tree = json.loads(line)
                prompt = tree.get("prompt") or {}
                if prompt.get("lang") != "en":
                    continue
                paths: list = []
                _oasst_paths(prompt, [], paths, [1])
                for j, p in enumerate(paths):
                    yield {"uid": f"{base}:{tree.get('message_tree_id', i)}:{j}", "source": sid, "domain": "conversation",
                           "messages": _msgs(*p)}
    elif fmt == "wikipedia":
        for i, row in enumerate(_parquet_rows(path, ["id", "title", "text"])):
            text = (row.get("text") or "").strip()
            if text:
                yield {"uid": f"{sid}:{row.get('id', i)}", "source": sid, "domain": "knowledge",
                       "text": f"{row.get('title', '').strip()}\n\n{text}"[:24_000]}
    elif fmt == "gsm8k":
        for i, row in enumerate(_parquet_rows(path)):
            sol, _ = gsm8k_solution(row["answer"])
            yield {"uid": f"{base}:{i}", "source": sid, "domain": "math",
                   "messages": _msgs(("user", row["question"].strip()), ("assistant", sol))}
    elif fmt == "arc":
        for i, row in enumerate(_parquet_rows(path)):
            prompt, labels, texts = arc_prompt(row)
            key = row["answerKey"]
            if key not in labels:
                continue
            ans = texts[labels.index(key)]
            yield {"uid": f"{base}:{row.get('id', i)}", "source": sid, "domain": "reasoning",
                   "messages": _msgs(("user", prompt), ("assistant", f"The answer is {key}. {ans}"))}
    elif fmt == "mbpp":
        for i, row in enumerate(_parquet_rows(path)):
            q = f"{row['text'].strip()}\nYour code should pass this test:\n{row['test_list'][0]}"
            code = row["code"].replace("\r\n", "\n").strip()
            yield {"uid": f"{base}:{row.get('task_id', i)}", "source": sid, "domain": "code",
                   "messages": _msgs(("user", q), ("assistant", f"```python\n{code}\n```"))}
    elif fmt in ("qa_jsonl", "qa_json"):
        # Instruction/answer pairs. Fields come from the catalog entry (e.g. query/answer, problem/solution).
        q_key, a_key = src.get("fields", ("question", "answer"))
        def rows():
            if fmt == "qa_json":  # one JSON array; streamed so very large files never load at once
                yield from _json_array_items(path)
            else:
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            yield json.loads(line)
        for i, row in enumerate(rows()):
            q, a = (row.get(q_key) or "").strip(), (row.get(a_key) or "").strip()
            if q and a:
                yield {"uid": f"{base}:{row.get('index', i)}", "source": sid, "domain": src.get("domain", "code"),
                       "messages": _msgs(("user", q[:12_000]), ("assistant", a[:16_000]))}
    elif fmt == "stdlib":
        from moth.training.sources import _iter_stdlib, find_stdlib

        root = find_stdlib()
        if root is None:
            return
        for d in _iter_stdlib(root):
            yield {"uid": f"{sid}:{d.id}", "source": sid, "domain": "code", "text": d.text[:60_000]}
    else:
        raise ValueError(f"unknown format {fmt!r}")


def eval_items(src: dict[str, Any], f: dict[str, Any], path: Path) -> Iterator[dict[str, Any]]:
    """Structured benchmark items from held-out (``role: eval``) files."""
    fmt, sid = src["format"], src["id"]
    base = f"{sid}:{f['path']}"
    if fmt == "gsm8k":
        for i, row in enumerate(_parquet_rows(path)):
            _, final = gsm8k_solution(row["answer"])
            yield {"uid": f"{base}:{i}", "source": sid, "suite": "math", "prompt": row["question"].strip(),
                   "answer": final}
    elif fmt == "arc":
        for i, row in enumerate(_parquet_rows(path)):
            prompt, labels, texts = arc_prompt(row)
            if row["answerKey"] in labels:
                yield {"uid": f"{base}:{row.get('id', i)}", "source": sid, "suite": "reasoning", "prompt": prompt,
                       "answer": row["answerKey"], "choices": labels, "choice_texts": texts}
    elif fmt == "mbpp":
        for i, row in enumerate(_parquet_rows(path)):
            yield {"uid": f"{base}:{row.get('task_id', i)}", "source": sid, "suite": "code",
                   "prompt": f"{row['text'].strip()}\nYour code should pass this test:\n{row['test_list'][0]}",
                   "tests": list(row["test_list"]), "setup": row.get("test_setup_code") or "",
                   "reference": row["code"]}
    else:
        raise ValueError(f"{fmt} has no eval files")
