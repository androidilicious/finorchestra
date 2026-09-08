"""Command-line interface.

    finorchestra pull                      download / refresh all raw inputs
    finorchestra run                       full weekly backtest with the configured (default: mock) model
    finorchestra run --llm openai_compatible --model qwen2.5:3b --base-url http://localhost:11434/v1 --start 2025-01-03
    finorchestra decide --date 2024-03-15  one explained decision
    finorchestra leakage-check --date ...  prove the decision does not change when the future is deleted
    finorchestra data-summary              what is in the point-in-time store
"""

from __future__ import annotations

import logging

import typer
from rich import print as rprint

from .config import load_config
from .utils import setup_logging, to_date

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Finorchestra: macro signals -> constrained allocations, evaluated honestly.")


def _cfg(config: str, llm: str | None, model: str | None, base_url: str | None, start: str | None, end: str | None, name: str | None, strategies: str | None = None, knowledge_cutoff: str | None = None):
    ov: dict = {}
    if llm:
        ov["llm.provider"] = llm
    if model:
        ov["llm.model"] = model
    if base_url:
        ov["llm.base_url"] = base_url
    if knowledge_cutoff:
        ov["llm.knowledge_cutoff"] = knowledge_cutoff
    if start:
        ov["run.start"] = start
    if end:
        ov["run.end"] = end
    if name:
        ov["run.name"] = name
    if strategies:
        ov["evaluation.strategies"] = [s.strip() for s in strategies.split(",") if s.strip()]
    return load_config(config, ov)


@app.command()
def pull(config: str = "configs/default.yaml", force: bool = False) -> None:
    """Download or refresh FRED vintages, ETF prices, EPU/GPR indices and FOMC statements."""
    setup_logging(logging.INFO)
    from .data.fomc import FomcStore
    from .data.fred import FredStore
    from .data.market import MarketStore
    from .data.text_indices import TextIndexStore

    cfg = load_config(config)
    MarketStore(cfg).pull(force=force)
    TextIndexStore(cfg).pull(force=force)
    FomcStore(cfg).pull(force=force)
    fs = FredStore(cfg)
    fs.pull(force=force)
    rprint(fs.describe().to_string(index=False))


@app.command()
def run(
    config: str = "configs/default.yaml",
    llm: str | None = typer.Option(None, help="mock | openai_compatible"),
    model: str | None = None,
    base_url: str | None = None,
    start: str | None = None,
    end: str | None = None,
    name: str | None = None,
    strategies: str | None = typer.Option(None, help="comma-separated subset of rule,llm_clip,llm_feedback"),
    knowledge_cutoff: str | None = typer.Option(None, help="the model's documented training cutoff, YYYY-MM-DD; recorded in the certificate"),
) -> None:
    """Run the full weekly backtest and write outputs/runs/<run_id>/."""
    setup_logging(logging.INFO)
    from .data.pit import PointInTimeStore
    from .pipeline import Pipeline

    cfg = _cfg(config, llm, model, base_url, start, end, name, strategies, knowledge_cutoff)
    store = PointInTimeStore.load(cfg)
    pipe = Pipeline(cfg, store)
    summary = pipe.backtest()
    rprint(f"[bold green]done[/] run_id={summary['run_id']}")
    for n, m in summary["performance"].items():
        rprint(f"  {n:14s} Sharpe {m['sharpe']:.2f}  ann.ret {m['ann_return']:+.1%}  vol {m['ann_vol']:.1%}  maxDD {m['max_drawdown']:.1%}")
    rprint(f"report: {cfg.outputs_dir / 'runs' / summary['run_id'] / 'report.md'}")


@app.command()
def decide(
    date_: str = typer.Option(..., "--date", help="Decision date YYYY-MM-DD (a rebalance Friday, or the Friday before is used)"),
    config: str = "configs/default.yaml",
    llm: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    out: str | None = typer.Option(None, help="write the markdown explanation here"),
) -> None:
    """Produce and explain one decision."""
    setup_logging(logging.INFO)
    from .data.pit import PointInTimeStore
    from .explain.report import decision_markdown
    from .pipeline import Pipeline

    cfg = _cfg(config, llm, model, base_url, None, None, None)
    store = PointInTimeStore.load(cfg)
    pipe = Pipeline(cfg, store)
    dec = pipe.decide(to_date(date_), history=pipe.warmup_history(to_date(date_)))
    md = decision_markdown(dec.to_dict())
    if out:
        from pathlib import Path

        Path(out).write_text(md, encoding="utf-8")
        rprint(f"written {out}")
    else:
        print(md)


@app.command("leakage-check")
def leakage_check(
    date_: str = typer.Option(..., "--date"),
    config: str = "configs/default.yaml",
) -> None:
    """Assert the decision at --date is identical when all later data is physically removed."""
    setup_logging(logging.WARNING)
    from .data.pit import PointInTimeStore
    from .pipeline import Pipeline

    cfg = load_config(config)
    store = PointInTimeStore.load(cfg)
    ok, diffs = Pipeline(cfg, store).leakage_check(to_date(date_))
    if ok:
        rprint(f"[bold green]PASS[/] decision on {date_} is invariant to deleting all data published after it")
    else:
        rprint(f"[bold red]FAIL[/] {len(diffs)} differences:")
        for d in diffs[:20]:
            rprint("  " + d)
        raise typer.Exit(code=1)


@app.command()
def dashboard(
    run_dir: str = typer.Option(..., "--run-dir", help="a finished run directory, e.g. outputs/runs/mock-full-xxxx"),
    config: str = "configs/default.yaml",
) -> None:
    """Build (or rebuild) the interactive dashboard.html for a finished run."""
    setup_logging(logging.INFO)
    from pathlib import Path

    from .explain.dashboard import build_dashboard

    cfg = load_config(config)
    out = build_dashboard(Path(run_dir), cfg)
    rprint(f"dashboard written: {out}")


@app.command("data-summary")
def data_summary(config: str = "configs/default.yaml") -> None:
    """Describe the point-in-time store."""
    setup_logging(logging.WARNING)
    from .data.pit import PointInTimeStore

    cfg = load_config(config)
    store = PointInTimeStore.load(cfg)
    rprint(store.fred.describe().to_string(index=False))
    px = store.market.prices
    rprint(f"\nprices: {px.shape[0]} days x {px.shape[1]} tickers, {px.index.min().date()} .. {px.index.max().date()}")
    t = store.text.table
    rprint(f"text indices: {t.shape[0]} days, {t.index.min().date()} .. {t.index.max().date()}")
    f = store.fomc.docs
    rprint(f"FOMC statements: {len(f)}, {f['date'].min().date()} .. {f['date'].max().date()}")


if __name__ == "__main__":
    app()
