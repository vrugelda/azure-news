"""Runtime settings, read from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


@dataclass(frozen=True)
class Settings:
    # Paths, relative to the working directory (the repository root).
    data_dir: str = "site/data"  # published with the site
    state_dir: str = "state"  # ingest state; not published

    # Summarisation
    summarizer: str = "claude"  # "claude" or "heuristic" (no LLM, for local trials)
    model: str = "claude-haiku-5-5"
    refusal_fallbacks: bool = True
    batch_size: int = 20
    # Items at or above min_importance are published. Those that also reach
    # major_architecture_relevance are shown by default; the rest (down to
    # min_architecture_relevance) appear only behind the "smaller updates" filter.
    min_importance: int = 4
    min_architecture_relevance: int = 3
    major_architecture_relevance: int = 4

    # Ingest
    max_age_days: int = 30  # ignore feed items older than this
    retention_days: int = 180  # drop published items older than this
    feed_ttl_minutes: int = 30  # reuse a cached feed body within this window

    # Email notification through Azure Communication Services. Off unless all three of
    # the connection string, sender and recipients are set.
    acs_connection_string: str = field(default="", repr=False)
    notify_from: str = ""  # a sender address on a domain linked to the ACS resource
    notify_to: tuple[str, ...] = ()
    notify_tier: str = "major"  # "major", or "all" to include the smaller updates
    site_url: str = ""  # linked from the email when set

    @property
    def news_path(self) -> Path:
        """The published items, read by the frontend."""
        return Path(self.data_dir) / "news.json"

    @property
    def assessments_path(self) -> Path:
        """Verdict per feed item already assessed, so nothing is sent to the model twice."""
        return Path(self.state_dir) / "assessments.json"

    @property
    def notifications_path(self) -> Path:
        """Ids of published items that have not been emailed yet."""
        return Path(self.state_dir) / "notifications.json"

    def feed_cache_path(self, key: str) -> Path:
        return Path(self.state_dir) / "feeds" / f"{key}.json"

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ.get
        return cls(
            data_dir=env("AZURE_NEWS_DATA_DIR") or cls.data_dir,
            state_dir=env("AZURE_NEWS_STATE_DIR") or cls.state_dir,
            summarizer=(env("AZURE_NEWS_SUMMARIZER") or cls.summarizer).lower(),
            model=env("AZURE_NEWS_MODEL") or cls.model,
            refusal_fallbacks=(env("AZURE_NEWS_REFUSAL_FALLBACKS") or "1") != "0",
            batch_size=_int("AZURE_NEWS_BATCH_SIZE", cls.batch_size),
            min_importance=_int("AZURE_NEWS_MIN_IMPORTANCE", cls.min_importance),
            min_architecture_relevance=_int(
                "AZURE_NEWS_MIN_ARCHITECTURE_RELEVANCE", cls.min_architecture_relevance
            ),
            major_architecture_relevance=_int(
                "AZURE_NEWS_MAJOR_ARCHITECTURE_RELEVANCE", cls.major_architecture_relevance
            ),
            max_age_days=_int("AZURE_NEWS_MAX_AGE_DAYS", cls.max_age_days),
            retention_days=_int("AZURE_NEWS_RETENTION_DAYS", cls.retention_days),
            feed_ttl_minutes=_int("AZURE_NEWS_FEED_TTL_MINUTES", cls.feed_ttl_minutes),
            acs_connection_string=env("AZURE_NEWS_ACS_CONNECTION_STRING") or "",
            notify_from=(env("AZURE_NEWS_NOTIFY_FROM") or "").strip(),
            notify_to=tuple(
                address.strip()
                for address in (env("AZURE_NEWS_NOTIFY_TO") or "").split(",")
                if address.strip()
            ),
            notify_tier=(env("AZURE_NEWS_NOTIFY_TIER") or cls.notify_tier).lower(),
            site_url=(env("AZURE_NEWS_SITE_URL") or "").strip(),
        )
