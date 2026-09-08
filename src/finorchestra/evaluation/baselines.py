"""Passive yardsticks that form no views.

    benchmark    the data-derived neutral portfolio (allocation/benchmark.py) for that date: the same portfolio the
                 Black-Litterman prior and every mandate limit are anchored to. Holding it is "no opinion".
    sixty_forty  60% SPY / 40% IEF, static. The familiar retail mix; it ignores the mandate and is shown only as a
                 reference point everyone recognises.
"""

from __future__ import annotations

import pandas as pd

from ..config import Config


def sixty_forty_weights(cfg: Config) -> pd.Series:
    w = pd.Series(0.0, index=cfg.market.tickers)
    w["SPY"] = 0.60
    w["IEF"] = 0.40
    return w


def baseline_weights(name: str, cfg: Config, benchmark: pd.Series) -> pd.Series:
    if name == "benchmark":
        return benchmark.reindex(cfg.market.tickers).fillna(0.0)
    if name == "sixty_forty":
        return sixty_forty_weights(cfg)
    raise KeyError(f"unknown baseline {name!r}")
