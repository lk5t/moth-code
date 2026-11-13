"""0.9.0: large licensed sources, used shard by shard, in three new record formats."""
import hashlib
import json
import random

import pytest

from moth.datafactory import build, catalog, fetch, parse
from test_datafactory import FakeHTTP

LONG = ("Photosynthesis is how green plants turn light, water and carbon dioxide into sugar and oxygen. "
        "The process happens in chloroplasts, which contain the pigment chlorophyll. ")


def test_every_large_source_is_pinned_and_licensed():
    from moth.datafactory.large_sources import SOURCES

    assert len(SOURCES) >= 13
    total = 0
    for s in SOURCES:
        assert len(s["revision"]) == 40 and s["license"] and s["attribution"] and s["files"]
        for f in s["files"]:
            assert len(f["sha256"]) == 64 and f["size"] > 0 and f["role"] == "train"
            total += f["size"]
        assert catalog.source(s["id"]) is s  # part of the catalog
    assert total > 50 * 10**9  # tens of gigabytes of training data available
    domains = {s["domain"] for s in SOURCES}
    assert {"conversation", "code", "knowledge", "math", "language"} <= domains


def test_shards_follow_the_budget():
    src = {"id": "x", "format": "parquet_text", "sharded": True,
           "files": [{"path": f"p{i}", "size": 100_000_000, "role": "train"} for i in range(10)]}
    assert catalog.shards_for(src, 1_000) == 1          # always at least one shard
    assert catalog.shards_for(src, 500_000_000) == 3    # 225 MB of parquet for 500 M characters
    assert catalog.shards_for(src, 10**12) == 10        # never more than exist
    assert [f["path"] for f in catalog.limited(src, 500_000_000)["files"]] == ["p0", "p1", "p2"]
    assert catalog.limited({**src, "sharded": False}, 1_000) == {**src, "sharded": False}


def _parquet(path, table):
    pa = pytest.importorskip("pyarrow")  # parquet support ships with MOTH Cloud (server dependency)
    import pyarrow.parquet as pq

    pq.write_table(pa.table(table), path)
    return path


def test_new_formats(tmp_path):
    p = _parquet(tmp_path / "t.parquet", {"text": [LONG, "", LONG + "More."]})
    recs = list(parse.train_records({"id": "c", "format": "parquet_text", "domain": "knowledge"}, {"path": "t"}, p))
    assert [r["text"] for r in recs] == [LONG.strip(), (LONG + "More.").strip()] and recs[0]["domain"] == "knowledge"
    msgs = [[{"role": "system", "content": "Be brief."}, {"role": "user", "content": "Hi"},
             {"role": "assistant", "content": "Hello!"}],
            [{"role": "assistant", "content": "orphan"}]]
    p = _parquet(tmp_path / "m.parquet", {"messages": msgs})
    recs = list(parse.train_records({"id": "s", "format": "parquet_messages", "domain": "conversation"}, {"path": "m"}, p))
    assert len(recs) == 1 and [m["role"] for m in recs[0]["messages"]] == ["user", "assistant"]  # system dropped
    p = _parquet(tmp_path / "q.parquet", {"instruction": ["Add a and b", ""], "output": ["def add(a, b): return a + b", "x"]})
    recs = list(parse.train_records({"id": "o", "format": "parquet_qa", "domain": "code",
                                     "fields": ["instruction", "output"]}, {"path": "q"}, p))
    assert len(recs) == 1 and recs[0]["messages"][1]["content"].startswith("def add")


def test_a_build_reads_only_what_its_budget_needs(tmp_path, monkeypatch):
    shards = []
    for i in range(3):
        rng = random.Random(i)
        words = ["river", "planet", "engine", "garden", "music", "number", "forest", "letter", "bridge", "window",
                 "teacher", "market", "cloud", "signal", "island", "kitchen", "pencil", "rocket", "valley", "story"]
        rows = [" ".join(f"The {rng.choice(words)} near the {rng.choice(words)} is {rng.choice(words)}ish today."
                         for _ in range(12)) for _ in range(400)]
        p = _parquet(tmp_path / f"s{i}.parquet", {"text": rows})
        data = p.read_bytes()
        shards.append(({"path": f"s{i}.parquet", "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                        "role": "train"}, data))
    src = {"id": "big", "name": "Big", "repo": "t/big", "revision": "a" * 40, "format": "parquet_text",
           "domain": "knowledge", "license": "MIT", "license_url": "", "attribution": "test", "description": "",
           "sharded": True, "files": [f for f, _ in shards]}
    monkeypatch.setattr(catalog, "SOURCES", [src])
    http = FakeHTTP({catalog.file_url(src, f): d for f, d in shards})
    monkeypatch.setattr(fetch.urllib.request, "urlopen", http)
    cap = 20_000
    m = build.build(tmp_path / "cache", tmp_path / "b", {"sources": ["big"], "holdout_fraction": 0.05,
                                                        "holdout_overrides": {}, "max_chars": {"big": cap}},
                    log=lambda m: None)
    fetched = {url.rsplit("/", 1)[-1] for url, _ in http.calls}
    assert fetched == {"s0.parquet"}  # one shard covers the budget: the others are not downloaded
    st = m["sources"][0]["stats"]
    assert cap <= st["chars"] < cap + 2_000 and st["read"] < 400, st  # stopped reading early
    assert [f["path"] for f in m["sources"][0]["files"]] == ["s0.parquet"]  # provenance: what was used
