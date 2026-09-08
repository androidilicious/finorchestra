"""Performance metrics that are hard to fool.

- Sharpe on excess returns over the cash ETF.
- Deflated Sharpe ratio (Bailey & Lopez de Prado 2014): probability that the observed Sharpe beats the
  expected maximum Sharpe from N independent trials with no skill, accounting for skew and kurtosis.
- Cost curve: net Sharpe at several one-way transaction costs in basis points.
- Block bootstrap of the Sharpe *difference* between two strategies (paired, same dates).
- Return attribution: regress weekly excess returns on ETF-built factors; alpha = residual mean.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

WEEKS = 52.0


def ann_return(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return float("nan")
    return float((1 + r).prod() ** (WEEKS / len(r)) - 1)


def ann_vol(r: pd.Series) -> float:
    return float(r.dropna().std(ddof=1) * np.sqrt(WEEKS))


def sharpe(excess: pd.Series) -> float:
    e = excess.dropna()
    sd = e.std(ddof=1)
    if len(e) < 10 or sd == 0 or not np.isfinite(sd):
        return float("nan")
    return float(e.mean() / sd * np.sqrt(WEEKS))


def max_drawdown(r: pd.Series) -> float:
    wealth = (1 + r.fillna(0)).cumprod()
    peak = wealth.cummax()
    return float((wealth / peak - 1).min())


def turnover_series(weights: pd.DataFrame, cash: str | None = None) -> pd.Series:
    """One-way turnover per rebalance: 0.5 * sum |w_t - w_{t-1}|.

    The first row is the trade that sets the book up. With `cash` given, the pre-inception book is 100% cash, so the
    initial one-way turnover is 1 - w_0[cash]; without it, the book starts empty and the initial turnover is
    0.5 * sum |w_0|. (`sum(axis=1)` skips NaN, so the first diff row must be set explicitly.)
    """
    d = 0.5 * weights.diff().abs().sum(axis=1, min_count=1)
    w0 = weights.iloc[0].fillna(0.0)
    if cash is not None and cash in weights.columns:
        first = float(1.0 - w0[cash])
    else:
        first = float(0.5 * w0.abs().sum())
    d.iloc[0] = first
    return d


def net_returns(gross: pd.Series, turnover: pd.Series, cost_bps: float) -> pd.Series:
    """Costs are charged on the turnover executed at the start of each holding week."""
    return gross - turnover.reindex(gross.index).fillna(0.0) * cost_bps / 1e4


def deflated_sharpe(excess: pd.Series, n_trials: int, sr_var_across_trials: float | None = None, sr_dispersion_annual: float = 0.5) -> dict:
    """DSR = Prob[SR > SR0], SR0 = expected max Sharpe of n_trials skill-less strategies (Bailey & Lopez de Prado 2014).

    SR0 needs the variance of Sharpe ratios across the trials. The paper estimates it from the trials themselves; with
    a handful of declared variants that estimate is meaningless, so by default an *assumed* annual dispersion
    (`sr_dispersion_annual`, converted to per-period units) is used and disclosed in the report. Pass
    `sr_var_across_trials` (per-period variance) to use an empirical value instead. All internal quantities are per period.
    """
    e = excess.dropna().values
    T = len(e)
    if T < 20:
        return {"sharpe_annual": float("nan"), "deflated_sharpe_prob": float("nan"), "sr0_annual": float("nan")}
    sr = e.mean() / e.std(ddof=1)
    skew = float(stats.skew(e))
    kurt = float(stats.kurtosis(e, fisher=False))
    v = sr_var_across_trials if sr_var_across_trials is not None else (sr_dispersion_annual / np.sqrt(WEEKS)) ** 2
    n = max(int(n_trials), 1)
    emc = 0.5772156649
    if n == 1:
        sr0 = 0.0
    else:
        z1 = stats.norm.ppf(1 - 1.0 / n)
        z2 = stats.norm.ppf(1 - 1.0 / (n * np.e))
        sr0 = np.sqrt(v) * ((1 - emc) * z1 + emc * z2)
    num = (sr - sr0) * np.sqrt(T - 1)
    den = np.sqrt(max(1 - skew * sr + (kurt - 1) / 4 * sr**2, 1e-9))
    psr = float(stats.norm.cdf(num / den))
    return {
        "sharpe_annual": float(sr * np.sqrt(WEEKS)),
        "sr0_annual": float(sr0 * np.sqrt(WEEKS)),
        "deflated_sharpe_prob": psr,
        "n_trials": n,
        "sr_dispersion_annual_assumed": None if sr_var_across_trials is not None else sr_dispersion_annual,
        "skew": skew,
        "kurtosis": kurt,
        "T": T,
    }


def block_bootstrap_sharpe_diff(a: pd.Series, b: pd.Series, block: int = 8, draws: int = 2000, seed: int = 7) -> dict:
    """Paired circular (fixed-length, wrap-around) block bootstrap for Sharpe(a) - Sharpe(b).

    Both series are resampled with the same block indices, so the difference is paired. The two-sided p-value for
    H0: diff = 0 is the share of the centred bootstrap distribution at least as far from zero as the observed difference.
    """
    df = pd.concat([a, b], axis=1).dropna()
    x, y = df.iloc[:, 0].values, df.iloc[:, 1].values
    T = len(x)
    if T < 30:
        return {"diff": float("nan"), "p_value": float("nan"), "ci95": [float("nan"), float("nan")]}
    rng = np.random.default_rng(seed)

    def sr(v):
        s = v.std(ddof=1)
        return v.mean() / s * np.sqrt(WEEKS) if s > 0 else 0.0

    obs = sr(x) - sr(y)
    diffs = np.empty(draws)
    n_blocks = int(np.ceil(T / block))
    for k in range(draws):
        starts = rng.integers(0, T, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) % T for s in starts])[:T]
        diffs[k] = sr(x[idx]) - sr(y[idx])
    centered = diffs - diffs.mean()
    p = float(np.mean(np.abs(centered) >= abs(obs)))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"diff": float(obs), "p_value": p, "ci95": [float(lo), float(hi)], "draws": draws, "block": block}


@dataclass
class Attribution:
    alpha_annual: float
    alpha_t: float
    betas: dict[str, float]
    r2: float
    share_market: float
    share_style: float
    share_covariance: float
    share_residual: float

    def to_dict(self) -> dict:
        return {
            "alpha_annual": self.alpha_annual,
            "alpha_t_hac": self.alpha_t,
            "betas": self.betas,
            "r2": self.r2,
            "variance_share": {
                "market": self.share_market,
                "style": self.share_style,
                "covariance": self.share_covariance,
                "residual": self.share_residual,
            },
        }


def attribution(excess: pd.Series, factors: pd.DataFrame, market_col: str = "MKT") -> Attribution:
    """OLS with Newey-West (HAC, 4 lags) standard errors.

    Variance decomposition of the strategy's excess return y:
        var(y) = var(m) + var(s) + 2 cov(m, s) + var(e)
    with m the market-factor fit, s the fit on the other factors, e the residual. Shares are each term divided by
    var(y), so they sum to 1 and the residual share equals 1 - R^2 (population variances, intercept included).
    """
    import statsmodels.api as sm

    df = pd.concat([excess.rename("y"), factors], axis=1).dropna()
    nan = float("nan")
    if len(df) < 30:
        return Attribution(nan, nan, {}, nan, nan, nan, nan, nan)
    X = sm.add_constant(df[factors.columns])
    res = sm.OLS(df["y"], X).fit(cov_type="HAC", cov_kwds={"maxlags": 4})
    betas = {c: float(res.params[c]) for c in factors.columns}
    y = df["y"].values
    m = (res.params[market_col] * df[market_col]).values if market_col in factors.columns else np.zeros(len(df))
    style_cols = [c for c in factors.columns if c != market_col]
    s = (df[style_cols] @ res.params[style_cols]).values if style_cols else np.zeros(len(df))
    e = res.resid.values
    var_y = float(np.var(y))
    if var_y <= 0:
        return Attribution(float(res.params["const"] * WEEKS), float(res.tvalues["const"]), betas, float(res.rsquared), nan, nan, nan, nan)
    sh_m = float(np.var(m) / var_y)
    sh_s = float(np.var(s) / var_y)
    sh_c = float(2.0 * np.cov(m, s, ddof=0)[0, 1] / var_y) if len(df) > 1 else 0.0
    sh_e = float(np.var(e) / var_y)
    return Attribution(
        alpha_annual=float(res.params["const"] * WEEKS),
        alpha_t=float(res.tvalues["const"]),
        betas=betas,
        r2=float(res.rsquared),
        share_market=sh_m,
        share_style=sh_s,
        share_covariance=sh_c,
        share_residual=sh_e,
    )


def summarize(excess: pd.Series, gross: pd.Series, turnover: pd.Series, cost_grid: list[int]) -> dict:
    out = {
        "weeks": int(excess.dropna().shape[0]),
        "ann_return": ann_return(gross),
        "ann_vol": ann_vol(gross),
        "sharpe": sharpe(excess),
        "max_drawdown": max_drawdown(gross),
        "avg_one_way_turnover": float(turnover.mean()),
        "sharpe_by_cost_bps": {},
    }
    for bps in cost_grid:
        out["sharpe_by_cost_bps"][str(bps)] = sharpe(net_returns(excess, turnover, bps))
    return out
