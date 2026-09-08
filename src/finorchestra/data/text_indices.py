"""Research-constructed text indices: EPU (Baker, Bloom, Davis) and GPR (Caldara, Iacoviello).

Both are daily newspaper-count indices published by their authors and mirrored (EPU) on FRED. They are not
revised in the way official statistics are, but they are published with a short lag and occasionally
backfilled when newspaper archives change. We treat each observation as available `lag_days` business
days after its date and record in the certificate that these are latest-vintage series.

Convention: "business days after" counts Mon-Fri forward from the observation date and ignores holidays, so a
Sunday-dated observation with lag 2 is usable from Tuesday. On every rebalance Friday this means nothing newer
than the Wednesday two business days earlier.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from ..config import Config
from ..utils import LOG, add_business_days, ensure_dir
from .fred import FRED_GRAPH, _get, _parse_graph_csv


class TextIndexStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = ensure_dir(cfg.raw_dir / "epu")
        self.epu_path: Path = self.dir / f"{cfg.text_indices.epu_daily_series}.csv"
        self.gpr_path: Path = cfg.root / cfg.text_indices.gpr_daily_file
        self.table: pd.DataFrame | None = None  # columns: epu, gpr, gpr_threat, gpr_act ; index: date ; + available_from

    def pull(self, force: bool = False) -> None:
        sid = self.cfg.text_indices.epu_daily_series
        if force or not self.epu_path.exists() or (date.today() - self._last_date(self.epu_path)).days > 7:
            LOG.info("EPU: downloading %s from FRED", sid)
            self.epu_path.write_text(_get(FRED_GRAPH, {"id": sid}), encoding="utf-8")
        if not self.gpr_path.exists():
            LOG.info("GPR: downloading daily file")
            import requests

            r = requests.get(
                "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls", timeout=120
            )
            r.raise_for_status()
            ensure_dir(self.gpr_path.parent)
            self.gpr_path.write_bytes(r.content)

    @staticmethod
    def _last_date(p: Path) -> date:
        try:
            df = pd.read_csv(p)
            return pd.to_datetime(df.iloc[-1, 0]).date()
        except Exception:
            return date(1900, 1, 1)

    def load(self) -> TextIndexStore:
        epu = _parse_graph_csv(self.epu_path.read_text(encoding="utf-8"))
        epu = epu.set_index("observation_date").iloc[:, 0].rename("epu")
        epu_avail = pd.Series(
            [pd.Timestamp(add_business_days(d.date(), self.cfg.text_indices.epu_lag_days)) for d in epu.index],
            index=epu.index,
        )

        g = pd.read_excel(self.gpr_path)
        g["date"] = pd.to_datetime(g["DAY"].astype(int).astype(str), format="%Y%m%d")
        g = g.set_index("date")[["GPRD", "GPRD_THREAT", "GPRD_ACT"]]
        g.columns = ["gpr", "gpr_threat", "gpr_act"]
        gpr_avail = pd.Series(
            [pd.Timestamp(add_business_days(d.date(), self.cfg.text_indices.gpr_lag_days)) for d in g.index],
            index=g.index,
        )

        table = pd.concat([epu, g], axis=1).sort_index()
        avail = pd.concat([epu_avail.rename("a1"), gpr_avail.rename("a2")], axis=1).max(axis=1)
        table["available_from"] = avail.reindex(table.index)
        self.table = table
        return self

    def as_of(self, d: date) -> pd.DataFrame:
        assert self.table is not None
        t = self.table
        return t.loc[t["available_from"] <= pd.Timestamp(d)].drop(columns="available_from")

    def truncated(self, d: date) -> TextIndexStore:
        other = TextIndexStore.__new__(TextIndexStore)
        other.cfg, other.dir, other.epu_path, other.gpr_path = self.cfg, self.dir, self.epu_path, self.gpr_path
        t = self.table
        other.table = t.loc[t["available_from"] <= pd.Timestamp(d)].copy()
        return other
