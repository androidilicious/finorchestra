"""Small shared helpers: logging, dates, hashing, file IO."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LOG = logging.getLogger("finorchestra")


def setup_logging(level: int = logging.INFO) -> None:
    if not LOG.handlers:
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S"))
        LOG.addHandler(h)
    LOG.setLevel(level)


def to_date(x: str | date | datetime | pd.Timestamp) -> date:
    if isinstance(x, pd.Timestamp):
        return x.date()
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    return pd.Timestamp(x).date()


def fridays_between(start: date, end: date, weekday: int = 4) -> list[date]:
    """All dates with the given weekday in [start, end]."""
    d = start
    while d.weekday() != weekday:
        d += timedelta(days=1)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=7)
    return out


def add_business_days(d: date, n: int) -> date:
    """Shift a date forward by n business days (Mon-Fri, holidays ignored: a conservative approximation)."""
    cur = d
    steps = 0
    while steps < n:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            steps += 1
    return cur


def stable_hash(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:12]


def ensure_dir(p: Path) -> Path:
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, default=_json_default, ensure_ascii=False)


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _json_default(o: Any) -> Any:
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp, date, datetime)):
        return str(o)[:10]
    if isinstance(o, Path):
        return str(o)
    if hasattr(o, "model_dump"):
        return o.model_dump()
    return str(o)


def annualize_factor(freq: str = "W") -> float:
    return {"D": 252.0, "W": 52.0, "M": 12.0}[freq]
