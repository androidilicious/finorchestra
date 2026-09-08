"""ETF prices (adjusted close) with a local cache, plus weekly return construction.

Prices are market-determined and never revised, so a price dated D is available at the close of D.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from ..config import Config
from ..utils import LOG, ensure_dir


class MarketStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = ensure_dir(cfg.raw_dir / "market")
        self.path: Path = self.dir / "adj_close.csv"
        self.prices: pd.DataFrame | None = None

    def pull(self, force: bool = False) -> pd.DataFrame:
        if self.path.exists() and not force:
            px = pd.read_csv(self.path, index_col=0, parse_dates=True)
            stale = (date.today() - px.index.max().date()).days
            if stale <= 4 and set(self.cfg.market.tickers) <= set(px.columns):
                self.prices = px[self.cfg.market.tickers]
                return self.prices
        import yfinance as yf  # imported lazily so tests without network never touch it

        tickers = self.cfg.market.tickers
        LOG.info("market: downloading %d tickers from %s", len(tickers), self.cfg.market.start)
        raw = yf.download(tickers, start=self.cfg.market.start, auto_adjust=True, progress=False, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
        close = close[tickers].dropna(how="all")
        close.index = pd.to_datetime(close.index).tz_localize(None)
        close.index.name = "date"
        close.to_csv(self.path)
        self.prices = close
        return close

    def load(self) -> MarketStore:
        if not self.path.exists():
            raise FileNotFoundError(f"{self.path} missing; run `finorchestra pull` first")
        px = pd.read_csv(self.path, index_col=0, parse_dates=True)
        self.prices = px[self.cfg.market.tickers]
        return self

    # ---------------------------------------------------------------- weekly views
    def weekly_prices(self, weekday: int = 4) -> pd.DataFrame:
        """Last available close on or before each rebalance weekday."""
        assert self.prices is not None
        px = self.prices.ffill()
        anchor = {0: "W-MON", 1: "W-TUE", 2: "W-WED", 3: "W-THU", 4: "W-FRI"}[weekday]
        return px.resample(anchor).last().dropna(how="all")

    def weekly_returns(self, weekday: int = 4) -> pd.DataFrame:
        wp = self.weekly_prices(weekday)
        return wp.pct_change().iloc[1:]

    def prices_as_of(self, d: date) -> pd.DataFrame:
        assert self.prices is not None
        return self.prices.loc[: pd.Timestamp(d)]

    def truncated(self, d: date) -> MarketStore:
        other = MarketStore.__new__(MarketStore)
        other.cfg, other.dir, other.path = self.cfg, self.dir, self.path
        other.prices = self.prices.loc[: pd.Timestamp(d)].copy()
        return other


def excess_returns(weekly: pd.DataFrame, rf_ticker: str) -> pd.DataFrame:
    rf = weekly[rf_ticker]
    return weekly.sub(rf, axis=0)


def shrunk_covariance(returns: pd.DataFrame, shrinkage: float) -> pd.DataFrame:
    """Sample covariance shrunk toward its diagonal by a given intensity; annualized from weekly data."""
    s = returns.cov() * 52.0
    target = pd.DataFrame(np.diag(np.diag(s.values)), index=s.index, columns=s.columns)
    return (1 - shrinkage) * s + shrinkage * target


def ledoit_wolf_constant_correlation(returns: pd.DataFrame, periods_per_year: float = 52.0) -> tuple[pd.DataFrame, float]:
    """Ledoit and Wolf (2004), "Honey, I shrunk the sample covariance matrix", J. Portfolio Management 30(4).

    Shrinks the sample covariance toward the constant-correlation target: every fund keeps its own sample variance,
    and every pairwise correlation is pulled toward the average correlation. The intensity is the paper's estimator
    (their appendix), clipped to [0, 1]. Returns the annualised matrix and the intensity. Unlike shrinkage toward a
    scaled identity, this never inflates the variance of a low-risk fund such as cash.
    """
    X = returns.fillna(0.0).values.astype(float)
    T, N = X.shape
    Xc = X - X.mean(axis=0)
    S = Xc.T @ Xc / T
    var = np.diag(S).copy()
    sd = np.sqrt(np.maximum(var, 1e-18))
    corr = S / np.outer(sd, sd)
    r_bar = (corr.sum() - N) / (N * (N - 1)) if N > 1 else 0.0
    F = r_bar * np.outer(sd, sd)
    np.fill_diagonal(F, var)
    # pi_hat: sum of asymptotic variances of the sample covariance entries
    Y = Xc**2
    pi_mat = (Y.T @ Y) / T - S**2
    pi_hat = float(pi_mat.sum())
    # rho_hat: sum of asymptotic covariances between sample covariance entries and target entries
    term1 = ((Xc**3).T @ Xc) / T  # theta_ii,ij summed form: E[x_i^3 x_j]
    help_ = Xc.T @ Xc / T  # = S
    help_diag = np.diag(help_)
    term2 = help_diag[:, None] * S  # s_ii * s_ij
    term3 = help_ * var[:, None]  # s_ij * s_ii (same as term2; kept for clarity of the paper's expression)
    term4 = var[:, None] * S
    theta_mat = term1 - term2 - term3 + term4  # theta_hat_{ii,ij}
    np.fill_diagonal(theta_mat, 0.0)
    rho_hat = float(np.diag(pi_mat).sum() + r_bar * ((1.0 / sd)[:, None] * sd[None, :] * theta_mat).sum())
    gamma_hat = float(np.linalg.norm(S - F, "fro") ** 2)
    kappa = (pi_hat - rho_hat) / gamma_hat if gamma_hat > 0 else 0.0
    delta = float(np.clip(kappa / T, 0.0, 1.0))
    sigma = (1 - delta) * S + delta * F
    sigma = 0.5 * (sigma + sigma.T) * periods_per_year
    return pd.DataFrame(sigma, index=returns.columns, columns=returns.columns), delta


def next_week_return(weekly_prices: pd.DataFrame, d: date) -> pd.Series | None:
    """Return from the weekly close on/before d to the following weekly close, or None at the end."""
    idx = weekly_prices.index
    pos = idx.searchsorted(pd.Timestamp(d), side="right") - 1
    if pos < 0 or pos + 1 >= len(idx):
        return None
    return weekly_prices.iloc[pos + 1] / weekly_prices.iloc[pos] - 1.0


def business_days_ago(d: date, n: int) -> date:
    cur = d
    while n > 0:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            n -= 1
    return cur
