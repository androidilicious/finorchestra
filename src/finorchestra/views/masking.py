"""Prompt masking against knowledge-cutoff contamination.

Tickers become "Asset A/B/...", calendar dates become relative offsets ("t-3 weeks"), and specific
numbers that could trigger recall (e.g. "5.25 percent") are rounded inside retrieved text. Masking cannot
make a model forget history; it removes the easiest hooks for recall and is reported in the certificate.
"""

from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass

from ..config import AssetCfg

_DATE_PATTERNS = [
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b"),
    re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b"),
    re.compile(r"\b(19|20)\d{2}\b"),
]
_DASH = "-‐‑‒–—―"  # ASCII hyphen plus the Unicode hyphens/dashes Fed statements use
_NUM = rf"(?:\d+[{_DASH}]\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"  # 5-1/4  |  1/2  |  5.25  |  5
# "percent\b" so that "1/4 percentage point" (a move size) is left alone: rounding it to 0.5 would turn a
# quarter-point move into a half-point one.
_PCT = re.compile(rf"({_NUM})(?:\s+to\s+({_NUM}))?\s*(?:percent\b|%)")


def _to_float(s: str) -> float:
    s = re.sub(f"[{_DASH}]", "-", s)
    if "-" in s and "/" in s:
        whole, frac = s.split("-")
        a, b = frac.split("/")
        return int(whole) + int(a) / int(b)
    if "/" in s:
        a, b = s.split("/")
        return int(a) / int(b)
    return float(s)


def _half(v: float) -> str:
    return f"{math.floor(v * 2 + 0.5) / 2:g}"


def _half_down(v: float) -> str:
    return f"{math.floor(v * 2) / 2:g}"


def _half_up(v: float) -> str:
    return f"{math.ceil(v * 2) / 2:g}"


def _mask_pct(m: re.Match) -> str:
    """Round a level to the nearest 0.5 point. A range is widened outward (floor the low end, ceil the high
    end) so that "5-1/4 to 5-1/2 percent" becomes "about 5 to 5.5 percent" rather than collapsing to a point."""
    try:
        if m.group(2):
            return f"about {_half_down(_to_float(m.group(1)))} to {_half_up(_to_float(m.group(2)))} percent"
        return f"about {_half(_to_float(m.group(1)))} percent"
    except (ValueError, ZeroDivisionError):
        return m.group(0)


@dataclass
class Masker:
    enabled: bool
    forward: dict[str, str]  # ticker -> code
    backward: dict[str, str]  # code -> ticker
    labels: dict[str, str]  # code -> plain-language description

    @classmethod
    def build(cls, universe: list[AssetCfg], enabled: bool = True) -> Masker:
        fwd, bwd, labels = {}, {}, {}
        for i, a in enumerate(universe):
            code = f"Asset {string.ascii_uppercase[i]}" if enabled else a.ticker
            fwd[a.ticker] = code
            bwd[code] = a.ticker
            labels[code] = a.label
        return cls(enabled, fwd, bwd, labels)

    def code(self, ticker: str) -> str:
        return self.forward.get(ticker, ticker)

    def ticker(self, code: str) -> str:
        if code in self.backward:
            return self.backward[code]
        # tolerate "Asset A (broad domestic equities)" or lowercase variations
        key = code.strip().split("(")[0].strip().title()
        return self.backward.get(key, code.strip().upper())

    def mask_text(self, text: str) -> str:
        if not self.enabled:
            return text
        for pat in _DATE_PATTERNS:
            text = pat.sub("[date]", text)
        text = _PCT.sub(_mask_pct, text)
        for t, c in self.forward.items():
            text = re.sub(rf"\b{re.escape(t)}\b", c, text)
        return text

    def asset_table(self) -> str:
        return "\n".join(f"- {c}: {self.labels[c]}" for c in self.backward)


