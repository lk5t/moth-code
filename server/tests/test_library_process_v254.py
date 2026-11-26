"""2.5.4: a training-data build does its heavy work (downloading, de-duplicating, training the tokenizer,
tokenizing) in a separate process, so MOTH Cloud keeps answering while it runs."""
import threading
import time

import pytest

from moth_server.intelligence import library, library_proc as LP


def _records(n=300):
    return [{"uid": f"t{i}", "domain": "conversation", "messages": [{"role": "user", "content": f"What is {i} plus {i}?"},
                          {"role": "assistant", "content": f"{i} plus {i} is {2 * i}."}]} for i in range(n)]


@pytest.mark.timeout(600)
def test_a_build_runs_in_its_own_process_and_the_server_keeps_answering(client, owner, monkeypatch):
    from moth_server.intelligence import self_training

    ctx = client.app.state.ctx
    ctx.extras["library_in_process"] = False  # what production does
    monkeypatch.setattr(self_training, "records", lambda ctx: _records())
    seen = []
    real_run = LP.run

    def spy(fn, kwargs, log, in_process=False):
        seen.append((fn, in_process))
        return real_run(fn, kwargs, log, in_process)

    monkeypatch.setattr(LP, "run", spy)
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("bid", library.start_build(
        ctx, owner["user"]["id"], {"sources": [], "holdout_fraction": 0.05, "holdout_overrides": {},
                                   "near_dedupe": False, "vocab_size": 512, "tokenizer_chars": 50_000}, wait=True)))
    t.start()
    slowest = 0.0
    while t.is_alive():  # the server answers throughout
        a = time.time()
        assert client.get("/v1/health").status_code == 200
        slowest = max(slowest, time.time() - a)
        time.sleep(0.2)
    t.join()
    b = library.latest_ready(ctx)
    from sqlalchemy import select

    from moth_server.db import library_builds

    row = ctx.db.one(select(library_builds).where(library_builds.c.id == out["bid"]))
    assert b and b["id"] == out["bid"], (row["status"], row["error"], ctx.db.get_config(f"library_progress_{out['bid']}"))
    assert seen == [("collect", False), ("tokenize", False)]
    assert slowest < 5


def test_a_failure_in_the_build_process_is_reported(tmp_path):
    with pytest.raises(FileNotFoundError):
        LP.run("tokenize", {"out": str(tmp_path / "missing"), "tokenizer": str(tmp_path / "none.json"), "chunks": None},
               lambda m: None)
