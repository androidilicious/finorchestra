"""End-to-end orchestration: one decision per rebalance date, then the weekly backtest around it.

`Pipeline.decide(d)` is the unit of work. It sees the world only through `store.snapshot(d)`, and it
returns a plain dict that is written to disk as the explainability record. `Pipeline.backtest()` walks the
rebalance calendar, tracks weights and returns per strategy, evaluates, and writes the run report.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .allocation.benchmark import benchmark_weights
from .allocation.duration import estimate_durations
from .allocation.engine import AllocationOutcome, allocate
from .config import Config
from .data.market import ledoit_wolf_constant_correlation
from .data.pit import PointInTimeStore, Snapshot
from .evaluation import metrics as M
from .evaluation.baselines import baseline_weights
from .evaluation.leakage import certificate, outputs_identical
from .explain.report import (
    plot_cumulative,
    plot_regimes,
    plot_weights,
    run_report_markdown,
    write_decision,
    write_latest_markdown,
)
from .llm.client import LLMClient
from .signals.incremental import incremental_test
from .signals.regime import RegimeEstimate, estimate_regime
from .signals.retrieval import DatedIndex
from .signals.text_signal import StanceScorer, TextSignal, build_text_signal
from .signals.zscores import SignalSet, build_signals
from .utils import LOG, ensure_dir, fridays_between, to_date, write_json
from .views.fitted_agent import fitted_views
from .views.llm_agent import AgentTrace, LLMAgent
from .views.masking import Masker
from .views.schema import ViewSet

LLM_STRATEGIES = ("llm_clip", "llm_feedback")


@dataclass
class Decision:
    date: date
    signals: SignalSet
    regime: RegimeEstimate
    text: TextSignal
    sigma: pd.DataFrame
    outcomes: dict[str, AllocationOutcome]
    traces: dict[str, AgentTrace] = field(default_factory=dict)
    elapsed_s: float = 0.0
    benchmark: pd.Series | None = None  # the date's data-derived neutral portfolio
    durations: pd.Series | None = None  # the date's estimated fund durations (years)
    cov_shrinkage: float | None = None  # Ledoit-Wolf shrinkage intensity estimated for the date's covariance

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": str(self.date),
            "neutral_portfolio": None if self.benchmark is None else {k: round(float(v), 4) for k, v in self.benchmark.items()},
            "durations": None if self.durations is None else {k: round(float(v), 3) for k, v in self.durations.items()},
            "covariance_shrinkage": self.cov_shrinkage,
            "signals": {
                "themes": self.signals.themes,
                "macro_z": self.signals.z,
                "macro_latest": self.signals.raw_latest,
                "text_index_z": self.signals.text_index_z,
                "text_index_latest": self.signals.text_index_latest,
            },
            "regime": self.regime.to_dict(),
            "text_signal": self.text.to_dict(),
            "strategies": {
                k: {
                    "allocation": v.to_dict(),
                    "trace": None
                    if k not in self.traces
                    else {
                        "rounds": self.traces[k].rounds,
                        "fallbacks": self.traces[k].fallbacks,
                        "documents_used": self.traces[k].documents_used,
                        "prompt_chars": self.traces[k].prompt_chars,
                    },
                }
                for k, v in self.outcomes.items()
            },
            "elapsed_s": self.elapsed_s,
        }

    def panel_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {"date": pd.Timestamp(self.date)}
        row.update(features_row(self.signals, self.text))
        row.update({f"p_{k}": v for k, v in self.regime.probabilities.items()})
        row["regime"] = self.regime.label
        return row


def features_row(signals: SignalSet, text: TextSignal) -> dict[str, float]:
    """The feature vector a decision date contributes to the fitted agent's training history and the panel."""
    row: dict[str, float] = {}
    row.update({f"theme_{k}": v for k, v in signals.themes.items()})
    row.update({f"tiz_{k}": v for k, v in signals.text_index_z.items()})
    row["fed_stance"] = text.stance
    row["fed_stance_change"] = text.stance_change
    row["fed_novelty"] = text.novelty
    return row


