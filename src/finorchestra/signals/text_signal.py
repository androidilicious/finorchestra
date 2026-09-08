"""Our own text signal from Fed communications: policy stance and novelty.

stance   in [-1, +1]: dovish ... hawkish, scored per statement by the configured LLM (or the offline lexicon).
novelty  in [0, 1]:   1 - cosine(TF-IDF) similarity to the previous statement. Old news scores near 0.
The two are passed to the fitted agent and the model as separate features; no hand-set combination of them
(the first version's stance x (0.5 + novelty) "surprise") remains.

Scores are cached per (provider, model, statement date) so a backtest scores each statement once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer

from ..config import Config
from ..llm.client import LLMClient
from ..llm.mock import lexicon_stance
from ..utils import LOG, ensure_dir
from ..views.masking import Masker
from ..views.schema import StanceResult

_SYSTEM = (
    "You are a central-bank watcher. Read the policy statement and rate its stance on a hawkish-dovish scale. "
    "+1 = strongly hawkish (leaning toward higher rates / tighter policy, worried about inflation). "
    "-1 = strongly dovish (leaning toward lower rates / easier policy, worried about growth or employment). "
    "0 = balanced. Reply with JSON only: {\"stance\": <float in [-1,1]>, \"key_phrases\": [<up to 6 short quotes>]}"
)


@dataclass
class TextSignal:
    statement_date: date | None
    days_since: int | None
    stance: float
    prev_stance: float | None
    stance_change: float
    novelty: float
    key_phrases: list[str]

    def to_dict(self) -> dict:
        return {
            "statement_date": str(self.statement_date) if self.statement_date else None,
            "days_since_statement": self.days_since,
            "fed_stance": round(self.stance, 3),
            "fed_stance_change": round(self.stance_change, 3),
            "fed_statement_novelty": round(self.novelty, 3),
            "key_phrases": self.key_phrases,
        }


class StanceScorer:
    def __init__(self, cfg: Config, client: LLMClient, masker: Masker):
        self.cfg = cfg
        self.client = client
        self.masker = masker
        use_lexicon = cfg.text_signal.provider == "lexicon" or client.cfg.provider == "mock"
        self.mode = "lexicon" if use_lexicon else f"llm:{client.cfg.model}"
        tag = "lexicon" if use_lexicon else client.cfg.model.replace("/", "_").replace(":", "_")
        self.cache_path: Path = ensure_dir(cfg.processed_dir) / f"fomc_stance_{tag}.csv"
        self.cache: dict[str, tuple[float, str]] = {}
        if self.cache_path.exists():
            df = pd.read_csv(self.cache_path)
            self.cache = {r.date: (float(r.stance), str(r.key_phrases)) for r in df.itertuples()}

    def score(self, d: date, text: str) -> tuple[float, list[str]]:
        key = str(d)
        if key in self.cache:
            s, kp = self.cache[key]
            return s, [p for p in kp.split(" | ") if p]
        if self.mode == "lexicon":
            s, phrases = lexicon_stance(text)
        else:
            msgs = [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"<<STATEMENT>>\n{self.masker.mask_text(text)}\n<<END_STATEMENT>>"},
            ]
            try:
                res = self.client.chat_json(msgs, StanceResult, task="stance")
            except Exception as e:  # noqa: BLE001 - any failure falls back, and is counted
                LOG.warning("stance scoring failed for %s: %s", d, str(e)[:120])
                res = self.client.mock_fallback(msgs, StanceResult, task="stance")
            s, phrases = float(res.stance), list(res.key_phrases)
        self.cache[key] = (s, " | ".join(phrases))
        self._flush()
        return s, phrases

    def _flush(self) -> None:
        pd.DataFrame(
            [{"date": k, "stance": v[0], "key_phrases": v[1]} for k, v in sorted(self.cache.items())]
        ).to_csv(self.cache_path, index=False)


def novelty_vs_previous(texts: list[str], ngram: tuple[int, int] = (1, 2)) -> float:
    """1 - cosine similarity between the last two documents (0 = identical, 1 = unrelated)."""
    if len(texts) < 2:
        return 0.5
    vec = TfidfVectorizer(ngram_range=ngram, stop_words="english", sublinear_tf=True)
    X = vec.fit_transform(texts[-2:])
    sim = float((X[0] @ X[1].T).toarray()[0, 0])
    return float(np.clip(1.0 - sim, 0.0, 1.0))


def build_text_signal(fomc_as_of: pd.DataFrame, as_of: date, scorer: StanceScorer, ngram=(1, 2)) -> TextSignal:
    if fomc_as_of is None or fomc_as_of.empty:
        return TextSignal(None, None, 0.0, None, 0.0, 0.5, [])
    docs = fomc_as_of.sort_values("date")
    last = docs.iloc[-1]
    d_last = last["date"].date()
    stance, phrases = scorer.score(d_last, last["text"])
    prev_stance = None
    if len(docs) >= 2:
        prev = docs.iloc[-2]
        prev_stance, _ = scorer.score(prev["date"].date(), prev["text"])
    nov = novelty_vs_previous(list(docs["text"].iloc[-2:]), ngram)
    change = stance - (prev_stance if prev_stance is not None else 0.0)
    return TextSignal(d_last, (as_of - d_last).days, stance, prev_stance, change, nov, phrases)
