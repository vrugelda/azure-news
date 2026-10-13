"""Fetch the Azure feeds, summarise new major updates, and write the site's data file.

`azure-news notify` then emails the items that were published for the first time."""

from __future__ import annotations

import argparse
import logging

from .config import Settings
from .notify import run_notify
from .pipeline import run_ingest
from .summarize import open_summarizer


def main() -> None:
    parser = argparse.ArgumentParser(prog="azure-news", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("ingest", help="fetch, assess and store the news")
    commands.add_parser("notify", help="email the items published since the last email")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The Azure SDK logs the headers of every request and response at INFO.
    logging.getLogger("azure").setLevel(logging.WARNING)
    settings = Settings.from_env()
    if args.command == "notify":
        print(f"{run_notify(settings)} items emailed")
        return
    result = run_ingest(settings, open_summarizer(settings))
    print(
        f"{result.fetched} recent feed items, {result.assessed} assessed, "
        f"{result.kept} kept, {result.total} published to {settings.news_path}, "
        f"{result.pending} waiting to be emailed"
    )


if __name__ == "__main__":
    main()
