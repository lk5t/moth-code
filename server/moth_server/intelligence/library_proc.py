"""2.5.4: the heavy steps of a training-data build run in their own process.

Downloading, cleaning, de-duplicating, training a tokenizer and tokenizing millions of records used to run
inside MOTH Cloud's server process. With the larger 2.5 libraries that used so much memory and CPU that the
server stopped answering and was then stopped by the system, and the interrupted build started again after
the restart. In a separate, lower-priority process the server stays responsive; if memory runs out, the
system stops the build (it is retried later), not the server.
"""

from __future__ import annotations

import builtins
import multiprocessing as mp
import os
import queue
from pathlib import Path
from typing import Any, Callable

WAIT_POLL = 2.0


def _lower_priority() -> None:
    try:
        os.nice(10)
    except (OSError, AttributeError):
        pass
    try:
        Path("/proc/self/oom_score_adj").write_text("1000")
    except OSError:
        pass


def _child(q, fn_name: str, kwargs: dict) -> None:
    _lower_priority()
    try:
        result = globals()[fn_name](log=lambda m: q.put(("log", str(m))), **kwargs)
        q.put(("done", result))
    except BaseException as e:  # noqa: BLE001 — reported to the server, which marks the build failed
        q.put(("error", (type(e).__name__, str(e))))


def run(fn_name: str, kwargs: dict, log: Callable[[str], None], in_process: bool = False) -> Any:
    """Run ``fn_name(**kwargs)`` in a fresh process; its progress messages are passed to ``log``."""
    if in_process:  # tests that replace the data sources in this process
        return globals()[fn_name](log=log, **kwargs)
    c = mp.get_context("spawn")
    q = c.Queue()
    p = c.Process(target=_child, args=(q, fn_name, kwargs), name=f"moth-{fn_name}", daemon=True)
    p.start()
    try:
        while True:
            try:
                kind, value = q.get(timeout=WAIT_POLL)
            except queue.Empty:
                if not p.is_alive():
                    try:  # the last message may arrive just after the process ended
                        kind, value = q.get(timeout=WAIT_POLL)
                    except queue.Empty:
                        raise RuntimeError(f"data preparation stopped unexpectedly (exit {p.exitcode}; "
                                           "usually not enough memory); it is retried automatically") from None
                else:
                    continue
            if kind == "log":
                log(value)
            elif kind == "done":
                return value
            else:
                name, msg = value
                err = getattr(builtins, name, None)
                raise (err(msg) if isinstance(err, type) and issubclass(err, Exception) else RuntimeError(f"{name}: {msg}"))
    finally:
        p.join(10)
        if p.is_alive():
            p.kill()
            p.join(5)


# ---- the steps (run in the child) -----------------------------------------------------------------------
def collect(log, cache: str, out: str, cfg: dict, extra: list, tokenizer: str | None, vocab: int,
            tokenizer_chars: int) -> tuple[dict, str]:
    """Download and prepare the corpus; train its tokenizer when the lineage has none yet."""
    from moth.datafactory import build as factory
    from moth.model.tokenizer import train_bpe

    manifest = factory.build(Path(cache), Path(out), cfg, log=log, extra_sources=extra)
    if tokenizer is None:
        tokenizer = str(Path(out) / "tokenizer.json")
        train_bpe(factory.iter_texts(Path(out), per_domain_chars=tokenizer_chars), vocab).save(tokenizer)
    return manifest, tokenizer


def tokenize(log, out: str, tokenizer: str, chunks: dict | None) -> dict:
    from moth.datafactory import build as factory
    from moth.model.tokenizer import Tokenizer

    return factory.tokenize_build(Path(out), Tokenizer.load(tokenizer), Path(tokenizer), log=log, train_chunks=chunks)
