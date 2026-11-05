"""Custom byte-level BPE tokenizer, implemented from scratch.

* Lossless: any byte sequence round-trips (base vocabulary = 256 bytes).
* Pre-tokenisation keeps code structure: newline + indentation runs are
  single pieces, identifiers/numbers/punctuation are split apart.
* Special tokens occupy ids ``0..N-1`` so the byte/merge ids are stable.
* Training uses incremental pair-count updates so only the words affected by
  a merge are re-counted.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Iterable

SPECIAL_TOKENS = [
    "<|pad|>", "<|bos|>", "<|eos|>", "<|system|>", "<|user|>", "<|assistant|>", "<|end|>",
    "<|tool_call|>", "<|tool_result|>", "<|fim_prefix|>", "<|fim_suffix|>", "<|fim_middle|>",
    "<|file|>", "<|reserved_0|>", "<|reserved_1|>", "<|reserved_2|>",
]

PATTERN = (
    r"'(?:s|d|m|t|ll|ve|re)\b"  # English contractions
    r"| ?[A-Za-z_]+"  # words / identifiers (with optional leading space)
    r"| ?[0-9]{1,3}"  # numbers in groups of up to three digits
    r"|\r?\n[ \t]*"  # newline plus following indentation
    r"| ?[^\sA-Za-z0-9_]+"  # punctuation / operators / non-ASCII
    r"|[ \t]+(?!\S)"  # whitespace runs, leaving the last space to attach to the next token
    r"|\s+"
)


class Tokenizer:
    def __init__(self, merges: list[tuple[int, int]], special_tokens: list[str] | None = None,
                 pattern: str = PATTERN):
        self.special_tokens = list(special_tokens or SPECIAL_TOKENS)
        self.n_special = len(self.special_tokens)
        self.pattern = pattern
        self._re = re.compile(pattern)
        self.merges = [tuple(m) for m in merges]
        self.special_ids = {t: i for i, t in enumerate(self.special_tokens)}
        self._special_re = re.compile("(" + "|".join(re.escape(t) for t in self.special_tokens) + ")")
        # id -> bytes
        self.vocab: dict[int, bytes] = {i: t.encode() for i, t in enumerate(self.special_tokens)}
        for b in range(256):
            self.vocab[self.n_special + b] = bytes([b])
        self.ranks: dict[tuple[int, int], int] = {}
        for rank, (a, b) in enumerate(self.merges):
            new_id = self.n_special + 256 + rank
            self.vocab[new_id] = self.vocab[a] + self.vocab[b]
            self.ranks[(a, b)] = rank
        self._cache: dict[str, list[int]] = {}

    # ---- properties ------------------------------------------------------
    @property
    def vocab_size(self) -> int:
        return self.n_special + 256 + len(self.merges)

    def token_id(self, token: str) -> int:
        return self.special_ids[token]

    @property
    def pad_id(self) -> int:
        return self.special_ids["<|pad|>"]

    @property
    def bos_id(self) -> int:
        return self.special_ids["<|bos|>"]

    @property
    def eos_id(self) -> int:
        return self.special_ids["<|eos|>"]

    @property
    def end_id(self) -> int:
        return self.special_ids["<|end|>"]

    # ---- encoding --------------------------------------------------------
    def _bpe(self, piece: str) -> list[int]:
        cached = self._cache.get(piece)
        if cached is not None:
            return cached
        ids = [self.n_special + b for b in piece.encode("utf-8")]
        while len(ids) >= 2:
            best_rank, best_i = None, -1
            for i in range(len(ids) - 1):
                r = self.ranks.get((ids[i], ids[i + 1]))
                if r is not None and (best_rank is None or r < best_rank):
                    best_rank, best_i = r, i
            if best_rank is None:
                break
            new_id = self.n_special + 256 + best_rank
            pair = (ids[best_i], ids[best_i + 1])
            out, i = [], 0
            while i < len(ids):
                if i < len(ids) - 1 and (ids[i], ids[i + 1]) == pair:
                    out.append(new_id)
                    i += 2
                else:
                    out.append(ids[i])
                    i += 1
            ids = out
        if len(self._cache) < 200_000:
            self._cache[piece] = ids
        return ids

    def encode(self, text: str, allow_special: bool = False) -> list[int]:
        ids: list[int] = []
        chunks = self._special_re.split(text) if allow_special else [text]
        for chunk in chunks:
            if not chunk:
                continue
            if allow_special and chunk in self.special_ids:
                ids.append(self.special_ids[chunk])
                continue
            for piece in self._re.findall(chunk):
                ids.extend(self._bpe(piece))
        return ids

    def decode_bytes(self, ids: Iterable[int], skip_special: bool = True) -> bytes:
        out = bytearray()
        for i in ids:
            if i < self.n_special and skip_special:
                continue
            out += self.vocab.get(int(i), b"")
        return bytes(out)

    def decode(self, ids: Iterable[int], skip_special: bool = True) -> str:
        return self.decode_bytes(ids, skip_special).decode("utf-8", errors="replace")

    # ---- persistence -----------------------------------------------------
    def to_dict(self) -> dict:
        return {"type": "moth-bpe", "version": 1, "pattern": self.pattern,
                "special_tokens": self.special_tokens, "merges": [list(m) for m in self.merges]}

    def save(self, path: Path | str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path | str) -> "Tokenizer":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if d.get("type") != "moth-bpe":
            raise ValueError(f"{path} is not a MOTH tokenizer file")
        return cls([tuple(m) for m in d["merges"]], d["special_tokens"], d["pattern"])

    def fingerprint(self) -> str:
        """Stable hash; models and contributions must use the same tokenizer."""
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


def train_bpe(
    texts: Iterable[str],
    vocab_size: int,
    special_tokens: list[str] | None = None,
    min_frequency: int = 2,
    progress: Callable[[int, int], None] | None = None,
    max_unique_words: int = 2_000_000,
) -> Tokenizer:
    """Learn BPE merges from an iterable of documents."""
    specials = list(special_tokens or SPECIAL_TOKENS)
    n_special = len(specials)
    target_merges = vocab_size - n_special - 256
    if target_merges < 0:
        raise ValueError(f"vocab_size must be at least {n_special + 256}")
    rx = re.compile(PATTERN)
    special_rx = re.compile("|".join(re.escape(t) for t in specials))

    word_freq: Counter[str] = Counter()
    for text in texts:
        text = special_rx.sub(" ", text)  # specials never appear inside learned tokens
        word_freq.update(rx.findall(text))
        if len(word_freq) > max_unique_words:  # bound memory: drop rare pieces
            word_freq = Counter(dict(word_freq.most_common(max_unique_words // 2)))

    words: list[list[int]] = []
    freqs: list[int] = []
    for w, f in word_freq.items():
        words.append([n_special + b for b in w.encode("utf-8")])
        freqs.append(f)

    pair_counts: defaultdict[tuple[int, int], int] = defaultdict(int)
    where: defaultdict[tuple[int, int], set[int]] = defaultdict(set)
    for wi, w in enumerate(words):
        for a, b in zip(w, w[1:]):
            pair_counts[(a, b)] += freqs[wi]
            where[(a, b)].add(wi)

    # Max-heap with lazy invalidation; ties broken by pair ids for determinism.
    heap = [(-c, p) for p, c in pair_counts.items()]
    heapq.heapify(heap)
    merges: list[tuple[int, int]] = []

    while len(merges) < target_merges and heap:
        neg, pair = heapq.heappop(heap)
        count = pair_counts.get(pair, 0)
        if count != -neg:
            if count > 0:
                heapq.heappush(heap, (-count, pair))
            continue
        if count < min_frequency:
            break
        new_id = n_special + 256 + len(merges)
        merges.append(pair)
        changed: dict[tuple[int, int], int] = {}
        for wi in list(where[pair]):
            w, f = words[wi], freqs[wi]
            # remove old pair counts for this word
            for a, b in zip(w, w[1:]):
                pair_counts[(a, b)] -= f
                changed[(a, b)] = pair_counts[(a, b)]
            out, i = [], 0
            while i < len(w):
                if i < len(w) - 1 and w[i] == pair[0] and w[i + 1] == pair[1]:
                    out.append(new_id)
                    i += 2
                else:
                    out.append(w[i])
                    i += 1
            words[wi] = out
            for a, b in zip(out, out[1:]):
                pair_counts[(a, b)] += f
                where[(a, b)].add(wi)
                changed[(a, b)] = pair_counts[(a, b)]
        pair_counts.pop(pair, None)
        where.pop(pair, None)
        for p, c in changed.items():
            if c > 0:
                heapq.heappush(heap, (-c, p))
            else:
                pair_counts.pop(p, None)
        if progress and (len(merges) % 100 == 0 or len(merges) == target_merges):
            progress(len(merges), target_merges)
    return Tokenizer(merges, specials)
