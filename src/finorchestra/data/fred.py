"""FRED / ALFRED loader with real-time (vintage) reconstruction.

Every observation is stored as an interval:

    observation_date | value | realtime_start | realtime_end

meaning "between realtime_start (inclusive) and realtime_end (exclusive), the published value for
observation_date was `value`". Asking for the data *as of* a date D is then a filter:
realtime_start <= D < realtime_end. This is the same representation the FRED API uses, so both the API path
(with a key) and the keyless ALFRED graph path produce identical tables.

Keyless path: the ALFRED graph endpoint accepts several vintage dates per call. We request the series as
published on every rebalance Friday since `vintage_start`, then collapse consecutive identical vintages
into intervals. realtime_start is therefore the first Friday on which a value was visible, which is at most
six days after the true release: conservative (we never know things early), never leaky.

Series flagged `revised: false` (market-determined daily series such as yields) are fetched once with
realtime_start = observation_date and an open-ended realtime_end.
"""

from __future__ import annotations

import io
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from ..config import Config, FredSeriesCfg
from ..utils import LOG, ensure_dir, fridays_between, to_date

FRED_GRAPH = "https://fred.stlouisfed.org/graph/fredgraph.csv"
ALFRED_GRAPH = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"
FAR_FUTURE = pd.Timestamp("2262-04-11")  # pandas max
FAR_FUTURE_DATE = date(2262, 4, 11)

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "finorchestra/0.1 (academic research; point-in-time macro data)"


def _get(url: str, params: dict | None = None, retries: int = 4) -> str:
    for attempt in range(retries):
        try:
            r = _SESSION.get(url, params=params, timeout=90)
            if r.status_code == 200 and r.text.strip():
                return r.text
            LOG.warning("HTTP %s from %s (attempt %d)", r.status_code, url, attempt + 1)
        except requests.RequestException as e:  # pragma: no cover - network
            LOG.warning("request failed: %s (attempt %d)", e, attempt + 1)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}")