class Pipeline:
    def __init__(self, cfg: Config, store: PointInTimeStore, client: LLMClient | None = None):
        self.cfg = cfg
        self.store = store
        self.client = client or LLMClient(cfg.llm)
        self.masker = Masker.build(cfg.market.universe, enabled=cfg.llm.masking)
        self.scorer = StanceScorer(cfg, self.client, self.masker)
        self.agent = LLMAgent(cfg, self.client, self.masker)

    # ------------------------------------------------------------------ pieces
    def _anchor(self) -> str:
        return {0: "W-MON", 1: "W-TUE", 2: "W-WED", 3: "W-THU", 4: "W-FRI"}[self.cfg.run.rebalance_weekday]

    def _weekly_returns(self, snap: Snapshot) -> pd.DataFrame:
        """Friday-to-Friday total returns known at the snapshot date (all history)."""
        return snap.prices.ffill().resample(self._anchor()).last().pct_change().dropna(how="all")

    def _covariance(self, window: pd.DataFrame) -> tuple[pd.DataFrame, float]:
        """Annualised total-return covariance, Ledoit-Wolf (2004) constant-correlation shrinkage with estimated intensity.

        Total returns rather than excess-over-cash, because the cash row of an excess-return covariance is identically
        zero. The constant-correlation target keeps every fund's own variance and shrinks only the correlations, so a
        low-risk fund such as cash is never made to look risky (a scaled-identity target would do exactly that).
        """
        return ledoit_wolf_constant_correlation(window.fillna(0.0))

    def _durations(self, snap: Snapshot, window: pd.DataFrame) -> pd.Series:
        """Empirical durations from each bond fund's returns against the 10-year yield over the covariance window."""
        y = snap.macro.get(self.cfg.market.yield_series)
        if y is None or len(y.dropna()) < 30:
            return pd.Series(0.0, index=window.columns)
        dy = y.dropna().astype(float).resample(self._anchor()).last().diff() / 100.0
        return estimate_durations(window, dy.reindex(window.index), self.cfg.market.kinds)

    def features_for(self, d: date) -> dict[str, float]:
        """Signal features for a date without allocating: used to build the fitted agent's warm-up history."""
        snap = self.store.snapshot(d)
        signals = build_signals(snap, self.cfg.signals)
        text = build_text_signal(snap.fomc, d, self.scorer, tuple(self.cfg.text_signal.novelty_ngram))
        return features_row(signals, text)

    def warmup_history(self, first: date) -> pd.DataFrame:
        """Feature rows for the weeks strictly before `first`: the fitted agent's initial training set and the regime
        percentiles' reference distribution. Past-only by construction; the backtest then appends each decision's row."""
        fa = self.cfg.fitted_agent
        n_warm = fa.min_train_weeks + fa.horizon_weeks + 8
        warm_dates = [wd for wd in fridays_between((pd.Timestamp(first) - pd.Timedelta(weeks=n_warm)).date(), first, self.cfg.run.rebalance_weekday) if wd < first]
        LOG.info("warm-up: %d feature dates before %s for the fitted agent and regime percentiles", len(warm_dates), first)
        rows = [{"date": pd.Timestamp(wd), **self.features_for(wd)} for wd in warm_dates]
        return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame()

    def decide(self, d: date, w_prev: dict[str, pd.Series] | None = None, strategies: list[str] | None = None, history: pd.DataFrame | None = None) -> Decision:
        """`history`: feature rows for decision dates strictly before `d` (the fitted agent's training set and the
        regime percentiles' reference distribution). Without it the fitted agent emits no view and the regime uses
        the normal-CDF fallback; the backtest always supplies it."""
        t0 = time.time()
        strategies = strategies or self.cfg.evaluation.strategies
        w_prev = w_prev or {}
        snap = self.store.snapshot(d)
        signals = build_signals(snap, self.cfg.signals)
        hist = history if history is not None else pd.DataFrame()
        theme_hist = hist.rename(columns=lambda c: c.replace("theme_", "")) if not hist.empty else None
        regime = estimate_regime(signals.themes, theme_hist)
        text = build_text_signal(snap.fomc, d, self.scorer, tuple(self.cfg.text_signal.novelty_ngram))
        weekly_all = self._weekly_returns(snap)
        window = weekly_all.tail(self.cfg.allocation.cov_window_weeks).fillna(0.0)
        sigma, shrink = self._covariance(window)
        durations = self._durations(snap, window)
        benchmark = benchmark_weights(sigma, self.cfg.market.risk_free_ticker, self.cfg.allocation.benchmark)
        outcomes: dict[str, AllocationOutcome] = {}
        traces: dict[str, AgentTrace] = {}

        if "rule" in strategies:
            views = fitted_views(self.cfg, hist, weekly_all, pd.Timestamp(d), features_row(signals, text), regime)
            outcomes["rule"] = allocate(self.cfg, views, sigma, w_prev.get("rule"), benchmark, durations)

        if any(s in strategies for s in LLM_STRATEGIES):
            index = DatedIndex(snap.fomc, d, self.cfg.retrieval)
            proposal, msgs, trace = self.agent.propose(signals, regime, text, index)
            if "llm_clip" in strategies:
                outcomes["llm_clip"] = allocate(self.cfg, proposal, sigma, w_prev.get("llm_clip"), benchmark, durations)
                traces["llm_clip"] = trace
            if "llm_feedback" in strategies:
                state = {"msgs": msgs}
                fb_trace = AgentTrace(prompt_chars=trace.prompt_chars, rounds=trace.rounds, fallbacks=trace.fallbacks, documents_used=list(trace.documents_used), raw_views=list(trace.raw_views))

                def reviser(vs: ViewSet, violations: list[str]) -> ViewSet:
                    new_vs, new_msgs = self.agent.revise(state["msgs"], vs, violations, fb_trace)
                    state["msgs"] = new_msgs
                    return new_vs

                outcomes["llm_feedback"] = allocate(
                    self.cfg, proposal, sigma, w_prev.get("llm_feedback"), benchmark, durations, reviser=reviser, rounds=self.cfg.allocation.feedback_rounds
                )
                traces["llm_feedback"] = fb_trace
        return Decision(d, signals, regime, text, sigma, outcomes, traces, time.time() - t0, benchmark=benchmark, durations=durations, cov_shrinkage=shrink)

    # ------------------------------------------------------------------ backtest
    def rebalance_dates(self) -> list[date]:
        start = to_date(self.cfg.run.start)
        last_px = self.store.last_price_date()
        end = min(to_date(self.cfg.run.end), last_px) if self.cfg.run.end else last_px
        return fridays_between(start, end, self.cfg.run.rebalance_weekday)

    def backtest(self, run_dir: Path | None = None, progress_every: int = 26) -> dict[str, Any]:
        cfg = self.cfg
        if run_dir is None:
            # the run id hashes the config, not the data: never overwrite a finished run whose inputs may have changed
            base = cfg.outputs_dir / "runs" / cfg.run_id()
            run_dir, k = base, 2
            while (run_dir / "summary.json").exists():
                run_dir = base.with_name(f"{base.name}-r{k}")
                k += 1
        run_dir = ensure_dir(run_dir)
        dates = self.rebalance_dates()
        LOG.info("backtest: %d rebalance dates %s..%s -> %s", len(dates), dates[0], dates[-1], run_dir)

        weekly_px = self.store.market.weekly_prices(cfg.run.rebalance_weekday)
        weekly_ret = weekly_px.pct_change()
        tickers = cfg.market.tickers
        strategies = list(cfg.evaluation.strategies)
        baselines = list(cfg.evaluation.baselines)
        names = strategies + baselines

        weights: dict[str, list[pd.Series]] = {n: [] for n in names}
        rets: dict[str, list[float]] = {n: [] for n in names}
        ret_dates: list[pd.Timestamp] = []
        w_prev: dict[str, pd.Series] = {}
        panel_rows: list[dict] = []
        fb_stats = Counter()
        fb_rules = Counter()
        t_start = time.time()
        last_decision: Decision | None = None

        history = self.warmup_history(dates[0])

        for i, d in enumerate(dates):
            dec = self.decide(d, w_prev, strategies, history)
            last_decision = dec
            write_decision(run_dir, dec.to_dict())
            panel_rows.append(dec.panel_row())
            history = pd.concat([history, pd.DataFrame([{"date": pd.Timestamp(d), **features_row(dec.signals, dec.text)}]).set_index("date")])

            # next-week realised returns (None on the final date)
            pos = weekly_px.index.searchsorted(pd.Timestamp(d), side="right") - 1
            has_next = pos + 1 < len(weekly_px.index)
            nxt = weekly_ret.iloc[pos + 1].reindex(tickers).fillna(0.0) if has_next else None

            todays: dict[str, pd.Series] = {}
            for s in strategies:
                if s in dec.outcomes:
                    todays[s] = dec.outcomes[s].weights.reindex(tickers).fillna(0.0)
            for b in baselines:
                todays[b] = baseline_weights(b, cfg, dec.benchmark).reindex(tickers).fillna(0.0)

            for n, w in todays.items():
                weights[n].append(w.rename(pd.Timestamp(d)))
                if has_next:
                    rets[n].append(float((w * nxt).sum()))
            if has_next:
                ret_dates.append(weekly_px.index[pos + 1])
            w_prev = {k: v for k, v in todays.items() if k in strategies}

            if "llm_feedback" in dec.outcomes:
                o = dec.outcomes["llm_feedback"]
                fb_stats["decisions"] += 1
                if o.binding_before:
                    fb_stats["with_implied_violations"] += 1
                    for r in (x.rule for x in o.binding_before):
                        fb_rules[r] += 1
                fb_stats["rounds"] += o.feedback_rounds
                if o.resolved_by_revision:
                    fb_stats["resolved_by_revision"] += 1

            if (i + 1) % progress_every == 0 or i == len(dates) - 1:
                el = time.time() - t_start
                LOG.info("  %d/%d dates (%s) regime=%s  %.1fs elapsed, ~%.0fs left", i + 1, len(dates), d, dec.regime.label, el, el / (i + 1) * (len(dates) - i - 1))

        # ------------------------------------------------------------ assemble
        W = {n: pd.DataFrame(v) for n, v in weights.items() if v}
        R = pd.DataFrame({n: pd.Series(v, index=ret_dates[: len(v)]) for n, v in rets.items() if v})
        rf = weekly_ret[cfg.market.risk_free_ticker].reindex(R.index).fillna(0.0)
        EX = R.sub(rf, axis=0)
        panel = pd.DataFrame(panel_rows).set_index("date")

        for n, w in W.items():
            w.to_csv(run_dir / f"weights_{n}.csv")
        R.to_csv(run_dir / "returns_gross.csv")
        EX.to_csv(run_dir / "returns_excess.csv")
        panel.to_csv(run_dir / "panel.csv")

        perf, deflated, TO = {}, {}, {}
        for n in R.columns:
            # turnover of decision i (including the initial trade out of cash) is charged against holding-week return i
            to = M.turnover_series(W[n], cash=cfg.market.risk_free_ticker)
            to_aligned = pd.Series(to.values[: len(R)], index=R.index)
            TO[n] = to_aligned
            perf[n] = M.summarize(EX[n], R[n], to_aligned, cfg.evaluation.cost_bps_grid)
        # Deflated Sharpe: trials = the strategies actually run; the cross-trial Sharpe dispersion is measured from them
        # (no prior). Baselines are single trials.
        strat_sr = [perf[n]["sharpe"] for n in strategies if n in perf and np.isfinite(perf[n]["sharpe"])]
        sr_disp_annual = float(np.std(strat_sr, ddof=1)) if len(strat_sr) >= 2 else 0.0
        for n in R.columns:
            deflated[n] = M.deflated_sharpe(EX[n], len(strategies) if n in strategies else 1, sr_var_across_trials=(sr_disp_annual / np.sqrt(52.0)) ** 2)

        comps = {}
        pairs = [("llm_feedback", "rule"), ("llm_clip", "rule"), ("llm_feedback", "llm_clip"), ("rule", "benchmark"), ("llm_clip", "benchmark"), ("llm_feedback", "benchmark")]
        for a, b in pairs:
            if a in EX.columns and b in EX.columns:
                comps[f"{a} - {b}"] = M.block_bootstrap_sharpe_diff(EX[a], EX[b], cfg.evaluation.bootstrap_blocks_weeks, cfg.evaluation.bootstrap_draws, cfg.run.seed)

        factors = pd.DataFrame({k: weekly_ret[f.long] - weekly_ret[f.short] for k, f in cfg.evaluation.attribution_factors.items()}).reindex(R.index)
        attrib = {n: M.attribution(EX[n], factors).to_dict() for n in R.columns}

        ex_weekly_all = weekly_ret.sub(weekly_ret[cfg.market.risk_free_ticker], axis=0)
        inc = incremental_test(panel, ex_weekly_all, cfg)
        if not inc.empty:
            inc.to_csv(run_dir / "incremental_test.csv", index=False)

        regime_share = panel["regime"].value_counts(normalize=True).round(3).to_dict()
        cert = certificate(cfg, self.store, dates, self.client.describe, self.client.stats.to_dict(), len(strategies), sr_disp_annual)
        write_json(run_dir / "certificate.json", cert)

        n_dec = max(fb_stats["decisions"], 1)
        summary = {
            "run_id": cfg.run_id(),
            "dates": {"first": str(dates[0]), "last": str(dates[-1]), "count": len(dates)},
            "model": self.client.describe,
            "elapsed_s": time.time() - t_start,
            "performance": perf,
            "deflated": deflated,
            "deflated_inputs": {
                "n_trials": len(strategies),
                "sr_dispersion_annual_measured": sr_disp_annual,
                "note": "SR0 (expected best Sharpe of skill-less trials) uses the number of strategies run and the Sharpe dispersion measured across them",
            },
            "comparisons": comps,
            "attribution": attrib,
            "feedback": {
                "decisions": fb_stats["decisions"],
                "decisions_with_implied_violations": fb_stats["with_implied_violations"],
                "share": fb_stats["with_implied_violations"] / n_dec,
                "total_rounds": fb_stats["rounds"],
                "resolved_by_revision": fb_stats["resolved_by_revision"],
                "top_rules": fb_rules.most_common(5),
            },
            "incremental_test": inc.to_dict(orient="records") if not inc.empty else [],
            "regime_share": regime_share,
            "certificate": cert,
        }
        write_json(run_dir / "summary.json", summary)
        (run_dir / "report.md").write_text(run_report_markdown(summary), encoding="utf-8")

        plot_cumulative(R, run_dir / "cumulative.png", f"Gross weekly returns, growth of 1 ({cfg.run_id()})")
        for n in strategies:
            if n in W:
                plot_weights(W[n], run_dir / f"weights_{n}.png", f"Weights over time: {n}")
        pcols = [c for c in panel.columns if c.startswith("p_")]
        plot_regimes(panel[pcols].rename(columns=lambda c: c[2:]), run_dir / "regimes.png")
        if last_decision is not None:
            write_latest_markdown(run_dir, last_decision.to_dict())
        try:
            from .explain.dashboard import build_dashboard

            build_dashboard(run_dir, cfg)
        except Exception as e:  # noqa: BLE001 - a dashboard problem must never invalidate a finished run
            LOG.warning("dashboard generation failed: %s", e)
        LOG.info("backtest complete -> %s", run_dir / "report.md")
        return summary

    # ------------------------------------------------------------------ leakage test
    def leakage_check(self, d: date, strategies: list[str] | None = None) -> tuple[bool, list[str]]:
        """Decision from the full store vs. from a store truncated at d must be identical."""
        full = self.decide(d, None, strategies, self.warmup_history(d)).to_dict()
        trunc_store = self.store.truncated(d)
        other = Pipeline(self.cfg, trunc_store, self.client)
        trunc = other.decide(d, None, strategies, other.warmup_history(d)).to_dict()
        for dd in (full, trunc):
            for s in dd["strategies"].values():
                s.pop("trace", None)
        return outputs_identical(full, trunc)


def sanity_weights(w: pd.Series) -> bool:
    return bool(np.isfinite(w.values).all() and abs(w.sum() - 1) < 1e-3 and (w >= -1e-6).all())
