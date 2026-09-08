from __future__ import annotations

import numpy as np
import pandas as pd

from finorchestra.evaluation import metrics as M
from finorchestra.evaluation.leakage import outputs_identical


def _series(mean, sd, n=400, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2015-01-09", periods=n, freq="W-FRI")
    return pd.Series(rng.normal(mean, sd, n), index=idx)


def test_sharpe_and_costs():
    r = _series(0.002, 0.01)
    to = pd.Series(0.2, index=r.index)
    s0 = M.sharpe(r)
    s30 = M.sharpe(M.net_returns(r, to, 30))
    assert s30 < s0
    assert abs((M.net_returns(r, to, 10) - r).mean() + 0.2 * 10 / 1e4) < 1e-12


def test_deflated_sharpe_decreases_with_trials():
    r = _series(0.002, 0.01)
    d1 = M.deflated_sharpe(r, 1)
    d50 = M.deflated_sharpe(r, 50)
    assert d50["deflated_sharpe_prob"] < d1["deflated_sharpe_prob"]
    assert d1["sr0_annual"] == 0.0 and d50["sr0_annual"] > 0


def test_bootstrap_diff_detects_large_gap_and_not_none():
    a = _series(0.004, 0.01, seed=1)
    b = _series(0.000, 0.01, seed=2)
    res = M.block_bootstrap_sharpe_diff(a, b, block=8, draws=400)
    assert res["diff"] > 0 and res["p_value"] < 0.05
    same = M.block_bootstrap_sharpe_diff(a, a, block=8, draws=200)
    assert abs(same["diff"]) < 1e-12


def test_attribution_recovers_beta():
    f = pd.DataFrame({"MKT": _series(0.001, 0.02, seed=3), "DUR": _series(0.0, 0.015, seed=4)})
    y = 0.8 * f["MKT"] - 0.2 * f["DUR"] + _series(0.0005, 0.003, seed=5)
    a = M.attribution(y, f)
    assert abs(a.betas["MKT"] - 0.8) < 0.05 and abs(a.betas["DUR"] + 0.2) < 0.05
    assert a.share_market > a.share_style > 0


def test_max_drawdown_and_turnover():
    r = pd.Series([0.1, -0.5, 0.2])
    assert abs(M.max_drawdown(r) + 0.5) < 1e-12
    w = pd.DataFrame({"A": [1.0, 0.5, 0.5], "B": [0.0, 0.5, 0.5]})
    to = M.turnover_series(w)
    assert abs(to.iloc[1] - 0.5) < 1e-12 and to.iloc[2] == 0


def test_outputs_identical_tolerates_float_noise_and_flags_real_diffs():
    a = {"x": 1.0, "y": [1, 2, {"z": "a"}], "timestamp": "t1"}
    b = {"x": 1.0 + 1e-12, "y": [1, 2, {"z": "a"}], "timestamp": "t2"}
    assert outputs_identical(a, b)[0]
    c = {"x": 1.1, "y": [1, 2, {"z": "a"}]}
    ok, diffs = outputs_identical(a, c)
    assert not ok and any("x" in d for d in diffs)
