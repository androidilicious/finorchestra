"""Dated retrieval over the FOMC corpus: BM25 relevance x recency decay, hard-filtered by availability.

No document with available_from > as_of can ever be returned, because the index is built from an as-of
snapshot. Recency matters in macro: a statement from last month outranks an equally relevant one from three
years ago, so score = (1 + BM25) * 0.5 ** (age_days / halflife_days). The +1 keeps the most recent statement
retrievable even when lexical relevance is ~0.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..config import RetrievalCfg

_TOKEN = re.compile(r"[a-z][a-z\-]+")
_STOP = set(
    "the of and to in a that is for on with as at by be are from this will its it has have committee federal "
    "percent range will target funds rate reserve open market".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 2]


@dataclass
class Retrieved:
    date: date
    age_days: int
    score: float
    text: str


class DatedIndex:
    def __init__(self, docs: pd.DataFrame, as_of: date, cfg: RetrievalCfg):
        self.cfg = cfg
        self.as_of = as_of
        docs = docs.loc[docs["available_from"] <= pd.Timestamp(as_of)]
        self.dates = [d.date() for d in docs["date"]]
        self.texts = list(docs["text"])
        self.tokens = [tokenize(t) for t in self.texts]
        self.df: Counter = Counter()
        for toks in self.tokens:
            self.df.update(set(toks))
        self.n = len(self.tokens)
        self.avgdl = sum(len(t) for t in self.tokens) / max(1, self.n)

    def _bm25(self, q: list[str], toks: list[str], k1: float = 1.5, b: float = 0.75) -> float:
        tf = Counter(toks)
        dl = len(toks)
        s = 0.0
        for term in q:
            if term not in tf:
                continue
            idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            s += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * dl / max(self.avgdl, 1)))
        return s

    def search(self, query: str, top_k: int | None = None) -> list[Retrieved]:
        top_k = top_k or self.cfg.top_k
        q = tokenize(query)
        out = []
        for i, toks in enumerate(self.tokens):
            age = (self.as_of - self.dates[i]).days
            rel = self._bm25(q, toks)
            decay = 0.5 ** (age / max(1, self.cfg.recency_halflife_days))
            score = (1.0 + rel) * decay  # +1 keeps the most recent statement in play even for odd queries
            out.append(Retrieved(self.dates[i], age, score, self.texts[i][: self.cfg.max_chars_per_doc]))
        out.sort(key=lambda r: -r.score)
        return out[:top_k]

    def latest(self) -> Retrieved | None:
        if not self.dates:
            return None
        i = max(range(self.n), key=lambda k: self.dates[k])
        return Retrieved(self.dates[i], (self.as_of - self.dates[i]).days, 1.0, self.texts[i][: self.cfg.max_chars_per_doc])
