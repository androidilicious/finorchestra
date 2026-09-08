"""Leakage controls: a contamination certificate and a structural no-look-ahead test.

The certificate records, for every input, how point-in-time it really is, plus everything about the model
that bears on memorisation. The test takes a decision date D, runs the decision from the full store and
from a store physically truncated at D, and asserts the outputs are identical.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from ..config import Config
from ..data.pit import PointInTimeStore


def certificate(cfg: Config, store: PointInTimeStore, dates: list[date], llm_describe: dict, llm_stats: dict, trials: int, sr_dispersion_measured: float | None = None) -> dict[str, Any]:
    cutoff = pd.Timestamp(cfg.llm.knowledge_cutoff).date() if cfg.llm.provider != "mock" else None
    n_after = sum(1 for d in dates if cutoff and d > cutoff)
    inputs = []
    try:
        desc = store.fred.describe().set_index("series")
    except Exception:  # noqa: BLE001 - describe is informational
        desc = None
    for s in cfg.fred.series:
        mode = store.fred.modes.get(s.id, "unknown")
        lag_txt = f"usable {s.lag_days} business day(s) after the observation date" if s.lag_days else "available same day"
        entry = {
            "input": s.id,
            "kind": "official statistic" if s.revised else "market-determined series",
            "point_in_time": {
                "alfred_weekly_vintages": "yes: value as published on the latest Friday <= decision date",
                "api_realtime": "yes: exact real-time periods from the FRED API",
                "latest_unrevised": f"n/a: series is never revised; {lag_txt}",
                "cached": "yes (cached vintage table)",
            }.get(mode, mode),
            "mode": mode,
            "lag_business_days": s.lag_days,
        }
        if desc is not None and s.id in desc.index:
            entry["observations"] = int(desc.loc[s.id, "observations"])
            entry["vintage_intervals_per_observation"] = float(desc.loc[s.id, "intervals_per_obs"])
        inputs.append(entry)
    inputs += [
        {"input": "ETF adjusted closes", "kind": "market prices", "point_in_time": "yes for returns: total-return adjusted closes whose levels rescale on each refresh; every use is ratio-based (returns, covariance), so results are invariant to the refresh date", "mode": "latest"},
        {"input": cfg.text_indices.epu_daily_series, "kind": "research index (newspaper counts)", "point_in_time": f"partial: latest vintage, availability lag {cfg.text_indices.epu_lag_days} business days; author backfills not reconstructed", "mode": "latest_with_lag"},
        {"input": "GPR daily", "kind": "research index (newspaper counts)", "point_in_time": f"partial: latest vintage, availability lag {cfg.text_indices.gpr_lag_days} business days; author backfills not reconstructed", "mode": "latest_with_lag"},
        {"input": "FOMC statements", "kind": "central bank text", "point_in_time": "yes: dated by release; usable from release day", "mode": "dated_corpus"},
    ]
    return {
        "run_id": cfg.run_id(),
        "decision_dates": {"first": str(dates[0]) if dates else None, "last": str(dates[-1]) if dates else None, "count": len(dates)},
        "inputs": inputs,
        "model": llm_describe,
        "model_call_stats": llm_stats,
        "prompt_masking": {
            "enabled": cfg.llm.masking,
            "what": "tickers -> Asset A/B/...; absolute dates -> [date] or t-k weeks; percentage levels in retrieved text (including fractions such as 5-1/4) rounded to the nearest 0.5, ranges widened outward to 0.5 bounds, move sizes in percentage points left unchanged",
            "limitation": "masking removes recall hooks; it cannot make a model forget. Treat pre-cutoff LLM results as upper bounds.",
        },
        "knowledge_cutoff": {
            "declared": str(cutoff) if cutoff else "n/a (deterministic mock has no training data)",
            "decision_dates_after_cutoff": n_after,
            "share_after_cutoff": (n_after / len(dates)) if dates else None,
        },
        "constraints": "enforced deterministically by the optimizer and re-checked by the critic on executed weights",
        "multiple_testing": {
            "strategy_variants_run": trials,
            "measured_sharpe_dispersion_annual": sr_dispersion_measured,
            "note": "deflated Sharpe uses the number of strategies run and the Sharpe dispersion measured across them; every extra configuration tried should be added to the count",
        },
        "assumptions": assumptions_block(cfg),
    }


def assumptions_block(cfg: Config) -> list[dict[str, Any]]:
    """Every remaining hand-set number in the configuration, with its basis. Estimated or sourced quantities
    (durations, risk weights, neutral portfolio, covariance shrinkage, regime percentiles, formula loadings) are listed
    separately as 'derived' so a reader can see what is data and what is a choice."""
    a, m, f, sg, ev = cfg.allocation, cfg.allocation.mandate, cfg.fitted_agent, cfg.signals, cfg.evaluation
    choices = [
        {"name": "z-score window / minimum history / clip", "value": f"{sg.zscore_window_years}y / {sg.min_history_years}y / {sg.clip}", "basis": "judgement: one business cycle of 'normal'; sensitivity in docs/assumptions-register.md"},
        {"name": "theme membership and signs", "value": {k: dict(zip(v.series, v.signs, strict=True)) for k, v in sg.themes.items()}, "basis": "judgement, textbook macro; Investment Clock axes (growth, inflation)"},
        {"name": "covariance window", "value": f"{a.cov_window_weeks} weeks", "basis": "judgement: two years of weekly returns; shrinkage intensity is estimated (Ledoit-Wolf 2004)"},
        {"name": "risk aversion delta", "value": a.risk_aversion, "basis": "literature: He-Litterman (1999) / Idzorek (2005) range 2.25 to 3.1"},
        {"name": "turnover penalty", "value": a.turnover_penalty, "basis": "judgement: about 20 bp per unit traded, in expected-return units"},
        {"name": "feedback rounds", "value": a.feedback_rounds, "basis": "judgement: cost control"},
        {"name": "neutral portfolio method", "value": a.benchmark, "basis": "data: inverse-volatility over risky funds from the date's covariance; no parameters"},
        {"name": "mandate: active weight band", "value": m.active_weight_band, "basis": "PLACEHOLDER for the client's policy limit"},
        {"name": "mandate: volatility allowance over neutral", "value": m.volatility_allowance, "basis": "PLACEHOLDER for the client's policy limit"},
        {"name": "mandate: duration band (years) around neutral", "value": m.duration_band_years, "basis": "PLACEHOLDER for the client's policy limit"},
        {"name": "mandate: capital allowance over neutral RWA", "value": m.capital_allowance, "basis": "PLACEHOLDER; risk weights themselves are 12 CFR 217 standardised"},
        {"name": "mandate: weekly one-way turnover cap", "value": m.max_one_way_turnover, "basis": "PLACEHOLDER for the client's policy limit"},
        {"name": "fitted agent: horizon / min training / ridge grid / max views", "value": f"{f.horizon_weeks}w / {f.min_train_weeks}w / {f.ridge_alphas} / {f.max_views}", "basis": "judgement on the procedure; loadings are estimated"},
        {"name": "retrieval: top_k / chars per doc / recency half-life", "value": f"{cfg.retrieval.top_k} / {cfg.retrieval.max_chars_per_doc} / {cfg.retrieval.recency_halflife_days}d", "basis": "practical: 4k-token local model budget; half-life is judgement"},
        {"name": "bootstrap block / draws", "value": f"{ev.bootstrap_blocks_weeks}w / {ev.bootstrap_draws}", "basis": "method Politis-Romano (1994); block length judgement"},
        {"name": "cost grid (bp one-way)", "value": ev.cost_bps_grid, "basis": "judgement on the grid"},
        {"name": "attribution factor proxies", "value": {k: f"{v.long}-{v.short}" for k, v in ev.attribution_factors.items()}, "basis": "judgement: ETF spreads as factor proxies"},
        {"name": "availability lags (business days)", "value": {s.id: s.lag_days for s in cfg.fred.series}, "basis": "data: publication schedules (H.15 next business day)"},
        {"name": "model knowledge cutoff", "value": cfg.llm.knowledge_cutoff, "basis": "declared from the vendor's documentation; not checkable"},
    ]
    derived = [
        {"name": "fund durations", "how": "estimated each date: minus the slope of weekly fund return on weekly 10y-yield change over the covariance window; non-bond funds 0"},
        {"name": "regulatory risk weights", "how": "12 CFR 217.32 / 217.52 by declared kind: government, inflation-linked, cash, gold 0%; corporate 100%; listed equity 300%; commodity and currency funds 100% (other assets)"},
        {"name": "neutral portfolio", "how": f"{a.benchmark} over risky funds from the date's covariance"},
        {"name": "covariance shrinkage", "how": "Ledoit-Wolf (2004) constant-correlation target with the paper's estimated intensity; each fund keeps its own variance"},
        {"name": "regime probabilities", "how": "empirical percentile of each theme within its own past-only history; normal-CDF fallback with under 52 weeks"},
        {"name": "formula-agent loadings and confidence", "how": "past-only ridge regression per asset, penalty by leave-one-out CV; confidence = 2*Phi(|prediction|/residual sd) - 1"},
        {"name": "deflated-Sharpe dispersion", "how": "standard deviation of annual Sharpe across the strategies run"},
    ]
    return [{"kind": "choice", **c} for c in choices] + [{"kind": "derived", **d} for d in derived]


def outputs_identical(a: dict, b: dict, tol: float = 1e-9) -> tuple[bool, list[str]]:
    """Deep-compare two decision dicts, tolerating float noise."""
    diffs: list[str] = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in set(x) | set(y):
                if k in ("timestamp", "elapsed_s"):
                    continue
                walk(x.get(k), y.get(k), f"{path}.{k}")
        elif isinstance(x, list) and isinstance(y, list):
            if len(x) != len(y):
                diffs.append(f"{path}: len {len(x)} != {len(y)}")
                return
            for i, (p, q) in enumerate(zip(x, y, strict=True)):
                walk(p, q, f"{path}[{i}]")
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool):
            if not (np.isnan(x) and np.isnan(y)) and abs(float(x) - float(y)) > tol:
                diffs.append(f"{path}: {x} != {y}")
        elif x != y:
            diffs.append(f"{path}: {x!r} != {y!r}")

    walk(a, b, "$")
    return (not diffs), diffs
