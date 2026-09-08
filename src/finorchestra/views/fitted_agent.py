"""The fitted formula agent: a past-only ridge regression from signal features to forward excess returns.

It replaces the first version's hand-written loading table and regime multipliers. At each decision date it
refits, per asset, a ridge regression of the next `horizon_weeks` weeks of excess return on the feature row
(theme composites and Fed-text features), using only decision dates whose forward window had closed by the
decision date. The ridge penalty is chosen by leave-one-out cross-validation over a small grid. Confidence is
the probability, under the fit's own residual spread, that the predicted sign is right, rescaled to [0, 1]:
    confidence = 2 * Phi(|prediction| / residual_sd) - 1.
Nothing here is typed in except the horizon, the feature list, the penalty grid and the view ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt

import numpy as np
import pandas as pd

from ..config import Config
from ..signals.regime import RegimeEstimate
from .schema import View, ViewSet


def _phi(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


@dataclass
class FitDiagnostics:
    n_train: int
    alpha: float
    r2: float
    residual_sd: float


def forward_targets(weekly_ret: pd.DataFrame, cash: str, horizon: int) -> pd.DataFrame:
    """Sum of the next `horizon` weekly excess returns after each Friday t, indexed by t (NaN where incomplete)."""
    ex = weekly_ret.sub(weekly_ret[cash], axis=0)
    fwd = ex.rolling(horizon).sum().shift(-horizon)
    return fwd


def _fit_one(X: np.ndarray, y: np.ndarray, x_now: np.ndarray, alphas: list[float]) -> tuple[float, np.ndarray, FitDiagnostics]:
    from sklearn.linear_model import RidgeCV

    mu, sd = X.mean(axis=0), X.std(axis=0, ddof=1)
    sd = np.where(sd > 1e-12, sd, 1.0)
    Z = (X - mu) / sd
    z_now = (x_now - mu) / sd
    model = RidgeCV(alphas=np.array(alphas, dtype=float), fit_intercept=True).fit(Z, y)
    pred = float(model.predict(z_now.reshape(1, -1))[0])
    resid = y - model.predict(Z)
    ss_res = float((resid**2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1.0
    diag = FitDiagnostics(n_train=len(y), alpha=float(model.alpha_), r2=1.0 - ss_res / ss_tot, residual_sd=float(resid.std(ddof=1)) if len(y) > 2 else float("nan"))
    contrib = model.coef_ * z_now  # per-feature contribution to the prediction, in return units
    return pred, contrib, diag


def fitted_views(
    cfg: Config,
    history: pd.DataFrame,
    weekly_ret: pd.DataFrame,
    d: pd.Timestamp,
    current: dict[str, float],
    regime: RegimeEstimate,
) -> ViewSet:
    """`history`: feature rows for decision dates strictly before `d` (index = decision date, columns include the
    configured features). `weekly_ret`: Friday-to-Friday total returns known at `d` (last row <= d)."""
    fc = cfg.fitted_agent
    cash = cfg.market.risk_free_ticker
    d = pd.Timestamp(d)
    regime_line = f"Fitted agent: {regime.label} (growth {regime.growth:+.2f}, inflation {regime.inflation:+.2f})"
    if history is None or history.empty or not isinstance(history.index, pd.DatetimeIndex):
        return ViewSet(regime_assessment=regime_line + "; no feature history", views=[View(asset=cash, direction="neutral", expected_excess_return_annual=0.0, confidence=0.3, evidence=["no past feature history supplied; no fitted view"])], rationale="Past-only ridge regression needs a feature history; none was available for this decision.").normalized()
    feats = [f for f in fc.features if f in history.columns and f in current]
    hist = history.loc[history.index < d, feats].dropna()
    fwd = forward_targets(weekly_ret.loc[:d], cash, fc.horizon_weeks)
    # a training row t is usable only if its forward window closed by d: t + horizon weeks <= d
    usable = hist.index[hist.index + pd.Timedelta(weeks=fc.horizon_weeks) <= d]
    hist = hist.loc[usable]
    fwd = fwd.reindex(hist.index)
    views: list[View] = []
    x_now = np.array([float(current[f]) for f in feats], dtype=float)
    n_ok = 0
    for asset in cfg.market.tickers:
        if asset == cash or asset not in fwd.columns:
            continue
        y = fwd[asset]
        mask = y.notna() & np.isfinite(hist.values).all(axis=1)
        if int(mask.sum()) < fc.min_train_weeks or not feats:
            continue
        pred_h, contrib, diag = _fit_one(hist.values[mask.values], y.values[mask.values], x_now, fc.ridge_alphas)
        n_ok += 1
        if not np.isfinite(diag.residual_sd) or diag.residual_sd <= 0:
            continue
        conf = 2.0 * _phi(abs(pred_h) / diag.residual_sd) - 1.0
        q_annual = pred_h * 52.0 / fc.horizon_weeks
        order = np.argsort(-np.abs(contrib))[:2]
        evidence = [f"{feats[i]} = {x_now[i]:+.2f} contributes {contrib[i] * 52.0 / fc.horizon_weeks:+.2%}/yr" for i in order]
        evidence.append(f"ridge fit: {diag.n_train} weeks, alpha {diag.alpha:g}, R² {diag.r2:.3f}, residual sd {diag.residual_sd:.2%} per {fc.horizon_weeks}w")
        views.append(
            View(
                asset=asset,
                direction="overweight" if q_annual > 0 else "underweight",
                expected_excess_return_annual=round(float(np.clip(q_annual, -0.15, 0.15)), 4),
                confidence=round(float(np.clip(conf, 0.0, 1.0)), 3),
                evidence=evidence,
            )
        )
    views.sort(key=lambda v: -v.confidence)
    views = views[: fc.max_views]
    if not views:
        views = [View(asset=cash, direction="neutral", expected_excess_return_annual=0.0, confidence=0.3, evidence=[f"fewer than {fc.min_train_weeks} usable training weeks; no fitted view"])]
    return ViewSet(
        regime_assessment=f"Fitted agent: {regime.label} (growth {regime.growth:+.2f}, inflation {regime.inflation:+.2f}); {n_ok} assets fitted on {len(hist)} past weeks",
        views=views,
        rationale=f"Past-only ridge regression of {fc.horizon_weeks}-week forward excess returns on {len(feats)} signal features, refit at this date; confidence is the fit's own probability that the sign is right.",
    ).normalized()
