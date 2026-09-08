"""FOMC statement corpus scraped from federalreserve.gov, one dated text file per statement.

Statements are released at 14:00 ET on the last day of each meeting, so a statement dated D is usable on
any decision date >= D (+ configured lag). The date in the URL is the release date.
"""

from __future__ import annotations

import re
import time
from datetime import date

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import Config
from ..utils import LOG, add_business_days, ensure_dir

BASE = "https://www.federalreserve.gov"
CALENDAR = f"{BASE}/monetarypolicy/fomccalendars.htm"
HISTORICAL = f"{BASE}/monetarypolicy/fomchistorical{{year}}.htm"
STATEMENT_RE = re.compile(r"/newsevents/(?:pressreleases/monetary|press/monetary/)(\d{8})a\.htm")

_HEADERS = {"User-Agent": "finorchestra/0.1 (academic research; FOMC statement corpus)"}
_BOILERPLATE = (
    "For release at",
    "Share",
    "Federal Reserve issues FOMC statement",
    "Last Update:",
    "Implementation Note",
    "Board of Governors of the Federal Reserve System",
)


def repair_mojibake(text: str) -> str:
    """Undo UTF-8 text that was decoded as cp1252/latin-1 and re-saved (e.g. '3â€‘1/2' -> '3‑1/2').

    Only applied when the tell-tale 'â' or 'Ã' lead bytes are present; clean text passes through unchanged.
    """
    if "â" not in text and "Ã" not in text:
        return text
    for enc in ("cp1252", "latin-1"):
        try:
            return text.encode(enc).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def _fetch(url: str, retries: int = 3) -> str | None:
    for i in range(retries):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=60)
            if r.status_code == 200:
                # federalreserve.gov serves UTF-8; requests may guess ISO-8859-1 from the headers and garble hyphens/quotes
                r.encoding = "utf-8"
                return r.text
            if r.status_code == 404:
                return None
        except requests.RequestException:
            pass
        time.sleep(1.0 + i)
    return None


def list_statement_urls(year_from: int, year_to: int) -> dict[date, str]:
    urls: dict[date, str] = {}
    pages = [CALENDAR] + [HISTORICAL.format(year=y) for y in range(year_from, year_to + 1)]
    for page in pages:
        html = _fetch(page)
        if not html:
            continue
        for m in STATEMENT_RE.finditer(html):
            d = pd.Timestamp(m.group(1)).date()
            if year_from <= d.year <= year_to:
                urls.setdefault(d, BASE + m.group(0))
    return dict(sorted(urls.items()))


def parse_statement(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    container = soup.select_one("div#article") or soup.body or soup
    paras = []
    for p in container.find_all("p"):
        t = " ".join(p.get_text(" ", strip=True).split())
        if len(t) < 40 or any(t.startswith(b) for b in _BOILERPLATE):
            continue
        paras.append(t)
    # Drop the trailing voting / implementation paragraphs, which carry no macro content
    keep = []
    for t in paras:
        if t.startswith("Voting for the") or t.startswith("Voting against") or t.startswith("For media inquiries"):
            break
        keep.append(t)
    return "\n\n".join(keep if keep else paras)


class FomcStore:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dir = ensure_dir(cfg.raw_dir / "fomc" / "statements")
        self.docs: pd.DataFrame | None = None  # columns: date, text, available_from, path

    def pull(self, force: bool = False) -> None:
        y0, y1 = self.cfg.fomc.years
        urls = list_statement_urls(y0, min(y1, date.today().year))
        LOG.info("FOMC: %d statement URLs found (%d..%d)", len(urls), y0, y1)
        n_new = 0
        for d, url in urls.items():
            out = self.dir / f"{d.isoformat()}.txt"
            if out.exists() and not force:
                continue
            html = _fetch(url)
            if not html:
                LOG.warning("FOMC: could not fetch %s", url)
                continue
            text = parse_statement(html)
            if len(text) < 200:
                LOG.warning("FOMC: suspiciously short statement %s (%d chars)", d, len(text))
            out.write_text(f"SOURCE: {url}\n\n{text}", encoding="utf-8")
            n_new += 1
            time.sleep(0.3)
        LOG.info("FOMC: %d new statements saved to %s", n_new, self.dir)

    def load(self) -> FomcStore:
        rows = []
        for p in sorted(self.dir.glob("*.txt")):
            d = pd.Timestamp(p.stem).date()
            raw = p.read_text(encoding="utf-8")
            text = repair_mojibake(raw.split("\n\n", 1)[1] if raw.startswith("SOURCE:") else raw)
            rows.append(
                {
                    "date": pd.Timestamp(d),
                    "text": text,
                    "available_from": pd.Timestamp(add_business_days(d, self.cfg.fomc.lag_days)),
                    "path": str(p),
                }
            )
        self.docs = pd.DataFrame(rows)
        if self.docs.empty:
            raise FileNotFoundError(f"no FOMC statements in {self.dir}; run `finorchestra pull` first")
        return self

    def as_of(self, d: date) -> pd.DataFrame:
        assert self.docs is not None
        return self.docs.loc[self.docs["available_from"] <= pd.Timestamp(d)].reset_index(drop=True)

    def truncated(self, d: date) -> FomcStore:
        other = FomcStore.__new__(FomcStore)
        other.cfg, other.dir = self.cfg, self.dir
        other.docs = self.as_of(d).copy()
        return other
