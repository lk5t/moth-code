"""The approved dataset library.

Every entry is pinned to an exact upstream revision, and every file to its size and SHA-256 (the
Hugging Face LFS object id *is* the file's SHA-256), so a download is verified before it is used and a
training mixture can be rebuilt byte-for-byte. Only datasets whose published license allows training
a model that is offered commercially are listed; attribution and share-alike obligations are carried
into every model's ``ATTRIBUTION.md``.

``role`` says how a file may be used: ``train`` files feed training, ``eval`` files are held out for
benchmarks and are never trained on (training text that overlaps them is removed).

Updates: ``check_updates`` compares each pinned revision with the dataset's current upstream revision.
A changed dataset is never used silently — the Owner approves the new revision, which is then pinned,
downloaded once and verified like the first one.
"""

from __future__ import annotations

from typing import Any

HF = "https://huggingface.co/datasets/{repo}/resolve/{revision}/{path}"

# Capability domains used by the curriculum, the benchmarks and the dashboards.
DOMAINS = ("language", "conversation", "knowledge", "math", "reasoning", "code", "writing")

SOURCES: list[dict[str, Any]] = [
    {
        "id": "tinystories", "name": "TinyStories", "domain": "language", "repo": "roneneldan/TinyStories",
        "revision": "f54c09fd23315a6f9c86f9dc80f725de7d8f9c64", "format": "stories",
        "license": "CDLA-Sharing-1.0", "license_url": "https://cdla.dev/sharing-1-0/",
        "attribution": "TinyStories by Ronen Eldan and Yuanzhi Li (Microsoft Research)",
        "description": "Short stories in simple English: grammar, narrative and everyday words.",
        "files": [
            {"path": "TinyStoriesV2-GPT4-valid.txt", "size": 22502601, "role": "train",
             "sha256": "6874bae9a4c1a4e7edcf0e53b86c17817e9cf881fc75ff2368da457b80c0585d"},
            {"path": "TinyStories-valid.txt", "size": 19447282, "role": "train",
             "sha256": "94e431816c4cce81ff71e4408ff8d3bda9a42e8d2663986697c3954288cb38b4"},
        ],
    },
    {
        "id": "dolly-15k", "name": "Databricks Dolly 15k", "domain": "conversation",
        "repo": "databricks/databricks-dolly-15k", "revision": "bdd27f4d94b9c1f951818a7da7fd7aeea5dbff1a",
        "format": "dolly", "license": "CC-BY-SA-3.0", "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "attribution": "databricks-dolly-15k by Databricks, Inc. (CC BY-SA 3.0)",
        "description": "Human-written instructions and answers: questions, explanations, summaries, writing.",
        "files": [{"path": "databricks-dolly-15k.jsonl", "size": 13085339, "role": "train",
                   "sha256": "2df9083338b4abd6bceb5635764dab5d833b393b55759dffb0959b6fcbf794ec"}],
    },
    {
        "id": "oasst1", "name": "OpenAssistant Conversations (oasst1)", "domain": "conversation",
        "repo": "OpenAssistant/oasst1", "revision": "fdf72ae0827c1cda404aff25b6603abec9e3399b",
        "format": "oasst_trees", "license": "Apache-2.0", "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
        "attribution": "OpenAssistant Conversations (oasst1) by LAION and contributors (Apache-2.0)",
        "description": "Multi-turn human conversations with an assistant, best-ranked replies only.",
        "files": [{"path": "2023-04-12_oasst_ready.trees.jsonl.gz", "size": 34145252, "role": "train",
                   "sha256": "2a9a8fd343e9b28e04a895a669d3253f82d93e9c174d440199ae19d5fafbdff7"}],
    },
    {
        "id": "simple-wikipedia", "name": "Simple English Wikipedia (2023-11-01)", "domain": "knowledge",
        "repo": "wikimedia/wikipedia", "revision": "b04c8d1ceb2f5cd4588862100d08de323dccfbaa",
        "format": "wikipedia", "license": "CC-BY-SA-3.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "attribution": "Simple English Wikipedia contributors (CC BY-SA 3.0), via the wikimedia/wikipedia dataset",
        "description": "Encyclopedia articles in plain English: facts about the world.",
        "files": [{"path": "20231101.simple/train-00000-of-00001.parquet", "size": 156885218, "role": "train",
                   "sha256": "31bded16768a47c286becd292079122f5d7d4397a17b87d4250a00ccd581e6f0"}],
    },
    {
        "id": "gsm8k", "name": "GSM8K", "domain": "math", "repo": "openai/gsm8k",
        "revision": "740312add88f781978c0658806c59bc2815b9866", "format": "gsm8k", "license": "MIT",
        "license_url": "https://opensource.org/license/mit", "attribution": "GSM8K by OpenAI (MIT)",
        "description": "Grade-school maths word problems with step-by-step solutions.",
        "files": [
            {"path": "main/train-00000-of-00001.parquet", "size": 2306545, "role": "train",
             "sha256": "ea82612ea9582142387730c793eb67d3b12849002bc0b7fa6f8efafa7351419d"},
            {"path": "main/test-00000-of-00001.parquet", "size": 419088, "role": "eval",
             "sha256": "ee7b8da9e381df27b9e3f7758a159ab2bdaa4dbaa910546cbbc47e0cb44e4f59"},
        ],
    },
    {
        "id": "arc", "name": "AI2 Reasoning Challenge (ARC)", "domain": "reasoning", "repo": "allenai/ai2_arc",
        "revision": "210d026faf9955653af8916fad021475a3f00453", "format": "arc", "license": "CC-BY-SA-4.0",
        "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "attribution": "AI2 Reasoning Challenge by the Allen Institute for AI (CC BY-SA 4.0)",
        "description": "Science multiple-choice questions that need reasoning.",
        "files": [
            {"path": "ARC-Easy/train-00000-of-00001.parquet", "size": 330598, "role": "train",
             "sha256": "b315db8a4be597dc7daa50a4e70d48dd7c990c32085629e6ccd8c926beaa80b5"},
            {"path": "ARC-Challenge/train-00000-of-00001.parquet", "size": 189909, "role": "train",
             "sha256": "e488c1587ffdcfc8443f916c53488a95cd471c5790e0746c6bfe4cecf20962cb"},
            {"path": "ARC-Easy/test-00000-of-00001.parquet", "size": 346257, "role": "eval",
             "sha256": "4160597d618ae851c7eb04e281574f3f654776216ac6b6641588d64527b47177"},
        ],
    },
    {
        "id": "mbpp", "name": "MBPP (Mostly Basic Python Problems)", "domain": "code",
        "repo": "google-research-datasets/mbpp", "revision": "4bb6404fdc6cacfda99d4ac4205087b89d32030c",
        "format": "mbpp", "license": "CC-BY-4.0", "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution": "MBPP by Google Research (CC BY 4.0)",
        "description": "Short Python programming tasks with solutions and tests.",
        "files": [
            {"path": "full/train-00000-of-00001.parquet", "size": 87223, "role": "train",
             "sha256": "09d125ca31edacb7800be8c67c45abff618faf0214ff551291817d06bdb914ae"},
            {"path": "full/validation-00000-of-00001.parquet", "size": 25144, "role": "train",
             "sha256": "3f0ec060987432d99fe8fb409d31e6c67445b208a01741c5583517c80a10fe80"},
            {"path": "full/prompt-00000-of-00001.parquet", "size": 7878, "role": "train",
             "sha256": "a053e4bb85ceb77430ae80592addb4ca4dc6ba087592f9e04537800ee88b7431"},
            {"path": "full/test-00000-of-00001.parquet", "size": 115824, "role": "eval",
             "sha256": "566fd53060ffba5766dace1d1e2f4c38906781526de222b0dfbdbc325b696c77"},
        ],
    },
    {
        "id": "codefeedback", "name": "CodeFeedback (filtered instructions)", "domain": "code",
        "repo": "m-a-p/CodeFeedback-Filtered-Instruction", "revision": "a08c213a9748c66c15d0225814be80a2e77adf4a",
        "format": "qa_jsonl", "fields": ("query", "answer"), "license": "Apache-2.0",
        "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
        "attribution": "CodeFeedback-Filtered-Instruction by M-A-P (Apache-2.0)",
        "description": "Programming questions with worked answers in many languages, quality-filtered.",
        "files": [{"path": "CodeFeedback-Filtered-Instruction.jsonl", "size": 371228314, "role": "train",
                   "sha256": "6dd3f7797cd86a7e437de660ad259c50835812f8e309d893f09de77b2ee80063"}],
    },
    {
        "id": "magicoder-oss", "name": "Magicoder OSS-Instruct 75K", "domain": "code",
        "repo": "ise-uiuc/Magicoder-OSS-Instruct-75K", "revision": "5f839b1f368a76b161028bb9edff055db34022b2",
        "format": "qa_jsonl", "fields": ("problem", "solution"), "license": "MIT",
        "license_url": "https://opensource.org/license/mit",
        "attribution": "Magicoder OSS-Instruct 75K by the UIUC iSE group (MIT)",
        "description": "Coding problems inspired by open-source code, with solutions; decontaminated against benchmarks.",
        "files": [{"path": "data-oss_instruct-decontaminated.jsonl", "size": 203201169, "role": "train",
                   "sha256": "f988f14d3516a9f958eeea310f63903727c6d3463bc9cb435288b6ca4bb09cf9"}],
    },
    {
        "id": "glaive-code", "name": "Glaive code assistant", "domain": "code",
        "repo": "glaiveai/glaive-code-assistant", "revision": "398ce053096475671e8d3872b8e5b28b59f8fcec",
        "format": "qa_json", "fields": ("question", "answer"), "license": "Apache-2.0",
        "license_url": "https://www.apache.org/licenses/LICENSE-2.0",
        "attribution": "glaive-code-assistant by Glaive AI (Apache-2.0)",
        "description": "Developer questions (debugging, tools, languages) with explained answers.",
        "files": [{"path": "c9bc9129-eba0-4b10-8292-4ae70fc7fa0d.json", "size": 218840602, "role": "train",
                   "sha256": "bae500490b2c9af237482f66c6070f689342717f7c55c45fbf8f153b56f7cf9c"}],
    },
    {
        "id": "python-stdlib", "name": "Python standard library", "domain": "code", "repo": None, "revision": None,
        "format": "stdlib", "license": "PSF-2.0", "license_url": "https://docs.python.org/3/license.html",
        "attribution": "Python standard library, Python Software Foundation (PSF License 2.0)",
        "description": "Real-world Python source code, found on the machine (no download).",
        "files": [],
    },
    # 0.7.0: verified synthetic examples for the foundations (generated by MOTH, every example checked)
    *[{"id": f"synthetic-{k}", "name": n, "domain": d, "repo": None, "revision": None, "format": "synthetic",
       "kind": k, "count": c, "license": "CC0-1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
       "attribution": "Generated by MOTH; every example is checked before use (CC0)", "description": desc, "files": []}
      for k, n, d, c, desc in (
          ("arithmetic", "Verified arithmetic", "math", 20_000,
           "Addition, subtraction, multiplication and division with exactly computed answers."),
          ("instructions", "Verified simple instructions", "conversation", 20_000,
           "Short, checkable instructions (repeat, sort, count, compare) with correct replies."),
          ("python", "Verified Python fundamentals", "code", 5_000,
           "Small Python functions, each executed against its tests before it is used."),
          ("reasoning", "Verified reasoning", "reasoning", 15_000,
           "Number sequences, orderings from comparisons and multi-step word problems, each re-derived."),
          ("language", "Verified language basics", "language", 15_000,
           "Plurals, opposites, alphabetical order, word counts and sentence casing from checked tables."),
          ("dialogue", "Verified multi-turn conversations", "conversation", 30_000,
           "Conversations that depend on earlier turns: remembering facts, corrections, follow-ups, list "
           "recall, clarifying questions, saying \"I don't know\", greetings and formats — each answer re-derived."),
          ("debugging", "Verified debugging exercises", "code", 15_000,
           "Functions with one planted bug (confirmed to fail their tests) and the fix (confirmed to pass)."),
          ("code_explain", "Verified code explanations", "code", 8_000,
           "What a function does, its inputs and a worked example computed by running it."),
          ("test_writing", "Verified test writing", "code", 8_000,
           "Tests for a function; every assertion is executed against it before use."))],
]

