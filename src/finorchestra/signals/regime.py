"""Growth x inflation regime estimate with empirical quadrant probabilities.

Quadrants (growth momentum, inflation momentum):
    goldilocks   : growth up,   inflation down
    overheating  : growth up,   inflation up
    stagflation  : growth down, inflation up
    recession    : growth down, inflation down

"Up" means the theme composite is above its own past-only history. P(growth up) is the empirical percentile of
today's growth theme within that history (the fraction of past readings at or below today's), and the two axes
are treated as independent. There is no tuning parameter: the only input is the history itself, which the pipeline
builds from dates strictly before the decision date. When no history is available (a stand-alone decision), the
percentile is taken from the standard normal CDF, which is what a z-scored composite would imply.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import erf, sqrt

import numpy as np
import pandas as pd

QUADRANTS = ("goldilocks", "overheating", "stagflation", "recession")
MIN_HISTORY = 52  # weeks of theme history before the empirical percentile replaces the normal-CDF fallback


@dataclass
class RegimeEstimate:
    label: str
    probabilities: dict[str, float]
    growth: float
    inflation: float
    method: str = "empirical"

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "probabilities": self.probabilities,
            "growth_composite": self.growth,
            "inflation_composite": self.inflation,
            "method": self.method,
        }


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _percentile(x: float, history: pd.Series | None) -> tuple[float, str]:
    if history is not None:
        h = pd.Series(history).dropna().astype(float)
        if len(h) >= MIN_HISTORY:
            # mid-rank percentile: ties count half, so a value equal to the whole history reads as 0.5
            p = (float((h < x).sum()) + 0.5 * float((h == x).sum()) + 0.5) / (len(h) + 1.0)
            return float(np.clip(p, 0.0, 1.0)), "empirical"
    return _normal_cdf(x), "normal_cdf_fallback"


def estimate_regime(themes: dict[str, float], history: pd.DataFrame | None = None) -> RegimeEstimate:
    """`history` holds past theme composites (columns growth, inflation), strictly before the decision date."""
    g = float(themes.get("growth", 0.0))
    i = float(themes.get("inflation", 0.0))
    hg = history["growth"] if history is not None and "growth" in history else None
    hi = history["inflation"] if history is not None and "inflation" in history else None
    p_g_up, m1 = _percentile(g, hg)
    p_i_up, m2 = _percentile(i, hi)
    probs = {
        "goldilocks": p_g_up * (1 - p_i_up),
        "overheating": p_g_up * p_i_up,
        "stagflation": (1 - p_g_up) * p_i_up,
        "recession": (1 - p_g_up) * (1 - p_i_up),
    }
    label = max(probs, key=probs.get)
    method = "empirical" if m1 == m2 == "empirical" else "normal_cdf_fallback"
    return RegimeEstimate(label, {k: round(v, 4) for k, v in probs.items()}, g, i, method)
