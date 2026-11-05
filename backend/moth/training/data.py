"""Tokenised dataset preparation and batching.

A prepared dataset directory contains:

* ``train.bin`` / ``val.bin`` — token ids (uint16 or uint32), documents
  separated by ``<|eos|>``
* ``train.mask`` / ``val.mask`` — uint8 loss mask (1 = learn this token)
* ``meta.json`` — tokenizer fingerprint, sources with licenses, token counts
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import torch

from moth.model.chat_format import Message, encode_chat
from moth.model.tokenizer import Tokenizer
from moth.training.sources import Document, SourceSpec, iter_source, resolve_license


def _dtype_for(vocab_size: int):
    return np.uint16 if vocab_size <= 65535 else np.uint32


def _is_val(doc: Document, val_fraction: float) -> bool:
    h = int(hashlib.sha1(f"{doc.source}/{doc.id}".encode()).hexdigest()[:8], 16)
    return (h % 10_000) < val_fraction * 10_000


def prepare_dataset(
    sources: Iterable[SourceSpec | str | dict],
    tokenizer: Tokenizer,
    tokenizer_path: str | Path,
    out_dir: str | Path,
    val_fraction: float = 0.02,
    progress: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    specs = [SourceSpec.from_any(s) for s in sources]
    licenses = {s.spec: resolve_license(s) for s in specs}  # fail early if undeclared
    dtype = _dtype_for(tokenizer.vocab_size)
    files = {
        split: (open(out / f"{split}.bin.tmp", "wb"), open(out / f"{split}.mask.tmp", "wb"))
        for split in ("train", "val")
    }
    counts = {"train": 0, "val": 0}
    docs = {"train": 0, "val": 0}
    per_source: dict[str, int] = {}
    last = time.time()
    try:
        for spec in specs:
            for doc in iter_source(spec):
                if should_stop and should_stop():
                    raise InterruptedError("dataset preparation cancelled")
                if doc.messages:
                    msgs = [Message(m["role"], m["content"]) for m in doc.messages]
                    ids, mask = encode_chat(tokenizer, msgs, add_generation_prompt=False)
                else:
                    ids = tokenizer.encode(doc.text)
                    mask = [1] * len(ids)
                ids.append(tokenizer.eos_id)
                mask.append(1)
                split = "val" if _is_val(doc, val_fraction) else "train"
                fb, fm = files[split]
                fb.write(np.asarray(ids, dtype=dtype).tobytes())
                fm.write(np.asarray(mask, dtype=np.uint8).tobytes())
                counts[split] += len(ids)
                docs[split] += 1
                per_source[spec.spec] = per_source.get(spec.spec, 0) + len(ids)
                if progress and time.time() - last > 1.0:
                    last = time.time()
                    progress({"documents": docs["train"] + docs["val"], "tokens": counts["train"] + counts["val"],
                              "source": spec.spec})
    finally:
        for fb, fm in files.values():
            fb.close()
            fm.close()
    if counts["train"] == 0:
        raise ValueError("no training tokens were produced from the given sources")
    if counts["val"] == 0:  # tiny corpora: carve validation from the end of train
        _split_tail(out, dtype, max(1, counts["train"] // 50))
        moved = max(1, counts["train"] // 50)
        counts["train"] -= moved
        counts["val"] += moved
    for split in ("train", "val"):
        (out / f"{split}.bin.tmp").replace(out / f"{split}.bin")
        (out / f"{split}.mask.tmp").replace(out / f"{split}.mask")
    meta = {
        "format": 1,
        "created": time.time(),
        "dtype": np.dtype(dtype).name,
        "tokenizer_path": str(Path(tokenizer_path).resolve()),
        "tokenizer_fingerprint": tokenizer.fingerprint(),
        "vocab_size": tokenizer.vocab_size,
        "tokens": counts,
        "documents": docs,
        "sources": [{"spec": s.spec, "license": licenses[s.spec], "tokens": per_source.get(s.spec, 0)} for s in specs],
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _split_tail(out: Path, dtype, n: int) -> None:
    for kind, dt in (("bin", dtype), ("mask", np.uint8)):
        train = np.fromfile(out / f"train.{kind}.tmp", dtype=dt)
        train[-n:].tofile(out / f"val.{kind}.tmp")
        train[:-n].tofile(out / f"train.{kind}.tmp")


class TokenDataset:
    """Random fixed-length windows over a prepared split (memory-mapped)."""

    def __init__(self, path: str | Path, split: str, seq_len: int):
        self.path = Path(path)
        self.meta = json.loads((self.path / "meta.json").read_text())
        dtype = np.dtype(self.meta["dtype"])
        self.tokens = np.memmap(self.path / f"{split}.bin", dtype=dtype, mode="r")
        self.mask = np.memmap(self.path / f"{split}.mask", dtype=np.uint8, mode="r")
        self.seq_len = min(seq_len, max(2, len(self.tokens) - 2))
        if len(self.tokens) < 3:
            raise ValueError(f"split {split!r} is too small to train on ({len(self.tokens)} tokens)")

    def __len__(self) -> int:
        return len(self.tokens)

    def batch(self, batch_size: int, generator: torch.Generator, device: str | torch.device = "cpu"):
        hi = len(self.tokens) - self.seq_len - 1
        starts = torch.randint(0, max(1, hi), (batch_size,), generator=generator).tolist()
        x = np.stack([self.tokens[s : s + self.seq_len] for s in starts]).astype(np.int64)
        y = np.stack([self.tokens[s + 1 : s + 1 + self.seq_len] for s in starts]).astype(np.int64)
        m = np.stack([self.mask[s + 1 : s + 1 + self.seq_len] for s in starts])
        X, Y, M = torch.from_numpy(x), torch.from_numpy(y), torch.from_numpy(m)
        if str(device).startswith("cuda"):
            return (X.pin_memory().to(device, non_blocking=True), Y.pin_memory().to(device, non_blocking=True),
                    M.pin_memory().to(device, non_blocking=True))
        return X.to(device), Y.to(device), M.to(device)