# 0.9.0: large licensed sources (tens of GB in total), pinned file by file. A ``sharded`` source is used one
# file (shard) at a time: the library adds the next shard when MOTH needs more data (see ``shards_for``).
from moth.datafactory.large_sources import SOURCES as _LARGE  # noqa: E402

SOURCES += _LARGE

# Rough bytes of downloaded file per character of text it yields (parquet is compressed).
BYTES_PER_CHAR = {"parquet_text": 0.45, "parquet_messages": 0.45, "parquet_qa": 0.45, "stories": 1.0,
                  "qa_json": 1.1, "oasst_trees": 0.5}


def shards_for(src: dict[str, Any], max_chars: int | None) -> int:
    """How many of a sharded source's train files are needed for ``max_chars`` characters (at least one)."""
    train = [f for f in src["files"] if f["role"] == "train"]
    if not src.get("sharded") or not max_chars:
        return len(train)
    need, total, n = max_chars * BYTES_PER_CHAR.get(src["format"], 1.0), 0, 0
    for f in train:
        if total >= need:
            break
        total += f["size"]
        n += 1
    return max(1, n)


def limited(src: dict[str, Any], max_chars: int | None) -> dict[str, Any]:
    """The source with only the shards needed for ``max_chars`` (eval files are always kept)."""
    if not src.get("sharded"):
        return src
    n = shards_for(src, max_chars)
    train = [f for f in src["files"] if f["role"] == "train"][:n]
    return {**src, "files": [f for f in src["files"] if f["role"] != "train"] + train}


