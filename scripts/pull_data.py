"""Pull every raw input the pipeline needs. Idempotent: re-running only fetches what is missing or stale."""

from __future__ import annotations

import argparse
import logging

from finorchestra.config import load_config
from finorchestra.data.fomc import FomcStore
from finorchestra.data.fred import FredStore
from finorchestra.data.market import MarketStore
from finorchestra.data.text_indices import TextIndexStore
from finorchestra.utils import LOG, setup_logging


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="configs/default.yaml")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", nargs="*", choices=["fred", "market", "text", "fomc"], default=None)
    args = ap.parse_args()
    setup_logging(logging.INFO)
    cfg = load_config(args.config)
    only = set(args.only or ["fred", "market", "text", "fomc"])

    if "market" in only:
        MarketStore(cfg).pull(force=args.force)
    if "text" in only:
        TextIndexStore(cfg).pull(force=args.force)
    if "fomc" in only:
        FomcStore(cfg).pull(force=args.force)
    if "fred" in only:
        fs = FredStore(cfg)
        fs.pull(force=args.force)
        LOG.info("\n%s", fs.describe().to_string(index=False))
    LOG.info("pull complete")


if __name__ == "__main__":
    main()
