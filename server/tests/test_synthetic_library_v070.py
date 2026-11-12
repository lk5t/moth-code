"""A real dataset-library build includes MOTH's verified synthetic examples with masks and token counts."""
import json
from pathlib import Path

import numpy as np


def test_library_build_with_synthetic_sources(client, owner, monkeypatch):
    from moth.datafactory import catalog
    from moth_server.intelligence import discovery, library

    ctx = client.app.state.ctx
    small = [{**s, "count": 300} for s in catalog.SOURCES if s["id"].startswith("synthetic-")]
    monkeypatch.setattr(catalog, "SOURCES", small)
    assert all(discovery.LICENSES.__contains__(s["license"]) for s in small)
    bid = library.start_build(ctx, owner["user"]["id"], {"sources": [s["id"] for s in small], "holdout_fraction": 0.05,
                                                         "holdout_overrides": {}, "near_dedupe": False}, wait=True)
    build = library.latest_ready(ctx)
    assert build and build["id"] == bid, library.status(ctx)
    manifest = build["manifest"] if isinstance(build["manifest"], dict) else json.loads(build["manifest"])
    counts = manifest["token_counts"]
    assert {"math", "conversation", "code"} <= set(counts)
    root = Path(build["path"]) / "tokens"
    mask = np.fromfile(root / "math" / "train.mask", dtype=np.uint8)
    assert 0 < mask.sum() < len(mask)  # only the assistant's answers are learned
