"""MOTH Research Engine (0.8.0): structured, cited research over authorized knowledge.

Authorized sources are the knowledge the person may see: Owner-approved shared knowledge and their own
documents (project notes, documentation, saved conversations). MOTH does not browse the web here.

A report is **extractive**: MOTH quotes what the sources say and organises it; it does not invent or
assert anything itself. For a question it

1. searches the knowledge base for the question and for each of its main terms (sub-questions);
2. keeps the sentences of the best passages that mention the question's terms, each with its citation
   and the source's confidence, verification and review status;
3. marks a finding *corroborated* when another document says something with the same key terms, and
   *single source* otherwise;
4. flags *conflicts*: sentences from different documents about the same terms that state different
   numbers (for example two different versions, sizes or dates);
5. lists *knowledge gaps*: terms of the question that no source covers.

Nothing in a report is treated as a verified fact: verification comes only from a person marking a
document verified. A report can be saved as a research note (low confidence, unverified, reviewed
after 90 days).
"""

from __future__ import annotations

import re
import time
from typing import Any

from moth_server.context import Ctx
from moth_server.intelligence import knowledge as K

SENT = re.compile(r"(?<=[.!?])\s+|\n+")
NUM = re.compile(r"\b\d+(?:\.\d+)*\b")


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in SENT.split(text) if 20 <= len(s.strip()) <= 400]


def run(ctx: Ctx, user_id: int | None, question: str, project: str | None = None, k: int = 6) -> dict[str, Any]:
    q_terms = list(dict.fromkeys(K.terms(question)))
    if not q_terms:
        raise K.KnowledgeError("Ask a question with at least one meaningful word.")
    queries = [question] + [t for t in q_terms[:4]]
    hits: dict[int, dict] = {}
    for q in queries:  # the question and its main terms (sub-questions)
        for h in K.search(ctx, user_id, q, k=k, project=project):
            hits.setdefault(h["chunk_id"], h)
    sources: list[dict] = []
    src_index: dict[int, int] = {}
    findings: list[dict[str, Any]] = []
    covered: set[str] = set()
    for h in sorted(hits.values(), key=lambda h: -h["score"]):
        for s in _sentences(h["text"]):
            st = set(K.terms(s))
            shared = [t for t in q_terms if t in st]
            if not shared:
                continue
            if h["doc_id"] not in src_index:
                src_index[h["doc_id"]] = len(sources) + 1
                meta = h.get("meta") or {}
                sources.append({"n": src_index[h["doc_id"]], "doc_id": h["doc_id"], "title": h["title"],
                                "source": h["source"], "version": h["version"], "shared": h["shared"],
                                "confidence": meta.get("confidence"), "verified": bool(meta.get("verified")),
                                "stale": bool(meta.get("stale"))})
            covered.update(shared)
            findings.append({"text": s, "cite": src_index[h["doc_id"]], "doc_id": h["doc_id"], "terms": shared,
                             "coverage": round(len(shared) / len(q_terms), 3), "_t": st})
    findings.sort(key=lambda f: (-f["coverage"], f["cite"]))
    findings = findings[:20]
    conflicts = []
    for i, a in enumerate(findings):
        support = {b["doc_id"] for b in findings if b["doc_id"] != a["doc_id"]
                   and len(a["_t"] & b["_t"] & set(q_terms)) >= max(1, len(a["terms"]) * 0.6)}
        a["status"] = "corroborated" if support else "single source"
        a["supported_by"] = sorted(src_index[d] for d in support)
        for b in findings[i + 1:]:
            if b["doc_id"] == a["doc_id"] or len(a["_t"] & b["_t"]) < 3:
                continue
            na, nb = set(NUM.findall(a["text"])), set(NUM.findall(b["text"]))
            if na and nb and na != nb:
                conflicts.append({"a": {"text": a["text"], "cite": a["cite"]}, "b": {"text": b["text"], "cite": b["cite"]},
                                  "about": sorted(a["_t"] & b["_t"] & set(q_terms))[:5] or sorted(a["_t"] & b["_t"])[:5],
                                  "why": f"different numbers: {', '.join(sorted(na))} vs {', '.join(sorted(nb))}"})
    for f in findings:
        f.pop("_t", None)
    gaps = [t for t in q_terms if t not in covered]
    return {"question": question, "project": project, "created_at": time.time(), "findings": findings,
            "sources": sources, "conflicts": conflicts[:10], "gaps": gaps,
            "summary": {"sources": len(sources), "findings": len(findings),
                        "corroborated": sum(f["status"] == "corroborated" for f in findings),
                        "single_source": sum(f["status"] == "single source" for f in findings),
                        "conflicts": len(conflicts), "gaps": len(gaps)},
            "note": "Extractive research: these are statements from your authorized sources with citations. "
                    "They are not verified facts; conflicts and single-source statements need checking."}


def as_text(r: dict[str, Any]) -> str:
    lines = [f"# Research: {r['question']}", "", "Statements from sources (not verified facts).", ""]
    for f in r["findings"]:
        lines.append(f"- {f['text']} [{f['cite']}] ({f['status']})")
    if r["conflicts"]:
        lines += ["", "## Conflicts"] + [f"- [{c['a']['cite']}] vs [{c['b']['cite']}]: {c['why']}" for c in r["conflicts"]]
    if r["gaps"]:
        lines += ["", "## Knowledge gaps", "- No source covers: " + ", ".join(r["gaps"])]
    lines += ["", "## Sources"] + [f"[{s['n']}] {s['title']}" + (f" — {s['source']}" if s["source"] else "")
                                  for s in r["sources"]]
    return "\n".join(lines)


def save(ctx: Ctx, user_id: int, report: dict[str, Any]) -> dict[str, Any]:
    """Keep a report as a research note: low confidence, unverified, reviewed after 90 days."""
    return K.add(ctx, user_id, f"Research: {report['question'][:180]}", as_text(report),
                 source=f"research:{int(report['created_at'])}", category="research", project=report.get("project"))
