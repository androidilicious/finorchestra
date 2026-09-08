"""Integration tests against the real point-in-time store. Skipped when the data has not been pulled."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from finorchestra.config import load_config

ROOT = Path(__file__).resolve().parents[1]


def _store_or_skip():
    cfg = load_config(ROOT / "configs" / "default.yaml")
    from finorchestra.data.pit import PointInTimeStore

    try:
        return cfg, PointInTimeStore.load(cfg)
    except FileNotFoundError as e:
        pytest.skip(f"raw data not pulled: {e}")


@pytest.mark.integration
def test_snapshot_only_contains_knowable_data():
    cfg, store = _store_or_skip()
    d = pd.Timestamp("2020-05-01").date()
    snap = store.snapshot(d)
    ur = snap.macro["unemployment_rate"]
    # April 2020 unemployment (14.7%) was released 2020-05-08: must NOT be visible on 2020-05-01
    assert ur.index.max() <= pd.Timestamp("2020-03-01")
    assert snap.prices.index.max().date() <= d
    assert (snap.fomc["date"] <= pd.Timestamp(d)).all()
    assert snap.text_indices.index.max().date() <= d


@pytest.mark.integration
def test_vintage_revision_is_visible_in_store():
    cfg, store = _store_or_skip()
    early = store.fred.as_of("PAYEMS", pd.Timestamp("2020-06-12").date())
    late = store.fred.as_of("PAYEMS", pd.Timestamp("2021-06-11").date())
    common = early.index.intersection(late.index)
    common = common[common >= "2019-01-01"]
    assert (early.loc[common] != late.loc[common]).any(), "payrolls should have been revised between 2020 and 2021"


@pytest.mark.integration
def test_decision_is_invariant_to_deleting_the_future():
    cfg, store = _store_or_skip()
    from finorchestra.pipeline import Pipeline

    ok, diffs = Pipeline(cfg, store).leakage_check(pd.Timestamp("2022-06-17").date())
    assert ok, diffs[:10]


@pytest.mark.integration
def test_short_backtest_runs_end_to_end(tmp_path):
    cfg, store = _store_or_skip()
    cfg = load_config(ROOT / "configs" / "default.yaml", {"run.start": "2023-01-06", "run.end": "2023-03-31", "run.name": "pytest", "evaluation.bootstrap_draws": 100})
    from finorchestra.pipeline import Pipeline

    summary = Pipeline(cfg, store).backtest(run_dir=tmp_path)
    assert (tmp_path / "report.md").exists() and (tmp_path / "certificate.json").exists()
    for name in ("rule", "llm_clip", "llm_feedback", "benchmark", "sixty_forty"):
        assert name in summary["performance"]
    w = pd.read_csv(tmp_path / "weights_llm_feedback.csv", index_col=0)
    assert ((w.sum(axis=1) - 1).abs() < 1e-3).all()
    assert (w >= -1e-6).all().all()
