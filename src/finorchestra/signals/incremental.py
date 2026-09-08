"""Incremental information test: does our Fed-text signal add anything beyond the baseline signals?

For each target ETF and horizon h, regress the forward h-week excess return on
    baseline  : theme z-scores + EPU z + GPR z
    augmented : baseline + the Fed-text features (stance, stance change, novelty)
and report the change in adjusted R^2 and the HAC t-statistic on the added terms. Also a simple lead-lag
check: correlation of the signal at t with forward returns at t+h versus backward returns.

Everything is computed on the weekly decision-date panel produced by the backtest, so it inherits the same
point-in-time discipline. Overlapping horizons make the HAC correction (lags = h) necessary.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import Config

BASE_COLS = ["theme_growth", "theme_inflation", "theme_policy", "theme_financial", "tiz_epu", "tiz_gpr"]
OUR_COLS = ["fed_stance", "fed_stance_change", "fed_novelty"]


def _ols_hac(y: pd.Series, X: pd.DataFrame, lags: int):
    import statsmodels.api as sm

    Xc = sm.add_constant(X)
    return sm.OLS(y, Xc).fit(cov_type="HAC", cov_kwds={"maxlags": max(1, lags)})


def incremental_test(panel: pd.DataFrame, weekly_excess: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """panel: indexed by decision date with signal columns; weekly_excess: weekly ETF excess returns."""
    rows = []
    base = [c for c in BASE_COLS if c in panel.columns]
    ours = [c for c in OUR_COLS if c in panel.columns]
    if not base or not ours:
        return pd.DataFrame()
    for target in cfg.incremental_test.targets:
        if target not in weekly_excess.columns:
            continue
        for h in cfg.incremental_test.horizons_weeks:
            fwd = weekly_excess[target].rolling(h).sum().shift(-h)  # sum of the next h weekly excess returns
            fwd = fwd.reindex(panel.index, method="nearest", tolerance=pd.Timedelta(days=3))
            df = pd.concat([fwd.rename("y"), panel[base + ours]], axis=1).dropna()
            if len(df) < 60:
                continue
            m0 = _ols_hac(df["y"], df[base], h)
            m1 = _ols_hac(df["y"], df[base + ours], h)
            back = weekly_excess[target].rolling(h).sum().reindex(panel.index, method="nearest", tolerance=pd.Timedelta(days=3))
            lead = float(np.corrcoef(df[ours[0]], df["y"])[0, 1])
            lag_df = pd.concat([panel[ours[0]], back], axis=1).dropna()
            lag = float(np.corrcoef(lag_df.iloc[:, 0], lag_df.iloc[:, 1])[0, 1]) if len(lag_df) > 30 else float("nan")
            rows.append(
                {
                    "target": target,
                    "horizon_weeks": h,
                    "n": len(df),
                    "adj_r2_baseline": float(m0.rsquared_adj),
                    "adj_r2_augmented": float(m1.rsquared_adj),
                    "delta_adj_r2": float(m1.rsquared_adj - m0.rsquared_adj),
                    **{f"t_{c}": float(m1.tvalues[c]) for c in ours},
                    **{f"beta_{c}": float(m1.params[c]) for c in ours},
                    "corr_signal_vs_forward": lead,
                    "corr_signal_vs_backward": lag,
                }
            )
    return pd.DataFrame(rows)