def _parse_graph_csv(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df = df.rename(columns={df.columns[0]: "observation_date"})
    df["observation_date"] = pd.to_datetime(df["observation_date"])
    for c in df.columns[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# --------------------------------------------------------------------------------------------------
# Keyless ALFRED path
# --------------------------------------------------------------------------------------------------
ALFRED_MAX_PER_CALL = 12  # the graph endpoint silently truncates longer requests


def fetch_alfred_vintages(series_id: str, vintage_dates: list[date], chunk: int = ALFRED_MAX_PER_CALL) -> pd.DataFrame:
    """Wide frame: observation_date x vintage_date -> value, via the ALFRED graph endpoint.

    Raises if any requested vintage is missing from the response: a silently dropped vintage would make a
    release look later than it was, which biases every downstream signal toward staleness.
    """
    chunk = min(chunk, ALFRED_MAX_PER_CALL)
    frames = []
    for i in range(0, len(vintage_dates), chunk):
        vd = vintage_dates[i : i + chunk]
        params = {"id": ",".join([series_id] * len(vd)), "vintage_date": ",".join(d.isoformat() for d in vd)}
        text = _get(ALFRED_GRAPH, params)
        df = _parse_graph_csv(text).set_index("observation_date")
        df.columns = [pd.Timestamp(c.split("_")[-1]) for c in df.columns]
        got = {c.date() for c in df.columns}
        missing = [d for d in vd if d not in got]
        if missing:
            raise RuntimeError(f"ALFRED returned {len(got)}/{len(vd)} vintages for {series_id}; missing {missing[:3]}...")
        frames.append(df)
        LOG.debug("%s: fetched vintages %s..%s", series_id, vd[0], vd[-1])
    wide = pd.concat(frames, axis=1)
    wide = wide.loc[:, ~wide.columns.duplicated()].sort_index(axis=1)
    return wide


def wide_vintages_to_intervals(wide: pd.DataFrame) -> pd.DataFrame:
    """Collapse a wide vintage matrix into (observation_date, value, realtime_start, realtime_end) rows."""
    rows = []
    vintages = list(wide.columns)
    for obs_date, row in wide.iterrows():
        prev_val = None
        start = None
        for v in vintages:
            val = row[v]
            is_nan = pd.isna(val)
            if is_nan:
                if prev_val is not None:
                    rows.append((obs_date, prev_val, start, v))
                    prev_val, start = None, None
                continue
            if prev_val is None:
                prev_val, start = val, v
            elif val != prev_val:
                rows.append((obs_date, prev_val, start, v))
                prev_val, start = val, v
        if prev_val is not None:
            rows.append((obs_date, prev_val, start, FAR_FUTURE))
    out = pd.DataFrame(rows, columns=["observation_date", "value", "realtime_start", "realtime_end"])
    return out.sort_values(["observation_date", "realtime_start"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------------------
# API path (optional key)
# --------------------------------------------------------------------------------------------------
def fetch_api_intervals(series_id: str, api_key: str, realtime_start: str = "1776-07-04") -> pd.DataFrame:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": realtime_start,
        "realtime_end": "9999-12-31",
        "limit": 100000,
    }
    rows = []
    offset = 0
    while True:
        params["offset"] = offset
        r = _SESSION.get(FRED_API, params=params, timeout=90)
        r.raise_for_status()
        js = r.json()
        for o in js["observations"]:
            val = pd.to_numeric(o["value"], errors="coerce")
            if pd.isna(val):
                continue
            end = o["realtime_end"]
            rows.append(
                (
                    pd.Timestamp(o["date"]),
                    float(val),
                    pd.Timestamp(o["realtime_start"]),
                    FAR_FUTURE if end.startswith("9999") else pd.Timestamp(end),
                )
            )
        offset += js["limit"]
        if offset >= js["count"]:
            break
    return pd.DataFrame(rows, columns=["observation_date", "value", "realtime_start", "realtime_end"])


def fetch_latest(series_id: str) -> pd.DataFrame:
    """Latest-vintage series as intervals with realtime_start = observation_date (for unrevised series)."""
    df = _parse_graph_csv(_get(FRED_GRAPH, {"id": series_id})).dropna()
    df.columns = ["observation_date", "value"]
    df["realtime_start"] = df["observation_date"]
    df["realtime_end"] = FAR_FUTURE
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------------------
class FredStore:
    """Point-in-time FRED data for the configured series, cached on disk."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = ensure_dir(cfg.raw_dir / "fred" / "vintages")
        self.tables: dict[str, pd.DataFrame] = {}
        self.modes: dict[str, str] = {}

    def _path(self, sid: str) -> Path:
        return self.dir / f"{sid}.parquet"

    @staticmethod
    def _save(df: pd.DataFrame, path: Path) -> Path:
        """Parquet when an engine is available, CSV otherwise. Returns the path actually written."""
        try:
            df.to_parquet(path, index=False)
            return path
        except ImportError:
            alt = path.with_suffix(".csv")
            df.to_csv(alt, index=False)
            return alt

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if path.exists():
            return pd.read_parquet(path)
        alt = path.with_suffix(".csv")
        df = pd.read_csv(alt, parse_dates=["observation_date", "realtime_start", "realtime_end"])
        return df

    def _exists(self, sid: str) -> bool:
        p = self._path(sid)
        return p.exists() or p.with_suffix(".csv").exists()

    def pull(self, force: bool = False, end: date | None = None) -> None:
        end = end or date.today()
        api_key = os.environ.get(self.cfg.fred.api_key_env) or None
        for s in self.cfg.fred.series:
            self._pull_one(s, api_key, end, force)
        self._finalize()

    def _lag_for(self, sid: str) -> int:
        return next((s.lag_days for s in self.cfg.fred.series if s.id == sid), 0)

    def _finalize(self) -> None:
        """Add `available_from` = realtime_start shifted by the series' availability lag (Mon-Fri business days).

        For revised series realtime_start is already the first Friday vintage in which a value appeared, so the lag is
        normally 0. For unrevised daily market series it is the observation date, and a lag of one business day
        reflects that H.15 yields and index closes are posted the following day. This is the column every as-of
        query uses; realtime_start is kept as the raw publication record.
        """
        for sid, t in list(self.tables.items()):
            if "available_from" in t.columns:
                continue
            lag = self._lag_for(sid)
            t = t.copy()
            t["available_from"] = t["realtime_start"] + pd.offsets.BusinessDay(lag) if lag > 0 else t["realtime_start"]
            self.tables[sid] = t

    def _pull_one(self, s: FredSeriesCfg, api_key: str | None, end: date, force: bool) -> None:
        path = self._path(s.id)
        if self._exists(s.id) and not force:
            existing = self._read(path)
            last_seen = existing["realtime_start"].max().date()
            mode_file = self.dir / f"{s.id}.mode"
            if (end - last_seen).days < 7 or not s.revised:
                self.tables[s.id] = existing
                self.modes[s.id] = mode_file.read_text(encoding="utf-8").strip() if mode_file.exists() else "cached"
                return
        if not s.revised:
            LOG.info("FRED %-9s latest vintage (unrevised series)", s.id)
            df = fetch_latest(s.id)
            mode = "latest_unrevised"
        elif api_key:
            LOG.info("FRED %-9s full real-time history via API", s.id)
            df = fetch_api_intervals(s.id, api_key)
            mode = "api_realtime"
        else:
            vint = fridays_between(to_date(self.cfg.fred.vintage_start), end, 4)
            LOG.info("FRED %-9s %d weekly vintages via ALFRED graph endpoint", s.id, len(vint))
            wide = fetch_alfred_vintages(s.id, vint, self.cfg.fred.vintage_chunk)
            df = wide_vintages_to_intervals(wide)
            mode = "alfred_weekly_vintages"
        self._save(df, path)
        (self.dir / f"{s.id}.mode").write_text(mode, encoding="utf-8")
        self.tables[s.id] = df
        self.modes[s.id] = mode

    def load(self) -> FredStore:
        for s in self.cfg.fred.series:
            path = self._path(s.id)
            if not self._exists(s.id):
                raise FileNotFoundError(f"{path} missing; run `finorchestra pull` first")
            self.tables[s.id] = self._read(path)
            mode_file = self.dir / f"{s.id}.mode"
            self.modes[s.id] = mode_file.read_text(encoding="utf-8").strip() if mode_file.exists() else "unknown"
        self._finalize()
        return self

    @staticmethod
    def _avail(t: pd.DataFrame) -> pd.Series:
        """The availability column; a table that has not been finalized falls back to the raw publication date."""
        return t["available_from"] if "available_from" in t.columns else t["realtime_start"]

    def as_of(self, sid: str, d: date) -> pd.Series:
        """Series of values indexed by observation_date, exactly as knowable at the close of date d."""
        t = self.tables[sid]
        ts = pd.Timestamp(d)
        m = (self._avail(t) <= ts) & (t["realtime_end"] > ts)
        sub = t.loc[m, ["observation_date", "value"]].drop_duplicates("observation_date", keep="last")
        return sub.set_index("observation_date")["value"].sort_index()

    def snapshot(self, d: date) -> dict[str, pd.Series]:
        return {s.name: self.as_of(s.id, d) for s in self.cfg.fred.series}

    def truncated(self, d: date) -> FredStore:
        """A copy that has never seen anything knowable after d (used by the leakage test)."""
        other = FredStore.__new__(FredStore)
        other.cfg, other.dir, other.modes = self.cfg, getattr(self, "dir", None), dict(getattr(self, "modes", {}))
        ts = pd.Timestamp(d)
        other.tables = {k: v[self._avail(v) <= ts].copy() for k, v in self.tables.items()}
        return other

    def describe(self) -> pd.DataFrame:
        rows = []
        for s in self.cfg.fred.series:
            t = self.tables[s.id]
            rows.append(
                {
                    "series": s.id,
                    "name": s.name,
                    "mode": self.modes.get(s.id),
                    "lag_business_days": s.lag_days,
                    "observations": t["observation_date"].nunique(),
                    "intervals": len(t),
                    "first_obs": t["observation_date"].min().date(),
                    "last_obs": t["observation_date"].max().date(),
                    "intervals_per_obs": round(len(t) / max(1, t["observation_date"].nunique()), 2),
                }
            )
        return pd.DataFrame(rows)


def vintage_calendar(cfg: Config, end: date | None = None) -> list[date]:
    end = end or date.today()
    return fridays_between(to_date(cfg.fred.vintage_start), end - timedelta(days=0), 4)
