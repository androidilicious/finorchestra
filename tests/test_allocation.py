from __future__ import annotations

import numpy as np
import pandas as pd

from finorchestra.allocation.benchmark import benchmark_weights
from finorchestra.allocation.black_litterman import black_litterman
from finorchestra.allocation.constraints import ConstraintSet
from finorchestra.allocation.engine import allocate
from finorchestra.allocation.optimizer import optimize, view_implied_portfolio
from finorchestra.views.schema import View, ViewSet


def _mkt(cfg, sigma=None):
    if sigma is None:
        return pd.Series(0.1, index=cfg.market.tickers)
    return benchmark_weights(sigma, cfg.market.risk_free_ticker, cfg.allocation.benchmark)


def _dur(cfg):
    return pd.Series({"SPY": 0.0, "TLT": 16.0, "IEF": 7.5, "TIP": 6.3, "LQD": 7.9, "HYG": 2.8, "GLD": 0.0, "DBC": 0.0, "UUP": 0.0, "BIL": 0.1}).reindex(cfg.market.tickers).fillna(0.0)


def _cs(cfg, sigma):
    return ConstraintSet.from_state(cfg, _mkt(cfg, sigma), sigma, _dur(cfg))


def test_black_litterman_no_views_returns_prior(cfg, sigma):
    vs = ViewSet(views=[View(asset="BIL", direction="neutral", expected_excess_return_annual=0.0, confidence=0.5)])
    res = black_litterman(sigma, _mkt(cfg, sigma), vs, delta=3.0)
    assert np.allclose(res.prior.values, res.posterior.values)


def test_black_litterman_confident_view_pulls_posterior_toward_q(cfg, sigma):
    w = _mkt(cfg, sigma)
    weak = ViewSet(views=[View(asset="TLT", direction="overweight", expected_excess_return_annual=0.08, confidence=0.1)])
    strong = ViewSet(views=[View(asset="TLT", direction="overweight", expected_excess_return_annual=0.08, confidence=0.95)])
    r_weak = black_litterman(sigma, w, weak, 3.0)
    r_strong = black_litterman(sigma, w, strong, 3.0)
    prior = r_weak.prior["TLT"]
    assert prior < r_weak.posterior["TLT"] < r_strong.posterior["TLT"] <= 0.08 + 1e-6
    assert r_strong.implied_weights["TLT"] > r_weak.implied_weights["TLT"]


def test_optimizer_respects_every_constraint(cfg, sigma):
    cs = _cs(cfg, sigma)
    mu = pd.Series(0.0, index=cfg.market.tickers)
    mu["TLT"] = 0.20  # an extreme view that would blow through the limits if unconstrained
    mu["SPY"] = 0.15
    w_prev = _mkt(cfg, sigma)
    res = optimize(mu, sigma, cs, delta=3.0, w_prev=w_prev, turnover_penalty=0.002, w_market=w_prev)
    assert res.status in ("optimal", "optimal_inaccurate")
    v = cs.check(res.weights, sigma, w_prev)
    assert v == [], [x.message for x in v]
    assert abs(res.weights.sum() - 1) < 1e-4


def test_critic_names_violations_plainly(cfg, sigma):
    cs = _cs(cfg, sigma)
    w = pd.Series(0.0, index=cfg.market.tickers)
    w["TLT"] = 0.6
    w["SPY"] = 0.4
    v = cs.check(w, sigma)
    rules = {x.rule for x in v}
    assert "max_weight:TLT" in rules and "max_weight:SPY" in rules and "duration_hi" in rules
    assert any("too long" in x.message for x in v)
    assert any("active-band" in x.message for x in v)


def test_aggressive_view_binds_constraints_but_final_is_feasible(cfg, sigma):
    vs = ViewSet(views=[View(asset="TLT", direction="overweight", expected_excess_return_annual=0.10, confidence=0.9)])
    out = allocate(cfg, vs, sigma, None, _mkt(cfg, sigma), _dur(cfg))
    assert out.binding_before, "an aggressive long-bond view should pin the TLT cap or the duration ceiling"
    assert any(r.rule in ("cap:TLT", "duration_ceiling") for r in out.binding_before)
    assert out.final_violations == []


def test_no_views_market_portfolio_binds_nothing(cfg, sigma):
    vs = ViewSet(views=[View(asset="BIL", direction="neutral", expected_excess_return_annual=0.0, confidence=0.5)])
    out = allocate(cfg, vs, sigma, None, _mkt(cfg, sigma), _dur(cfg))
    assert out.binding_before == [], [v.message for v in out.binding_before]


def test_feedback_loop_calls_reviser_and_records_history(cfg, sigma):
    calls = []

    def reviser(vs: ViewSet, violations: list[str]) -> ViewSet:
        calls.append(violations)
        return ViewSet(views=[v.model_copy(update={"expected_excess_return_annual": v.expected_excess_return_annual * 0.2, "confidence": 0.3}) for v in vs.views])

    vs = ViewSet(views=[View(asset="TLT", direction="overweight", expected_excess_return_annual=0.10, confidence=0.9)])
    out = allocate(cfg, vs, sigma, None, _mkt(cfg, sigma), _dur(cfg), reviser=reviser, rounds=2)
    assert out.feedback_rounds >= 1 and len(calls) == out.feedback_rounds
    assert out.revision_history[0]["violations_presented"] and out.revision_history[0]["rules_presented"]
    assert out.views.views[0].expected_excess_return_annual < 0.10
    assert out.final_violations == []
    assert len(out.binding_after) <= len(out.binding_before)


def test_view_implied_is_long_only_and_budgeted(cfg, sigma):
    cs = _cs(cfg, sigma)
    mu = pd.Series(0.01, index=cfg.market.tickers)
    w = view_implied_portfolio(mu, sigma, cs, 3.0)
    assert (w >= -1e-6).all() and abs(w.sum() - 1) < 1e-4
