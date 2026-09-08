"""Empirical durations estimated from data instead of a hand-typed table.

For each bond fund, duration is minus the slope of its weekly return on the weekly change in the 10-year
Treasury yield (in decimal), over the same trailing window the covariance uses. That is the textbook definition
of effective duration (price change per unit yield change), measured on the fund's own history and known at the
decision date. Non-bond funds carry zero duration by construction: duration is a bond concept, and an estimated
"duration" for gold or equities would be a correlation artefact, not interest-rate sensitivity.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BOND_KINDS = ("government_bond", "inflation_linked_bond", "corporate_bond", "cash")


def estimate_durations(weekly_returns: pd.DataFrame, weekly_yield_change: pd.Series, kinds: dict[str, str]) -> pd.Series:
    """Return a duration (years) per ticker. `weekly_yield_change` is the weekly change in the 10y yield in decimals."""
    joined = weekly_returns.join(weekly_yield_change.rename("_dy"), how="inner").dropna(subset=["_dy"])
    out = {}
    for ticker in weekly_returns.columns:
        if kinds.get(ticker) not in BOND_KINDS:
            out[ticker] = 0.0
            continue
        pair = joined[[ticker, "_dy"]].dropna()
        if len(pair) < 26 or float(pair["_dy"].var()) <= 0:
            out[ticker] = 0.0
            continue
        x = pair["_dy"].values
        y = pair[ticker].values
        beta = float(np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1))
        out[ticker] = max(0.0, -beta)  # a negative estimate for a bond fund is noise, not negative duration
    return pd.Series(out, index=list(weekly_returns.columns), dtype=float)