# Each Dolly category maps to the capability it mostly teaches.
DOLLY_DOMAINS = {"creative_writing": "writing", "brainstorming": "writing", "summarization": "writing",
                 "open_qa": "knowledge", "closed_qa": "knowledge", "information_extraction": "knowledge",
                 "classification": "reasoning", "general_qa": "conversation"}


def source(sid: str) -> dict[str, Any]:
    for s in SOURCES:
        if s["id"] == sid:
            return s
    raise KeyError(f"unknown dataset {sid!r}")


def file_url(src: dict[str, Any], f: dict[str, Any], revision: str | None = None) -> str:
    return HF.format(repo=src["repo"], revision=revision or src["revision"], path=f["path"])


def public(src: dict[str, Any]) -> dict[str, Any]:
    return {k: src[k] for k in ("id", "name", "domain", "license", "license_url", "attribution", "description",
                                 "revision")} | {
        "download_bytes": sum(f["size"] for f in src["files"]),
        "files": [{"path": f["path"], "size": f["size"], "role": f["role"], "sha256": f["sha256"]}
                  for f in src["files"]]}


def check_updates(fetch_json, sources=None) -> list[dict[str, Any]]:
    """Compare pinned revisions with upstream. ``fetch_json(url)`` returns parsed JSON (injectable for tests)."""
    out = []
    for s in SOURCES if sources is None else sources:
        if not s["repo"]:
            continue
        try:
            info = fetch_json(f"https://huggingface.co/api/datasets/{s['repo']}")
            latest = info.get("sha")
            out.append({"id": s["id"], "pinned": s["revision"], "latest": latest,
                        "update_available": bool(latest and latest != s["revision"])})
        except Exception as e:  # network problems never break training
            out.append({"id": s["id"], "pinned": s["revision"], "error": str(e)[:200]})
    return out


def with_pin(src: dict[str, Any], pin: dict[str, Any] | None) -> dict[str, Any]:
    """The source at an Owner-approved revision (``pin`` = ``{"revision", "files": [...]}``)."""
    if not pin:
        return src
    return {**src, "revision": pin["revision"], "files": pin["files"]}


def resolve_revision(src: dict[str, Any], revision: str, fetch_json) -> dict[str, Any]:
    """Pin for ``revision``: the same files, with sizes and SHA-256 read from the upstream LFS metadata."""
    files = []
    for f in src["files"]:
        folder = f["path"].rsplit("/", 1)[0] if "/" in f["path"] else ""
        url = f"https://huggingface.co/api/datasets/{src['repo']}/tree/{revision}" + (f"/{folder}" if folder else "")
        entry = next((x for x in fetch_json(url) if x.get("path") == f["path"]), None)
        if not entry or not (entry.get("lfs") or {}).get("oid"):
            raise ValueError(f"{f['path']} is missing or has no checksum at revision {revision[:12]}")
        files.append({**f, "size": int(entry["size"]), "sha256": entry["lfs"]["oid"]})
    return {"revision": revision, "files": files}
