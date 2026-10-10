"""Fetch the Azure feeds, summarise new major updates, and write the site's data file."""

from __future__ import annotations

import argparse
import logging

from .config import Settings
from .pipeline import run_ingest
from .summarize import open_summarizer


def main() -> None:
    parser = argparse.ArgumentParser(prog="azure-news", description=__doc__)
    parser.add_subparsers(dest="command", required=True).add_parser("ingest", help=__doc__)
    parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings.from_env()
    result = run_ingest(settings, open_summarizer(settings))
    print(
        f"{result.fetched} recent feed items, {result.assessed} assessed, "
        f"{result.kept} kept, {result.total} published to {settings.news_path}"
    )


if __name__ == "__main__":
    main()
