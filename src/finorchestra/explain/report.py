"""Explainability outputs: one JSON per decision, a Markdown rendering of any decision, and the run report.

Everything here is a readout of facts the pipeline already produced. Nothing is estimated after the fact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ..utils import ensure_dir, write_json  # noqa: E402


def _pct(x: float | None, digits: int = 1) -> str:
    return "n/a" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:+.{digits}%}"


def _num(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None or (isinstance(x, float) and pd.isna(x)) else f"{x:.{digits}f}"


def decision_markdown(dec: dict[str, Any]) -> str:
    d = dec["date"]
    reg = dec["regime"]
    txt = dec["text_signal"]
    lines = [f"# Decision {d}", ""]
    lines += [f"**Regime:** {reg['label']} " + ", ".join(f"{k} {v:.0%}" for k, v in reg["probabilities"].items()), ""]
    lines += [
        f"**Fed text:** last statement {txt.get('statement_date')} ({txt.get('days_since_statement')} days ago), "
        f"stance {txt.get('fed_stance'):+.2f}, novelty {txt.get('fed_statement_novelty'):.2f}",
        "",
    ]
    sig = dec["signals"]
    lines += ["## Signals (z-scores)", "", "| theme | z |", "|---|---|"]
    lines += [f"| {k} | {v:+.2f} |" for k, v in sig["themes"].items()]
    lines += ["", "| text index | z |", "|---|---|"]
    lines += [f"| {k} | {v:+.2f} |" for k, v in sig["text_index_z"].items()]
    lines += [""]
    for name, strat in dec["strategies"].items():
        a = strat["allocation"]
        lines += [f"## Strategy: {name}", ""]
        vs = a["views"]
        lines += [f"*{vs.get('regime_assessment','')}*", "", "| asset | direction | E[excess return]/yr | confidence | evidence |", "|---|---|---|---|---|"]
        for v in vs["views"]:
            ev = "; ".join(v.get("evidence", [])[:3])
            lines.append(f"| {v['asset']} | {v['direction']} | {_pct(v['expected_excess_return_annual'])} | {v['confidence']:.2f} | {ev} |")
        lines += ["", f"Rationale: {vs.get('rationale','')}", ""]
        if a["binding_constraints_first_pass"]:
            lines += ["**Views could not be implemented as stated (binding institutional constraints):**"] + [f"- {x['message']}" for x in a["binding_constraints_first_pass"]] + [""]
        if a["feedback_rounds"]:
            lines += [f"Constraint feedback: {a['feedback_rounds']} revision round(s). Views after each revision:", ""]
            for h in a["revision_history"]:
                after = ", ".join(f"{v['asset']} {v['expected_excess_return_annual']:+.3f}@{v['confidence']:.2f}" for v in h["views_after"])
                lines.append(f"- round {h['round']}: {after}")
            if a["binding_constraints_final"]:
                lines += ["", "Still binding after revision:"] + [f"- {x['message']}" for x in a["binding_constraints_final"]]
            else:
                lines += ["", "After revision no institutional constraint binds: the revised views are implementable as stated."]
            lines.append("")
        w = a["optimizer"]["weights"]
        cs = a["constraint_summary"]
        lines += ["| asset | weight |", "|---|---|"] + [f"| {k} | {v:.1%} |" for k, v in w.items() if v > 0.0005]
        lines += [
            "",
            f"Volatility {cs['volatility']:.1%} (limit {cs['volatility_limit']:.0%}), duration {cs['duration']:.1f}y "
            f"(band {cs['duration_band'][0]:.1f}-{cs['duration_band'][1]:.1f}), risk-weighted {cs['risk_weighted_exposure']:.2f} "
            f"(budget {cs['risk_weight_budget']:.2f}), turnover {_num(cs.get('one_way_turnover'))}.",
        ]
        if a["final_violations"]:
            lines += ["", "**FINAL WEIGHTS VIOLATE:**"] + [f"- {x['message']}" for x in a["final_violations"]]
        else:
            lines += ["", "Critic: all constraints satisfied on executed weights."]
        lines.append("")
    return "\n".join(lines)


def write_decision(run_dir: Path, dec: dict[str, Any]) -> None:
    ddir = ensure_dir(run_dir / "decisions")
    write_json(ddir / f"{dec['date']}.json", dec)


def write_latest_markdown(run_dir: Path, dec: dict[str, Any]) -> Path:
    p = run_dir / "latest_decision.md"
    p.write_text(decision_markdown(dec), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------------------- run report
def plot_cumulative(returns: pd.DataFrame, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5))
    wealth = (1 + returns.fillna(0)).cumprod()
    for c in wealth.columns:
        ax.plot(wealth.index, wealth[c], label=c, linewidth=1.4 if c.startswith("llm") or c == "rule" else 1.0, alpha=0.95)
    ax.set_title(title)
    ax.set_ylabel("growth of 1")
    ax.grid(alpha=0.3)
    ax.legend(ncol=3, fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_weights(weights: pd.DataFrame, path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.stackplot(weights.index, [weights[c].values for c in weights.columns], labels=weights.columns, alpha=0.9)
    ax.set_ylim(0, 1)
    ax.set_title(title)
    ax.legend(ncol=5, fontsize=7, loc="upper left")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_regimes(regimes: pd.DataFrame, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(10, 3.2))
    ax.stackplot(regimes.index, [regimes[c].values for c in regimes.columns], labels=regimes.columns, alpha=0.9)
    ax.set_ylim(0, 1)
    ax.set_title("Regime probabilities over time")
    ax.legend(ncol=4, fontsize=8, loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def run_report_markdown(summary: dict[str, Any]) -> str:
    L = [f"# Finorchestra run report: `{summary['run_id']}`", ""]
    L += [f"Decision dates: {summary['dates']['first']} to {summary['dates']['last']} ({summary['dates']['count']} weekly rebalances). "
          f"Model: **{summary['model']['provider']} / {summary['model']['model']}**. Elapsed {summary['elapsed_s']:.0f}s.", ""]
    L += ["## Performance (weekly, excess over cash for Sharpe)", ""]
    L += ["| strategy | ann. return | ann. vol | Sharpe | max DD | turnover/wk | Sharpe @5bp | @10bp | @20bp | @30bp | deflated SR prob |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, m in summary["performance"].items():
        sb = m["sharpe_by_cost_bps"]
        dsr = summary["deflated"].get(name, {}).get("deflated_sharpe_prob")
        L.append(
            f"| {name} | {_pct(m['ann_return'])} | {m['ann_vol']:.1%} | {_num(m['sharpe'])} | {m['max_drawdown']:.1%} | {m['avg_one_way_turnover']:.1%} | "
            f"{_num(sb.get('5'))} | {_num(sb.get('10'))} | {_num(sb.get('20'))} | {_num(sb.get('30'))} | {_num(dsr)} |"
        )
    dp = summary.get("deflated_inputs") or {}
    if dp:
        L += ["", f"Deflated Sharpe probability: P(Sharpe > SR0) where SR0 is the expected best Sharpe of {dp.get('n_trials')} skill-less trials, "
              f"using the annual Sharpe dispersion measured across those strategies ({_num(dp.get('sr_dispersion_annual_measured'))}); baselines use one trial."]
    L += ["", "## Paired comparisons (circular block bootstrap of Sharpe difference)", "", "| comparison | ΔSharpe | 95% CI | p-value |", "|---|---|---|---|"]
    for k, v in summary["comparisons"].items():
        L.append(f"| {k} | {_num(v['diff'], 3)} | [{_num(v['ci95'][0], 3)}, {_num(v['ci95'][1], 3)}] | {_num(v['p_value'], 3)} |")
    L += ["", "## Return attribution (HAC t-stats)", "", "| strategy | alpha/yr | t(alpha) | β MKT | β DUR | β CRD | β CMD | β USD | R² | var share mkt/style/cov/resid |", "|---|---|---|---|---|---|---|---|---|---|"]
    for name, a in summary["attribution"].items():
        b = a["betas"]
        vs = a["variance_share"]
        L.append(
            f"| {name} | {_pct(a['alpha_annual'])} | {_num(a['alpha_t_hac'])} | {_num(b.get('MKT'))} | {_num(b.get('DUR'))} | {_num(b.get('CRD'))} | "
            f"{_num(b.get('CMD'))} | {_num(b.get('USD'))} | {_num(a['r2'])} | {vs['market']:.0%}/{vs['style']:.0%}/{vs.get('covariance', 0):+.0%}/{vs['residual']:.0%} |"
        )
    L += ["", "Variance shares are var(component)/var(return): market factor, the other factors, twice their covariance, and the residual (= 1 − R²). They sum to 100%."]
    L += ["", "## Constraint feedback loop", ""]
    fb = summary["feedback"]
    L += [
        f"- Decisions where the LLM's first-pass views hit at least one institutional constraint: {fb['decisions_with_implied_violations']} of {fb['decisions']} ({fb['share']:.0%}).",
        f"- Revision rounds used: {fb['total_rounds']}. Decisions where revision removed every binding constraint: {fb['resolved_by_revision']}.",
        f"- Most frequently binding: {', '.join(f'{k} ({v})' for k, v in fb['top_rules'])}.",
        "",
    ]
    L += ["## Incremental information test (our Fed-text signal vs. baseline signals)", ""]
    it = summary.get("incremental_test") or []
    if it:
        L += ["| target | horizon (wk) | n | adj R² base | adj R² +ours | Δ adj R² | t(stance) | t(stance Δ) | t(novelty) | corr fwd | corr back |", "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in it:
            L.append(
                f"| {r['target']} | {r['horizon_weeks']} | {r['n']} | {_num(r['adj_r2_baseline'], 3)} | {_num(r['adj_r2_augmented'], 3)} | "
                f"{_num(r['delta_adj_r2'], 3)} | {_num(r.get('t_fed_stance'))} | {_num(r.get('t_fed_stance_change'))} | {_num(r.get('t_fed_novelty'))} | {_num(r['corr_signal_vs_forward'], 3)} | {_num(r['corr_signal_vs_backward'], 3)} |"
            )
    else:
        L.append("Not enough data for the test.")
    L += ["", "## Regime distribution", ""]
    L += ["| regime | share of weeks |", "|---|---|"] + [f"| {k} | {v:.0%} |" for k, v in summary["regime_share"].items()]
    L += ["", "## Contamination certificate", "", "```json", json.dumps(summary["certificate"], indent=1)[:6000], "```", ""]
    L += ["## Reading this honestly", ""]
    is_mock = (summary.get("model") or {}).get("provider") == "mock"
    L += [
        ("- With the deterministic mock, the 'llm' strategies test the *architecture* (regime-conditioned playbook, Fed stance, "
         "constraint feedback), not a language model. Swap in a real endpoint to test the model.")
        if is_mock
        else "- The reasoning model is a real language model; its results on dates before its knowledge cutoff are upper bounds.",
        "- A real LLM evaluated before its knowledge cutoff can recall history; see `knowledge_cutoff` in the certificate and prefer "
        "the post-cutoff slice for inference.",
        "- Sharpe differences of a few hundredths are within noise for ten years of weekly data. The bootstrap p-values above say so.",
        "- Return attribution shows how much of any edge is just market beta or a duration bet.",
        "",
    ]
    L += ["Figures: `cumulative.png`, `weights_*.png`, `regimes.png`. Per-decision explanations: `decisions/*.json`, latest in `latest_decision.md`."]
    return "\n".join(L)
