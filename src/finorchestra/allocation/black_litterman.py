"""Black-Litterman: market-implied prior + confidence-weighted views -> posterior expected excess returns.

prior      pi = delta * Sigma * w_mkt
views      P (k x n one-hot rows), Q (k), Omega = diag((1/c_i - 1) * tau * (P Sigma P')_ii)
posterior  mu = [ (tau Sigma)^-1 + P' Omega^-1 P ]^-1 [ (tau Sigma)^-1 pi + P' Omega^-1 Q ]

For a single-asset view the posterior moves a fraction c of the way from the prior toward Q (Omega -> 0 as c -> 1).
Confidence is clamped to [0.02, 0.98], so a view can never fully pin the posterior; confidence -> 0 has no effect.
The implied (unconstrained) portfolio is w* = (1/delta) Sigma^-1 mu; it is what the view set "wants" before
any institutional rule is applied, and it is what the critic inspects in the feedback loop.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..views.schema import ViewSet


@dataclass
class BLResult:
    prior: pd.Series
    posterior: pd.Series
    implied_weights: pd.Series  # unconstrained, sums to 1 (may be negative)
    P: np.ndarray
    Q: np.ndarray
    omega_diag: np.ndarray

    def to_dict(self) -> dict:
        return {
            "prior_excess_return": self.prior.round(4).to_dict(),
            "posterior_excess_return": self.posterior.round(4).to_dict(),
            "implied_unconstrained_weights": self.implied_weights.round(4).to_dict(),
        }


def market_prior(sigma: pd.DataFrame, w_mkt: pd.Series, delta: float) -> pd.Series:
    return pd.Series(delta * sigma.values @ w_mkt.reindex(sigma.index).values, index=sigma.index)


def implied_weights_cash_residual(mu: pd.Series, pi: pd.Series, sigma: pd.DataFrame, w_mkt: pd.Series, delta: float, cash: str | None) -> pd.Series:
    """Market portfolio plus the mean-variance tilt implied by (mu - pi) on risky assets; cash is the residual.

    Inverting the full covariance would let the near-zero variance of the cash asset dominate the tilt, so cash is
    treated as the numeraire, exactly as in the excess-return formulation of mean-variance.
    """
    assets = list(sigma.index)
    risky = [a for a in assets if a != cash]
    S = sigma.loc[risky, risky].values
    S = 0.5 * (S + S.T)
    d_mu = (mu - pi).reindex(risky).values
    tilt = np.linalg.solve(S + 1e-10 * np.eye(len(risky)), d_mu) / delta
    w = w_mkt.reindex(assets).astype(float).copy()
    w.loc[risky] = w.loc[risky].values + tilt
    if cash in assets:
        w.loc[cash] = 1.0 - w.loc[risky].sum()
    return w


def black_litterman(sigma: pd.DataFrame, w_mkt: pd.Series, views: ViewSet, delta: float, tau: float = 1.0, cash: str | None = None) -> BLResult:
    """`tau` is kept for the textbook form only. With Omega = (1/c - 1) * tau * (P Sigma P')_ii, tau multiplies both
    precision terms of the posterior and cancels exactly, so its value never changes a number; it is no longer a
    configuration option."""
    assets = list(sigma.index)
    n = len(assets)
    S = 0.5 * (sigma.values + sigma.values.T)
    # guard against a numerically singular covariance (e.g. an asset with ~zero variance)
    eig_min = float(np.linalg.eigvalsh(S).min())
    if eig_min < 1e-8:
        S = S + (1e-8 - min(eig_min, 0.0)) * np.eye(n)
    pi = delta * S @ w_mkt.reindex(assets).values

    rows, Q, conf = [], [], []
    for v in views.views:
        if v.asset not in assets or v.direction == "neutral":
            continue
        p = np.zeros(n)
        p[assets.index(v.asset)] = 1.0
        rows.append(p)
        Q.append(v.expected_excess_return_annual)
        conf.append(min(max(v.confidence, 0.02), 0.98))
    if not rows:
        mu = pi.copy()
        P = np.zeros((0, n))
        Qa = np.zeros(0)
        om = np.zeros(0)
    else:
        P = np.vstack(rows)
        Qa = np.array(Q)
        c = np.array(conf)
        pSp = np.einsum("ij,jk,ik->i", P, tau * S, P)
        om = (1.0 / c - 1.0) * pSp
        om = np.maximum(om, 1e-10)
        tS_inv = np.linalg.inv(tau * S)
        Om_inv = np.diag(1.0 / om)
        A = tS_inv + P.T @ Om_inv @ P
        b = tS_inv @ pi + P.T @ Om_inv @ Qa
        mu = np.linalg.solve(A, b)

    prior = pd.Series(pi, index=assets)
    posterior = pd.Series(mu, index=assets)
    if cash is None:
        # no numeraire given: pick the lowest-variance asset, which is what cash is in any sane universe
        cash = assets[int(np.argmin(np.diag(S)))]
    w_star = implied_weights_cash_residual(posterior, prior, sigma, w_mkt, delta, cash)
    return BLResult(prior=prior, posterior=posterior, implied_weights=w_star, P=P, Q=Qa, omega_diag=om)
