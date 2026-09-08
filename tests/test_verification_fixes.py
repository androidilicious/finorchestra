"""Regression tests for defects found by the claim re-verification (2026-09-07)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from finorchestra.config import FredSeriesCfg
from finorchestra.data.fred import FAR_FUTURE, FredStore
from finorchestra.evaluation import metrics as M
from finorchestra.views.masking import Masker


def test_turnover_charges_the_initial_trade():
    w = pd.DataFrame({"SPY": [0.6, 0.6, 0.5], "BIL": [0.4, 0.4, 0.5]})
    to = M.turnover_series(w, cash="BIL")
    assert abs(to.iloc[0] - 0.6) < 1e-12  # from 100% cash into 60% SPY
    assert to.iloc[1] == 0.0 and abs(to.iloc[2] - 0.1) < 1e-12
    to2 = M.turnover_series(w)
    assert abs(to2.iloc[0] - 0.5) < 1e-12  # empty book convention


def test_attribution_shares_sum_to_one_and_residual_is_one_minus_r2():
    rng = np.random.default_rng(3)
    idx = pd.date_range("2015-01-09", periods=400, freq="W-FRI")
    f = pd.DataFrame({"MKT": rng.normal(0.001, 0.02, 400), "DUR": rng.normal(0, 0.015, 400)}, index=idx)
    f["DUR"] = f["DUR"] + 0.3 * f["MKT"]  # correlated factors, so the covariance term is non-zero
    y = 0.8 * f["MKT"] - 0.4 * f["DUR"] + pd.Series(rng.normal(0.0005, 0.004, 400), index=idx)
    a = M.attribution(y, f)
    total = a.share_market + a.share_style + a.share_covariance + a.share_residual
    assert abs(total - 1.0) < 1e-9
    assert abs(a.share_residual - (1 - a.r2)) < 1e-9
    assert abs(a.share_covariance) > 1e-3


def test_deflated_sharpe_dispersion_is_disclosed_and_matters():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0.002, 0.01, 400), index=pd.date_range("2015-01-09", periods=400, freq="W-FRI"))
    d_small = M.deflated_sharpe(r, 5, sr_dispersion_annual=0.1)
    d_big = M.deflated_sharpe(r, 5, sr_dispersion_annual=1.0)
    assert d_big["sr0_annual"] > d_small["sr0_annual"]
    assert d_big["deflated_sharpe_prob"] < d_small["deflated_sharpe_prob"]
    assert d_big["sr_dispersion_annual_assumed"] == 1.0


def test_masker_rounds_fractional_rate_ranges():
    m = Masker.build([], enabled=True)
    out = m.mask_text("maintain the target range for the federal funds rate at 5-1/4 to 5-1/2 percent")
    assert "about 5 to 5.5 percent" in out  # a range is widened outward, never collapsed to a point
    move = m.mask_text("raise the target range by 1/4 percentage point to 5-1/4 to 5-1/2 percent")
    assert "1/4 percentage point" in move and "about 5 to 5.5 percent" in move  # move sizes are not rounded
    out3 = m.mask_text("maintain the target range at 3‑1/2 to 3–3/4 percent")  # non-breaking hyphen, en dash
    assert "about 3.5 to 4 percent" in out3 and "1/2" not in out3
    out2 = m.mask_text("inflation of 2 percent and a rate of 4.75 percent, or 1/2 percent")
    assert "about 2 percent" in out2 and "about 5 percent" in out2 and "about 0.5 percent" in out2
    assert "4.75" not in out2


def test_fomc_mojibake_repair():
    from finorchestra.data.fomc import repair_mojibake

    garbled = "3â€‘1/2 to 3â€‘3/4 percent and the Committeeâ€™s goals"
    assert repair_mojibake(garbled) == "3‑1/2 to 3‑3/4 percent and the Committee’s goals"
    clean = "Inflation remains elevated."
    assert repair_mojibake(clean) is clean


def test_fred_availability_lag_delays_unrevised_series(cfg):
    fs = FredStore.__new__(FredStore)
    fs.cfg = cfg.model_copy(update={"fred": cfg.fred.model_copy(update={"series": [FredSeriesCfg(id="X", name="x", revised=False, lag_days=1)]})})
    fs.modes = {"X": "latest_unrevised"}
    fs.dir = None
    obs = pd.to_datetime(["2024-03-14", "2024-03-15"])  # Thu, Fri
    fs.tables = {"X": pd.DataFrame({"observation_date": obs, "value": [1.0, 2.0], "realtime_start": obs, "realtime_end": [FAR_FUTURE, FAR_FUTURE]})}
    fs._finalize()
    fri = pd.Timestamp("2024-03-15").date()
    assert fs.as_of("X", fri).index.max() == pd.Timestamp("2024-03-14")  # Friday's print is not usable on Friday
    assert fs.as_of("X", pd.Timestamp("2024-03-18").date()).index.max() == pd.Timestamp("2024-03-15")  # Monday
    assert len(fs.truncated(fri).tables["X"]) == 1


def test_mock_cap_handler_matches_whole_asset_codes_only():
    """'single-asset cap' contains the substring 'asset c'; only the named asset (D) may be halved, never Asset C."""
    from finorchestra.llm.mock import MockLLM

    m = MockLLM()
    assets = {"Asset C": "intermediate government bonds (7-10y)", "Asset D": "inflation-protected government bonds"}
    views = [
        {"asset": "Asset C", "direction": "overweight", "expected_excess_return_annual": 0.02, "confidence": 0.6, "evidence": []},
        {"asset": "Asset D", "direction": "overweight", "expected_excess_return_annual": 0.04, "confidence": 0.8, "evidence": []},
    ]
    out = m._apply_violations("- Asset D (inflation-protected government bonds) is pinned at its single-asset cap of about 30 percent; the views asked for more", views, assets)
    by = {v["asset"]: v for v in out}
    assert by["Asset D"]["expected_excess_return_annual"] == 0.02  # halved
    assert by["Asset C"]["expected_excess_return_annual"] == 0.02  # untouched


def test_constant_correlation_shrinkage_keeps_variances_and_is_psd():
    """Ledoit-Wolf constant-correlation: each fund keeps its own sample variance (cash stays near-riskless), the
    intensity lies in [0, 1], the result is symmetric PSD, and correlations move toward their average."""
    from finorchestra.data.market import ledoit_wolf_constant_correlation

    rng = np.random.default_rng(5)
    T = 104
    f = rng.normal(0, 0.02, T)
    r = pd.DataFrame({"A": f + rng.normal(0, 0.01, T), "B": 0.5 * f + rng.normal(0, 0.01, T), "C": rng.normal(0, 0.003, T), "CASH": rng.normal(0, 0.0001, T)})
    sigma, delta = ledoit_wolf_constant_correlation(r)
    assert 0.0 <= delta <= 1.0
    sample_var = r.var(ddof=0) * 52.0
    for c in r.columns:
        assert abs(sigma.loc[c, c] - sample_var[c]) < 1e-12  # variances are untouched by the target
    assert np.sqrt(sigma.loc["CASH", "CASH"]) < 0.005  # cash is not inflated toward the average variance
    w, _ = np.linalg.eigh(sigma.values)
    assert w.min() >= -1e-12 and np.allclose(sigma.values, sigma.values.T)
    corr_s = r.corr().values
    sd = np.sqrt(np.diag(sigma.values))
    corr_lw = sigma.values / np.outer(sd, sd)
    r_bar = (corr_s.sum() - 4) / 12
    off = ~np.eye(4, dtype=bool)
    assert (np.abs(corr_lw[off] - r_bar) <= np.abs(corr_s[off] - r_bar) + 1e-12).all()  # pulled toward the mean correlation
