"""Typed institutional constraints and the deterministic critic that certifies them.

Every limit is expressed relative to the data-derived neutral portfolio (see benchmark.py), so the mandate has
four parameters instead of a table of numbers: an active-weight band, a volatility allowance, a duration band and
a capital allowance, plus the turnover cap. Durations are estimated from data (duration.py); risk weights come
from the US standardised capital rule by asset kind (12 CFR 217.32 and 217.52: US government exposures and gold
bullion 0%, corporate exposures 100%, publicly traded equity 300%, all other assets 100%).

Each constraint knows how to (a) express itself to cvxpy and (b) check a numeric weight vector. The critic is
nothing more than running every check and listing the violations in plain language. No AI anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import Config

# 12 CFR 217 standardised approach, by the kind declared for each fund in configs/default.yaml
REGULATORY_RISK_WEIGHT: dict[str, float] = {
    "government_bond": 0.0,
    "inflation_linked_bond": 0.0,
    "cash": 0.0,
    "gold": 0.0,
    "corporate_bond": 1.0,
    "equity": 3.0,
    "commodity": 1.0,
    "currency": 1.0,
}


@dataclass
class Violation:
    rule: str
    value: float
    limit: float
    message: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "value": round(self.value, 4), "limit": round(self.limit, 4), "message": self.message}


@dataclass
class ConstraintSet:
    assets: list[str]
    long_only: bool
    fully_invested: bool
    benchmark: np.ndarray
    max_weight: np.ndarray
    max_vol: float
    duration: np.ndarray
    duration_lo: float
    duration_hi: float
    risk_weight: np.ndarray
    risk_budget: float
    max_turnover: float
    labels: dict[str, str]

    @classmethod
    def from_state(cls, cfg: Config, benchmark: pd.Series, sigma: pd.DataFrame, durations: pd.Series) -> ConstraintSet:
        """Build the date's constraint set from the neutral portfolio, the covariance and the estimated durations."""
        m = cfg.allocation.mandate
        assets = cfg.market.tickers
        b = benchmark.reindex(assets).fillna(0.0).values.astype(float)
        S = sigma.reindex(index=assets, columns=assets).values
        dur = durations.reindex(assets).fillna(0.0).values.astype(float)
        rw = np.array([REGULATORY_RISK_WEIGHT[k] for k in (cfg.market.kinds[a] for a in assets)], dtype=float)
        bench_vol = float(np.sqrt(max(b @ S @ b, 0.0)))
        bench_dur = float(dur @ b)
        bench_rwa = float(rw @ b)
        return cls(
            assets=assets,
            long_only=m.long_only,
            fully_invested=m.fully_invested,
            benchmark=b,
            max_weight=np.clip(b + m.active_weight_band, 0.0, 1.0),
            max_vol=bench_vol * (1.0 + m.volatility_allowance),
            duration=dur,
            duration_lo=max(0.0, bench_dur - m.duration_band_years),
            duration_hi=bench_dur + m.duration_band_years,
            risk_weight=rw,
            risk_budget=bench_rwa * (1.0 + m.capital_allowance),
            max_turnover=m.max_one_way_turnover,
            labels={a.ticker: a.label for a in cfg.market.universe},
        )

    # ------------------------------------------------------------------ cvxpy side
    def cvx_constraints(self, w, sigma: np.ndarray, w_prev: np.ndarray | None, include_turnover: bool = True) -> list:
        import cvxpy as cp

        cons = []
        if self.fully_invested:
            cons.append(cp.sum(w) == 1)
        if self.long_only:
            cons.append(w >= 0)
        cons.append(w <= self.max_weight)
        cons.append(cp.quad_form(w, cp.psd_wrap(sigma)) <= self.max_vol**2)
        cons.append(self.duration @ w >= self.duration_lo)
        cons.append(self.duration @ w <= self.duration_hi)
        cons.append(self.risk_weight @ w <= self.risk_budget)
        if include_turnover and w_prev is not None:
            cons.append(0.5 * cp.norm1(w - w_prev) <= self.max_turnover)
        return cons

    def relaxed_cvx_constraints(self, w) -> list:
        """Only budget and long-only: used to compute the 'view-implied' portfolio the critic inspects."""
        import cvxpy as cp

        cons = []
        if self.fully_invested:
            cons.append(cp.sum(w) == 1)
        if self.long_only:
            cons.append(w >= 0)
        return cons

    # ------------------------------------------------------------------ critic side
    INSTITUTIONAL = ("max_weight", "max_volatility", "duration", "risk_weight_budget")
    BUDGET_TOL = 1e-3

    def check(
        self,
        w: pd.Series,
        sigma: pd.DataFrame,
        w_prev: pd.Series | None = None,
        tol: float = 1e-4,
        rules: tuple[str, ...] | None = None,
    ) -> list[Violation]:
        """List every violated rule. `rules` restricts the check to rule-name prefixes (e.g. INSTITUTIONAL).

        `tol` applies to every rule except the budget: the fully-invested check uses BUDGET_TOL (1e-3), matching the
        feasibility gate used elsewhere in the pipeline, because solver round-off on a sum of ten weights is larger
        than on a single weight.
        """
        x = w.reindex(self.assets).fillna(0.0).values
        S = sigma.reindex(index=self.assets, columns=self.assets).values
        out: list[Violation] = []
        if self.fully_invested and abs(x.sum() - 1) > self.BUDGET_TOL:
            out.append(Violation("fully_invested", x.sum(), 1.0, f"weights sum to {x.sum():.3f}, must be 1"))
        if self.long_only and x.min() < -tol:
            i = int(np.argmin(x))
            out.append(Violation("long_only", x[i], 0.0, f"{self.assets[i]} ({self.labels[self.assets[i]]}) weight {x[i]:.1%} is negative"))
        for i, a in enumerate(self.assets):
            if x[i] > self.max_weight[i] + tol:
                out.append(Violation(f"max_weight:{a}", x[i], self.max_weight[i], f"{a} ({self.labels[a]}) weight {x[i]:.1%} exceeds its active-band limit {self.max_weight[i]:.1%} (neutral {self.benchmark[i]:.1%} plus the band)"))
        vol = float(np.sqrt(max(x @ S @ x, 0.0)))
        if vol > self.max_vol + tol:
            out.append(Violation("max_volatility", vol, self.max_vol, f"portfolio volatility {vol:.1%} exceeds limit {self.max_vol:.1%}"))
        dur = float(self.duration @ x)
        if dur > self.duration_hi + tol:
            out.append(Violation("duration_hi", dur, self.duration_hi, f"portfolio duration {dur:.1f}y is above the liability band ceiling {self.duration_hi:.1f}y (too long)"))
        if dur < self.duration_lo - tol:
            out.append(Violation("duration_lo", dur, self.duration_lo, f"portfolio duration {dur:.1f}y is below the liability band floor {self.duration_lo:.1f}y (too short)"))
        rwa = float(self.risk_weight @ x)
        if rwa > self.risk_budget + tol:
            out.append(Violation("risk_weight_budget", rwa, self.risk_budget, f"risk-weighted exposure {rwa:.2f} exceeds capital budget {self.risk_budget:.2f}"))
        if w_prev is not None:
            to = float(0.5 * np.abs(x - w_prev.reindex(self.assets).fillna(0.0).values).sum())
            if to > self.max_turnover + tol:
                out.append(Violation("max_turnover", to, self.max_turnover, f"one-way turnover {to:.1%} exceeds limit {self.max_turnover:.0%}"))
        if rules is not None:
            out = [v for v in out if v.rule.startswith(rules)]
        return out

    def binding(self, w: pd.Series, sigma: pd.DataFrame, tol_w: float = 2e-3, tol_dur: float = 0.05, tol_rel: float = 0.01) -> list[Violation]:
        """Institutional constraints the optimizer is pressed against (within tolerance), in plain language.

        These are what the feedback loop hands back to the agent: a binding cap means the views wanted more than
        the mandate allows. Turnover and budget are excluded (they are operational, not about the views).
        """
        x = w.reindex(self.assets).fillna(0.0).values
        S = sigma.reindex(index=self.assets, columns=self.assets).values
        out: list[Violation] = []
        for i, a in enumerate(self.assets):
            if x[i] >= self.max_weight[i] - tol_w and self.max_weight[i] < 1.0:
                out.append(Violation(f"cap:{a}", x[i], self.max_weight[i], f"{a} ({self.labels[a]}) is pinned at its active-band cap of {self.max_weight[i]:.1%} (neutral weight {self.benchmark[i]:.1%} plus {self.max_weight[i] - self.benchmark[i]:.0%}); the views asked for more"))
        vol = float(np.sqrt(max(x @ S @ x, 0.0)))
        if vol >= self.max_vol * (1 - tol_rel):
            out.append(Violation("volatility_cap", vol, self.max_vol, f"portfolio volatility {vol:.1%} is at the {self.max_vol:.1%} limit (the neutral portfolio's volatility plus the allowance); the views want more risk"))
        dur = float(self.duration @ x)
        if dur >= self.duration_hi - tol_dur:
            out.append(Violation("duration_ceiling", dur, self.duration_hi, f"portfolio duration {dur:.1f}y is pinned at the liability band ceiling {self.duration_hi:.1f}y (views want it longer)"))
        if dur <= self.duration_lo + tol_dur and self.duration_lo > 0:
            out.append(Violation("duration_floor", dur, self.duration_lo, f"portfolio duration {dur:.1f}y is pinned at the liability band floor {self.duration_lo:.1f}y (views want it too short)"))
        rwa = float(self.risk_weight @ x)
        if self.risk_budget > 0 and rwa >= self.risk_budget * (1 - tol_rel):
            out.append(Violation("capital_budget", rwa, self.risk_budget, f"regulatory risk-weighted exposure {rwa:.2f} is at the capital budget {self.risk_budget:.2f} (the neutral portfolio's plus the allowance); the views want more capital-heavy assets"))
        return out

    def summary(self, w: pd.Series, sigma: pd.DataFrame, w_prev: pd.Series | None) -> dict:
        x = w.reindex(self.assets).fillna(0.0).values
        S = sigma.reindex(index=self.assets, columns=self.assets).values
        out = {
            "volatility": float(np.sqrt(max(x @ S @ x, 0.0))),
            "volatility_limit": self.max_vol,
            "duration": float(self.duration @ x),
            "duration_band": [self.duration_lo, self.duration_hi],
            "risk_weighted_exposure": float(self.risk_weight @ x),
            "risk_weight_budget": self.risk_budget,
            "max_single_weight": float(x.max()),
            "caps": {a: round(float(c), 4) for a, c in zip(self.assets, self.max_weight, strict=True)},
            "benchmark": {a: round(float(b), 4) for a, b in zip(self.assets, self.benchmark, strict=True)},
            "durations": {a: round(float(d), 3) for a, d in zip(self.assets, self.duration, strict=True)},
        }
        if w_prev is not None:
            out["one_way_turnover"] = float(0.5 * np.abs(x - w_prev.reindex(self.assets).fillna(0.0).values).sum())
        return out
