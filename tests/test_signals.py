from __future__ import annotations

import numpy as np
import pandas as pd

from finorchestra.config import DerivedCfg
from finorchestra.llm.mock import lexicon_stance
from finorchestra.signals.regime import estimate_regime
from finorchestra.signals.retrieval import DatedIndex
from finorchestra.signals.text_signal import novelty_vs_previous
from finorchestra.signals.zscores import derive, rolling_z_last


def test_rolling_z_uses_only_past_window():
    idx = pd.date_range("2000-01-01", periods=15 * 12, freq="MS")
    s = pd.Series(np.zeros(len(idx)), index=idx)
    s.iloc[-1] = 5.0  # a spike today must not inflate its own reference distribution
    s.iloc[:-1] = np.random.default_rng(0).normal(0, 1, len(idx) - 1)
    z = rolling_z_last(s, window_years=10, min_years=5, clip=10)
    hist = s.iloc[-121:-1]
    expected = (5.0 - hist.mean()) / hist.std(ddof=1)
    assert abs(z - expected) < 1e-9


def test_rolling_z_requires_history():
    idx = pd.date_range("2020-01-01", periods=24, freq="MS")
    s = pd.Series(np.arange(24, dtype=float), index=idx)
    assert rolling_z_last(s, 10, 5, 3) is None


def test_derive_transforms():
    idx = pd.date_range("2020-01-01", periods=25, freq="MS")
    s = pd.Series(100 * (1.01 ** np.arange(25)), index=idx)
    yoy = derive(s, DerivedCfg(source="x", transform="pct_change", periods=12))
    assert abs(yoy.iloc[-1] - (1.01**12 - 1)) < 1e-9
    ann = derive(s, DerivedCfg(source="x", transform="pct_change_annualized", periods=3))
    assert abs(ann.iloc[-1] - (1.01**12 - 1)) < 1e-6


def test_regime_probabilities_sum_to_one_and_label_matches():
    r = estimate_regime({"growth": 1.2, "inflation": -0.8})
    assert abs(sum(r.probabilities.values()) - 1) < 1e-3  # probabilities are rounded to 4 dp
    assert r.label == "goldilocks" and r.method == "normal_cdf_fallback"
    r2 = estimate_regime({"growth": -1.5, "inflation": 1.0})
    assert r2.label == "stagflation"


def test_regime_uses_empirical_percentiles_when_history_is_available():
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    hist = pd.DataFrame({"growth": rng.normal(0.5, 1.0, 200), "inflation": rng.normal(-0.5, 1.0, 200)})
    r = estimate_regime({"growth": 0.5, "inflation": -0.5}, hist)  # each theme sits at its own historical median
    assert r.method == "empirical"
    for p in r.probabilities.values():
        assert 0.18 < p < 0.32  # near 1/4 each when both percentiles are near one half


def test_lexicon_stance_direction():
    hawk, _ = lexicon_stance("Inflation remains elevated. The Committee anticipates that additional policy firming may be appropriate.")
    dove, _ = lexicon_stance("Downside risks to employment have increased. The Committee decided to lower the target range and will remain highly accommodative.")
    assert hawk > 0 > dove


def test_novelty_bounds():
    assert novelty_vs_previous(["the economy is growing", "the economy is growing"]) < 0.05
    assert novelty_vs_previous(["the economy is growing", "geopolitical tensions escalate sharply"]) > 0.9


def test_dated_index_never_returns_future_docs():
    docs = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-31", "2024-03-20", "2024-05-01"]),
            "text": ["inflation eased growth solid", "inflation elevated growth solid", "inflation surge growth weak"],
            "available_from": pd.to_datetime(["2024-01-31", "2024-03-20", "2024-05-01"]),
        }
    )
    from finorchestra.config import RetrievalCfg

    idx = DatedIndex(docs, pd.Timestamp("2024-04-05").date(), RetrievalCfg(top_k=5))
    hits = idx.search("inflation growth")
    assert all(h.date <= pd.Timestamp("2024-04-05").date() for h in hits)
    assert len(hits) == 2
    assert hits[0].date == pd.Timestamp("2024-03-20").date()  # recency wins on equal relevance
