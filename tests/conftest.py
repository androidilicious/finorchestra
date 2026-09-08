from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from finorchestra.config import load_config

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def cfg():
    return load_config(ROOT / "configs" / "default.yaml")


@pytest.fixture(scope="session")
def sigma(cfg):
    """A plausible annualized covariance for the universe, built from stylized vols and correlations."""
    t = cfg.market.tickers
    vol = pd.Series({"SPY": 0.16, "TLT": 0.14, "IEF": 0.06, "TIP": 0.06, "LQD": 0.07, "HYG": 0.09, "GLD": 0.15, "DBC": 0.18, "UUP": 0.07, "BIL": 0.003}).reindex(t)
    corr = pd.DataFrame(np.eye(len(t)), index=t, columns=t)
    pairs = {("SPY", "HYG"): 0.7, ("SPY", "LQD"): 0.2, ("SPY", "DBC"): 0.4, ("SPY", "TLT"): -0.3, ("SPY", "IEF"): -0.3, ("TLT", "IEF"): 0.9, ("TLT", "LQD"): 0.6, ("IEF", "TIP"): 0.7, ("TLT", "TIP"): 0.6, ("GLD", "UUP"): -0.4, ("GLD", "TIP"): 0.3, ("DBC", "UUP"): -0.4, ("HYG", "LQD"): 0.6}
    for (a, b), r in pairs.items():
        corr.loc[a, b] = corr.loc[b, a] = r
    S = corr.values * np.outer(vol.values, vol.values)
    # ensure PSD
    w, V = np.linalg.eigh(S)
    S = V @ np.diag(np.clip(w, 1e-6, None)) @ V.T
    return pd.DataFrame(S, index=t, columns=t)
