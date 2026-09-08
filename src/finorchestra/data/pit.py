"""The point-in-time store: the only door through which the rest of the system sees data.

`PointInTimeStore.snapshot(d)` returns everything that was knowable at the close of date d, and nothing
else. Every downstream component takes a Snapshot, never a raw table. `truncated(d)` builds a store that
physically lacks anything published after d; the leakage test asserts that decisions made from the full
store and from the truncated store are identical.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from ..config import Config
from .fomc import FomcStore
from .fred import FredStore
from .market import MarketStore
from .text_indices import TextIndexStore


@dataclass
class Snapshot:
    as_of: date
    macro: dict[str, pd.Series]  # name -> series indexed by observation_date, as published on as_of
    text_indices: pd.DataFrame  # epu, gpr, gpr_threat, gpr_act by date
    prices: pd.DataFrame  # adjusted closes up to as_of
    fomc: pd.DataFrame  # statements available by as_of

    def latest_macro(self) -> dict[str, float]:
        return {k: float(v.iloc[-1]) for k, v in self.macro.items() if len(v)}


class PointInTimeStore:
    def __init__(self, cfg: Config, fred: FredStore, market: MarketStore, text: TextIndexStore, fomc: FomcStore):
        self.cfg = cfg
        self.fred, self.market, self.text, self.fomc = fred, market, text, fomc

    @classmethod
    def load(cls, cfg: Config) -> PointInTimeStore:
        return cls(
            cfg,
            FredStore(cfg).load(),
            MarketStore(cfg).load(),
            TextIndexStore(cfg).load(),
            FomcStore(cfg).load(),
        )

    def snapshot(self, d: date) -> Snapshot:
        return Snapshot(
            as_of=d,
            macro=self.fred.snapshot(d),
            text_indices=self.text.as_of(d),
            prices=self.market.prices_as_of(d),
            fomc=self.fomc.as_of(d),
        )

    def truncated(self, d: date) -> PointInTimeStore:
        return PointInTimeStore(
            self.cfg, self.fred.truncated(d), self.market.truncated(d), self.text.truncated(d), self.fomc.truncated(d)
        )

    def last_price_date(self) -> date:
        assert self.market.prices is not None
        return self.market.prices.index.max().date()
