"""Constrained mean-variance optimizer on the Black-Litterman posterior.

    maximize  mu'w - (delta/2) w'Sigma w - lambda * 0.5*||w - w_prev||_1
    subject to the typed constraint set.

The volatility cap is a second-order-cone constraint, so cvxpy routes to CLARABEL (or SCS) rather than OSQP.
If the full problem is infeasible (e.g. the turnover cap conflicts with a newly tightened rule) the solver
drops the turnover constraint and reports that it did so, then finally falls back to the market portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .constraints import ConstraintSet


@dataclass
class OptResult:
    weights: pd.Series
    status: str
    objective: float | None
    relaxed_turnover: bool = False
    fell_back_to_market: bool = False

    def to_dict(self) -> dict:
        return {
            "weights": self.weights.round(4).to_dict(),
            "status": self.status,
            "relaxed_turnover": self.relaxed_turnover,
            "fell_back_to_market": self.fell_back_to_market,
        }


def _solve(mu, S, cons, w, objective_extra=None):
    import cvxpy as cp

    obj = objective_extra
    prob = cp.Problem(cp.Maximize(obj), cons)
    for solver in ("CLARABEL", "SCS"):
        try:
            prob.solve(solver=solver, verbose=False)
        except Exception:  # noqa: BLE001
            continue
        if prob.status in ("optimal", "optimal_inaccurate") and w.value is not None:
            return prob.status, float(prob.value), np.asarray(w.value).ravel()
    return prob.status or "failed", None, None


def optimize(
    mu: pd.Series,
    sigma: pd.DataFrame,
    cs: ConstraintSet,
    delta: float,
    w_prev: pd.Series | None,
    turnover_penalty: float,
    w_market: pd.Series,
) -> OptResult:
    import cvxpy as cp

    assets = cs.assets
    m = mu.reindex(assets).values
    S = sigma.reindex(index=assets, columns=assets).values
    S = 0.5 * (S + S.T) + 1e-10 * np.eye(len(assets))
    prev = None if w_prev is None else w_prev.reindex(assets).fillna(0.0).values
    w = cp.Variable(len(assets))

    def objective(include_prev: bool):
        o = m @ w - (delta / 2) * cp.quad_form(w, cp.psd_wrap(S))
        if include_prev and prev is not None and turnover_penalty > 0:
            o = o - turnover_penalty * 0.5 * cp.norm1(w - prev)
        return o

    status, val, x = _solve(m, S, cs.cvx_constraints(w, S, prev, include_turnover=True), w, objective(True))
    if x is not None:
        return OptResult(pd.Series(np.clip(x, 0, None), index=assets), status, val)

    status, val, x = _solve(m, S, cs.cvx_constraints(w, S, prev, include_turnover=False), w, objective(True))
    if x is not None:
        return OptResult(pd.Series(np.clip(x, 0, None), index=assets), status, val, relaxed_turnover=True)

    return OptResult(w_market.reindex(assets), "infeasible", None, relaxed_turnover=True, fell_back_to_market=True)


def view_implied_portfolio(mu: pd.Series, sigma: pd.DataFrame, cs: ConstraintSet, delta: float) -> pd.Series:
    """What the views 'want' with only budget + long-only imposed. This is what the critic inspects."""
    import cvxpy as cp

    assets = cs.assets
    m = mu.reindex(assets).values
    S = sigma.reindex(index=assets, columns=assets).values
    S = 0.5 * (S + S.T) + 1e-10 * np.eye(len(assets))
    w = cp.Variable(len(assets))
    obj = m @ w - (delta / 2) * cp.quad_form(w, cp.psd_wrap(S))
    status, _, x = _solve(m, S, cs.relaxed_cvx_constraints(w), w, obj)
    if x is None:
        x = np.ones(len(assets)) / len(assets)
    return pd.Series(np.clip(x, 0, None), index=assets)
