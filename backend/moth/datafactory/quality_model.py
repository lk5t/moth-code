"""Learned text quality (1.0): MOTH learns what good text looks like and drops the weakest web text.

The rule-based score in ``clean.quality`` catches obvious junk (too short, not prose, repetitive). Large
web collections also contain text that passes those rules but teaches little: spam, boilerplate, lists of
links, keyword stuffing. Following the approach of FineWeb-Edu and DCLM classifiers, but small and fully
local, each build:

1. counts hashed word pairs in a sample of **reference** text — the curated textbooks, stories, Wikipedia and
   hand-written conversations — and in a sample of the **web** text to be filtered;
2. scores every web record by the average log-likelihood ratio of its word pairs (how much more it reads like
   the reference than like average web text);
3. drops the lowest-scoring ``drop`` share (15 % by default) of each web source, measured on its own sample.

Curated and generated sources are never filtered by it. The score is kept on every record and reported per
source, so its effect is visible in the build's manifest.
"""

from __future__ import annotations

import math
import re
import zlib
from typing import Iterable

import numpy as np

REFERENCE = {"tinystories", "tinystories-full", "simple-wikipedia", "cosmopedia-stories", "cosmopedia-textbooks",
             "cosmopedia-math", "oasst1", "oasst2", "dolly-15k", "smoltalk-magpie", "smoltalk-skills"}
FILTERED = {"fineweb-edu", "cosmopedia-web"}
BUCKETS = 1 << 20
WORD = re.compile(r"[a-z']+")


def _pairs(text: str) -> np.ndarray:
    w = WORD.findall(text.lower()[:20_000])
    if len(w) < 2:
        return np.zeros(0, dtype=np.int64)
    h = np.array([zlib.crc32(x.encode()) for x in w], dtype=np.int64)  # stable across runs
    return ((h[:-1] * 1_000_003) ^ h[1:]) % BUCKETS


class QualityModel:
    def __init__(self) -> None:
        self.ref = np.zeros(BUCKETS, dtype=np.float32)
        self.bg = np.zeros(BUCKETS, dtype=np.float32)
        self.llr: np.ndarray | None = None

    def add(self, text: str, reference: bool) -> None:
        p = _pairs(text)
        if p.size:
            np.add.at(self.ref if reference else self.bg, p, 1.0)

    def fit(self) -> "QualityModel":
        a = 0.5  # add-a smoothing
        pr = (self.ref + a) / (self.ref.sum() + a * BUCKETS)
        pb = (self.bg + a) / (self.bg.sum() + a * BUCKETS)
        self.llr = np.log(pr / pb).astype(np.float32)
        return self

    @property
    def ready(self) -> bool:
        return self.llr is not None and self.ref.sum() > 1000 and self.bg.sum() > 1000

    def score(self, text: str) -> float:
        """Higher reads more like the reference text (0 = like average web text)."""
        if self.llr is None:
            return 0.0
        p = _pairs(text)
        return float(self.llr[p].mean()) if p.size else -math.inf


def threshold(scores: Iterable[float], drop: float) -> float:
    """The score below which the lowest ``drop`` share of a sample falls."""
    s = sorted(x for x in scores if math.isfinite(x))
    if not s or drop <= 0:
        return -math.inf
    return s[min(len(s) - 1, int(len(s) * drop))]
