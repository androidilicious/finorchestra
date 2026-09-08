"""The neutral portfolio: computed from data at each decision date, never typed in.

It is the Black-Litterman prior, the anchor for every mandate limit (active bands, risk, duration, capital), and
the passive yardstick called "benchmark" in the evaluation.

    inverse_vol   weight proportional to 1 / annual volatility over the risky funds (cash excluded), from the
                  same covariance the optimiser uses. No free parameters. A risk-balanced book that leans on no
                  return forecast; the standard "no views" allocation in the risk-parity literature.
    equal_weight  1/N over the risky funds. No parameters and no data; kept as the simplest possible alternative.

Cash is excluded from the benchmark because it is where the optimiser retreats to, not a position to be neutral
in: a benchmark that is mostly cash would make every risk-bearing view a large active bet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def benchmark_weights(sigma: pd.DataFrame, cash: str, method: str = "inverse_vol") -> pd.Series:
    assets = list(sigma.index)
    risky = [a for a in assets if a != cash]
    if method == "equal_weight":
        w = pd.Series(1.0 / len(risky), index=risky)
    elif method == "inverse_vol":
        vol = pd.Series(np.sqrt(np.diag(sigma.values)), index=assets).reindex(risky)
        vol = vol.where(vol > 0)
        inv = (1.0 / vol).fillna(0.0)
        w = inv / inv.sum() if inv.sum() > 0 else pd.Series(1.0 / len(risky), index=risky)
    else:
        raise ValueError(f"unknown benchmark method {method!r}")
    out = pd.Series(0.0, index=assets)
    out.loc[risky] = w.values
    return out
