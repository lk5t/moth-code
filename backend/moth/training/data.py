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
    h = int(hashlib.sha1((json.dumps(doc.messages, sort_keys=True) if doc.messages else doc.text).encode()).hexdigest()[:8], 16)
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
    seen = set()
    duplicates = 0
    try:
        for spec in specs:
            for doc in iter_source(spec):
                if should_stop and should_stop():
                    raise InterruptedError("dataset preparation cancelled")
                digest = hashlib.sha256((json.dumps(doc.messages, sort_keys=True) if doc.messages else doc.text).encode()).digest()
                if digest in seen:
                    duplicates += 1
                    continue
                seen.add(digest)
                if doc.messages:
                    msgs = [Message(m["role"], m["content"], allow_special=doc.trusted and m["role"] == "assistant")
                            for m in doc.messages]
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
    if counts['train'] == 0 and counts['val'] > 1:
        for kind in ('bin', 'mask'):
            (out / f'val.{kind}.tmp').replace(out / f'train.{kind}.tmp')
            (out / f'val.{kind}.tmp').write_bytes(b'')
        counts['train'], counts['val'] = counts['val'], 0
        docs['train'], docs['val'] = docs['val'], 0
    if counts["train"] == 0:
        kinds = ', '.join(f"{s.kind}:{Path(s.target).name}" for s in specs)
        raise ValueError(f"No text records were extracted from {kinds}; check empty files, ignored paths and supported TXT/JSONL formats")
    if counts['train'] + counts['val'] < 2:
        raise ValueError('Insufficient tokens for separate training and validation splits')
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
        "duplicates_skipped": duplicates,
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


class MixtureDataset:
    """Weighted sampling over per-domain prepared datasets (a Data Factory ``mixture.json``).

    Every batch row is drawn from one domain chosen by weight, so the curriculum controls exactly what
    the model sees. All domains must share one tokenizer. ``domain_batches`` gives per-domain batches for
    capability-level validation losses.
    """

    def __init__(self, path: str | Path, split: str, seq_len: int, weights: dict[str, float] | None = None):
        self.path = Path(path)
        self.mix = json.loads((self.path / "mixture.json").read_text())
        self.parts: dict[str, TokenDataset] = {}
        for d, info in self.mix["domains"].items():
            if info["tokens"].get(split, 0) < 3:
                continue
            self.parts[d] = TokenDataset(self.path / info["dir"], split, seq_len)
        if not self.parts:
            raise ValueError(f"mixture at {self.path} has no {split} data")
        fps = {p.meta["tokenizer_fingerprint"] for p in self.parts.values()}
        if fps != {self.mix["tokenizer_fingerprint"]}:
            raise ValueError("mixture domains were tokenized with different tokenizers")
        self.meta = {**next(iter(self.parts.values())).meta, "tokenizer_fingerprint": self.mix["tokenizer_fingerprint"],
                     "tokenizer_path": self.mix["tokenizer_path"]}
        self.seq_len = min(p.seq_len for p in self.parts.values())
        self.set_weights(weights)

    def set_weights(self, weights: dict[str, float] | None) -> None:
        w = {d: float((weights or {}).get(d, 0.0 if weights else 1.0)) for d in self.parts}
        if sum(w.values()) <= 0:
            w = {d: 1.0 for d in self.parts}
        total = sum(w.values())
        self.weights = {d: v / total for d, v in w.items() if v > 0}
        self._names = list(self.weights)
        self._probs = torch.tensor([self.weights[d] for d in self._names], dtype=torch.float64)

    def __len__(self) -> int:
        return sum(len(p) for p in self.parts.values())

    def batch(self, batch_size: int, generator: torch.Generator, device: str | torch.device = "cpu"):
        picks = torch.multinomial(self._probs, batch_size, replacement=True, generator=generator).tolist()
        rows = [self.parts[self._names[i]].batch(1, generator, "cpu") for i in picks]
        X = torch.cat([r[0][:, : self.seq_len] for r in rows])
        Y = torch.cat([r[1][:, : self.seq_len] for r in rows])
        M = torch.cat([r[2][:, : self.seq_len] for r in rows])
        return X.to(device), Y.to(device), M.to(device)

    def domain_batches(self) -> dict[str, TokenDataset]:
        return dict(self.parts)


def open_dataset(path: str | Path, split: str, seq_len: int, weights: dict[str, float] | None = None):
    """A prepared dataset directory or a Data Factory mixture directory."""
    if (Path(path) / "mixture.json").exists():
        return MixtureDataset(path, split, seq_len, weights)
    return TokenDataset(path, split, seq_len)


def dataset_meta(path: str | Path) -> dict:
    p = Path(path)
    if (p / "mixture.json").exists():
        mix = json.loads((p / "mixture.json").read_text())
        return {"tokenizer_path": mix["tokenizer_path"], "tokenizer_fingerprint": mix["tokenizer_fingerprint"],
                "mixture": True, "build_sha256": mix.get("build_sha256"),
                "tokens": {"train": sum(d["tokens"]["train"] for d in mix["domains"].values()),
                           "val": sum(d["tokens"]["val"] for d in mix["domains"].values())},
                "domains": {d: v["tokens"] for d, v in mix["domains"].items()}}
    return json.loads((p / "meta.json").read_text())
