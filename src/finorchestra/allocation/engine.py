"""Allocation engine: views -> Black-Litterman -> constrained QP -> critic -> (optional feedback) -> weights.

Two modes share one code path:
  clip      : optimize once under all constraints and accept whatever was clipped (what published systems do).
  feedback  : after optimizing, ask the critic which institutional constraints are *binding*. A binding cap means
              the views asked for more than the institution allows. Hand those, in plain language, back to the
              agent; let it revise; re-optimize; repeat up to `rounds`.
The executed weights always satisfy the institutional rules. Only the turnover cap can be relaxed, as a last resort
when it conflicts with a newly binding rule, and that relaxation is recorded in the decision.
The difference between the two, holding the first-pass proposal fixed, is the project's central experiment.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from ..config import Config
from ..views.schema import ViewSet
from .black_litterman import BLResult, black_litterman
from .constraints import ConstraintSet, Violation
from .optimizer import OptResult, optimize

Reviser = Callable[[ViewSet, list[str]], ViewSet]


@dataclass
class AllocationOutcome:
    views: ViewSet
    bl: BLResult
    opt: OptResult
    binding_before: list[Violation]  # institutional constraints active after the first-pass optimization
    binding_after: list[Violation]  # ... after the last revision (same as before when no feedback ran)
    final_violations: list[Violation]  # must be empty: the critic's certification of executed weights
    feedback_rounds: int = 0
    revision_history: list[dict] = field(default_factory=list)
    constraint_summary: dict = field(default_factory=dict)

    @property
    def weights(self) -> pd.Series:
        return self.opt.weights

    @property
    def resolved_by_revision(self) -> bool:
        return bool(self.revision_history) and not self.binding_after

    def to_dict(self) -> dict:
        return {
            "views": self.views.model_dump(),
            "black_litterman": self.bl.to_dict(),
            "binding_constraints_first_pass": [v.to_dict() for v in self.binding_before],
            "binding_constraints_final": [v.to_dict() for v in self.binding_after],
            "feedback_rounds": self.feedback_rounds,
            "revision_history": self.revision_history,
            "optimizer": self.opt.to_dict(),
            "final_violations": [v.to_dict() for v in self.final_violations],
            "constraint_summary": self.constraint_summary,
        }


def allocate(
    cfg: Config,
    views: ViewSet,
    sigma: pd.DataFrame,
    w_prev: pd.Series | None,
    benchmark: pd.Series,
    durations: pd.Series,
    reviser: Reviser | None = None,
    rounds: int = 0,
) -> AllocationOutcome:
    """`benchmark` is the date's data-derived neutral portfolio (the Black-Litterman prior and the anchor of every
    mandate limit); `durations` are the date's estimated fund durations."""
    a = cfg.allocation
    cs = ConstraintSet.from_state(cfg, benchmark, sigma, durations)
    w_mkt = benchmark.reindex(cfg.market.tickers).fillna(0.0)
    cash = cfg.market.risk_free_ticker

    def solve(vs: ViewSet) -> tuple[BLResult, OptResult, list[Violation]]:
        bl_res = black_litterman(sigma, w_mkt, vs, a.risk_aversion, cash=cash)
        opt_res = optimize(bl_res.posterior, sigma, cs, a.risk_aversion, w_prev, a.turnover_penalty, w_mkt)
        return bl_res, opt_res, cs.binding(opt_res.weights, sigma)

    history: list[dict] = []
    current = views
    bl, opt, binding = solve(current)
    binding_first = binding

    used_rounds = 0
    if reviser is not None and rounds > 0:
        while binding and used_rounds < rounds:
            msgs = [v.message for v in binding]
            revised = reviser(current, msgs)
            used_rounds += 1
            history.append(
                {
                    "round": used_rounds,
                    "violations_presented": msgs,
                    "rules_presented": [v.rule for v in binding],
                    "views_before": current.model_dump()["views"],
                    "views_after": revised.model_dump()["views"],
                }
            )
            current = revised
            bl, opt, binding = solve(current)

    final_v = cs.check(opt.weights, sigma, w_prev)
    if opt.relaxed_turnover:
        # The turnover cap was deliberately relaxed (recorded in opt.relaxed_turnover); do not also report the
        # resulting turnover as a critic violation, or a legitimate relaxation reads as a breach.
        final_v = [v for v in final_v if v.rule != "max_turnover"]
    return AllocationOutcome(
        views=current,
        bl=bl,
        opt=opt,
        binding_before=binding_first,
        binding_after=binding,
        final_violations=final_v,
        feedback_rounds=used_rounds,
        revision_history=history,
        constraint_summary=cs.summary(opt.weights, sigma, w_prev),
    )
