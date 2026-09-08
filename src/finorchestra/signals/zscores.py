"""Derived macro series and rolling, past-only z-scores.

A z-score at date d uses only observations with observation_date < d's latest observation, over a trailing
window. Because the input is an as-of snapshot, the values themselves are the ones published by d.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import DerivedCfg, SignalsCfg
from ..data.pit import Snapshot


def periods_per_year(index: pd.Index) -> float:
    """Snap the median spacing of a DatetimeIndex to a standard frequency (daily, weekly, monthly, quarterly, annual)."""
    if len(index) < 3:
        return 12.0
    spacing = float(np.median(np.diff(index.values).astype("timedelta64[D]").astype(float)))
    for days, ppy in ((1.0, 252.0), (7.0, 52.0), (30.4, 12.0), (91.3, 4.0), (365.25, 1.0)):
        if abs(spacing - days) / days < 0.2:
            return ppy
    return 365.25 / max(spacing, 1.0)


def derive(series: pd.Series, spec: DerivedCfg) -> pd.Series:
    s = series.dropna().astype(float)
    if spec.transform == "level":
        return s
    if spec.transform == "diff":
        return s.diff(spec.periods).dropna()
    if spec.transform == "pct_change":
        return s.pct_change(spec.periods).dropna()
    if spec.transform == "pct_change_annualized":
        per_year = periods_per_year(s.index)
        r = s.pct_change(spec.periods).dropna()
        return (1.0 + r) ** (per_year / spec.periods) - 1.0
    raise ValueError(spec.transform)


def rolling_z_last(series: pd.Series, window_years: int, min_years: int, clip: float) -> float | None:
    """z-score of the last observation against the trailing window that ends *before* it."""
    s = series.dropna()
    if len(s) < 3:
        return None
    last_date = s.index[-1]
    start = last_date - pd.DateOffset(years=window_years)
    hist = s.loc[(s.index >= start) & (s.index < last_date)]
    span_years = (last_date - hist.index.min()).days / 365.25 if len(hist) else 0.0
    if len(hist) < 12 or span_years < min_years:
        return None
    sd = float(hist.std(ddof=1))
    if not np.isfinite(sd) or sd <= 1e-12:
        return None
    z = (float(s.iloc[-1]) - float(hist.mean())) / sd
    return float(np.clip(z, -clip, clip))


@dataclass
class SignalSet:
    as_of: str
    raw_latest: dict[str, float]  # derived series latest values
    z: dict[str, float]  # derived series z-scores
    themes: dict[str, float]  # theme composites (mean of signed z)
    text_index_z: dict[str, float]  # epu, gpr, gpr_threat, gpr_act z-scores
    text_index_latest: dict[str, float]

    def as_frame(self) -> pd.DataFrame:
        rows = [("theme", k, v) for k, v in self.themes.items()]
        rows += [("macro_z", k, v) for k, v in self.z.items()]
        rows += [("text_index_z", k, v) for k, v in self.text_index_z.items()]
        return pd.DataFrame(rows, columns=["group", "signal", "value"])


def build_signals(snap: Snapshot, cfg: SignalsCfg) -> SignalSet:
    raw_latest: dict[str, float] = {}
    z: dict[str, float] = {}
    for name, spec in cfg.derived.items():
        src = snap.macro.get(spec.source)
        if src is None or src.empty:
            continue
        d = derive(src, spec)
        if d.empty:
            continue
        raw_latest[name] = float(d.iloc[-1])
        zz = rolling_z_last(d, cfg.zscore_window_years, cfg.min_history_years, cfg.clip)
        if zz is not None:
            z[name] = zz

    themes: dict[str, float] = {}
    for tname, t in cfg.themes.items():
        vals = [sgn * z[s] for s, sgn in zip(t.series, t.signs, strict=True) if s in z]
        if vals:
            themes[tname] = float(np.mean(vals))

    tz: dict[str, float] = {}
    tl: dict[str, float] = {}
    ti = snap.text_indices
    if ti is not None and not ti.empty:
        # daily indices are noisy: use a trailing 21-observation mean as the "current" reading. The EPU/GPR
        # files are calendar-daily (weekends included), so 21 rows is about three calendar weeks, not a trading month.
        for col in ti.columns:
            s = ti[col].dropna()
            if len(s) < 300:
                continue
            smooth = s.rolling(21, min_periods=10).mean().dropna()
            tl[col] = float(smooth.iloc[-1])
            zz = rolling_z_last(smooth, cfg.zscore_window_years, cfg.min_history_years, cfg.clip)
            if zz is not None:
                tz[col] = zz
    return SignalSet(str(snap.as_of), raw_latest, z, themes, tz, tl)
