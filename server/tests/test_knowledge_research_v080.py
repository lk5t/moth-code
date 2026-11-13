"""0.8.0: Knowledge 2.0 metadata and the extractive Research Engine."""
from conftest import H, register_verified


def _add(client, token, title, text, **kw):
    r = client.post("/v1/knowledge", json={"title": title, "text": text, **kw}, headers=H(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_metadata_near_duplicates_verification_and_project_preference(client, settings, owner):
    tok = owner["token"]
    code = _add(client, tok, "Retry helper", "```python\ndef retry(fn, times=3):\n    for _ in range(times):\n"
                "        try:\n            return fn()\n        except Exception:\n            pass\n```")
    assert code["document"]["meta"]["category"] == "code" and not code["document"]["meta"]["verified"]
    base = " ".join(f"Step {i}: the deploy script uploads bundle part {i} to staging host {i % 3} and checks it."
                    for i in range(40))
    a = _add(client, tok, "Deploy notes", base, project="moth-site")
    b = _add(client, tok, "Deploy notes (copy)", base + " Also notify the team.")
    assert a["document"]["meta"]["project"] == "moth-site"
    assert b["near_duplicate_of"] == a["document"]["id"]  # kept, but flagged
    other = _add(client, tok, "Other deploy", "The deploy script for the docs site uploads files with rsync. " * 6,
                 project="docs")
    hits = client.get("/v1/knowledge/search", params={"q": "deploy script uploads", "project": "docs"},
                      headers=H(tok)).json()["results"]
    assert hits[0]["doc_id"] == other["document"]["id"]  # same-project knowledge first
    m = client.patch(f"/v1/knowledge/{a['document']['id']}", json={"verified": True, "confidence": 0.9},
                     headers=H(tok)).json()["meta"]
    assert m["verified"] and m["confidence"] == 0.9 and not m["stale"]
    m = client.patch(f"/v1/knowledge/{a['document']['id']}", json={"review_days": 1}, headers=H(tok)).json()["meta"]
    import time
    from moth_server.db import knowledge_meta
    ctx = client.app.state.ctx
    with ctx.db.tx() as c:
        c.execute(knowledge_meta.update().where(knowledge_meta.c.doc_id == a["document"]["id"])
                  .values(review_after=time.time() - 1))
    docs = {d["id"]: d for d in client.get("/v1/knowledge", headers=H(tok)).json()["documents"]}
    assert docs[a["document"]["id"]]["meta"]["stale"]  # flagged as possibly outdated
    other_user = register_verified(client, settings, "kn_other")
    assert client.patch(f"/v1/knowledge/{a['document']['id']}", json={"verified": True},
                        headers=H(other_user["token"])).status_code == 404  # never someone else's documents


def test_research_cites_corroborates_flags_conflicts_and_gaps(client, owner):
    tok = owner["token"]
    _add(client, tok, "Release guide", "The MOTH worker uses port 8900 for its local server. Workers update "
                                       "themselves every 15 minutes.")
    _add(client, tok, "Ops notes", "In production the MOTH worker uses port 8901 for its local server. Workers "
                                   "update themselves every 15 minutes after a release.")
    r = client.post("/v1/research", json={"question": "Which port does the MOTH worker local server use, and "
                                                      "what about kubernetes?", "save": True}, headers=H(tok)).json()
    assert r["summary"]["sources"] == 2 and r["findings"]
    assert all(isinstance(f["cite"], int) for f in r["findings"])
    assert any(f["status"] == "corroborated" for f in r["findings"])
    assert r["conflicts"] and "8900" in r["conflicts"][0]["why"] and "8901" in r["conflicts"][0]["why"]
    assert "kubernet" in r["gaps"]  # nobody wrote about it: a gap, not an invented answer
    assert "not verified facts" in r["note"]
    assert r["saved"]["meta"]["category"] == "research" and r["saved"]["meta"]["confidence"] == 0.3
