import hashlib
from datetime import datetime, timezone

import pytest

from azure_news.config import Settings
from azure_news.feeds import FeedSource, HttpResponse
from azure_news.summarize import Assessment, Brief

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
SOURCE = FeedSource("updates", "Azure Updates", "https://example.test/rss")


def rss(*items: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


def rss_item(guid: str, title: str, description: str = "Details.", date: str = "Fri, 09 Oct 2026 20:27:17 Z") -> str:
    return (
        f"<item><guid>{guid}</guid><link>https://example.test/{guid}</link>"
        f"<category>Launched</category><category>Networking</category>"
        f"<title>{title}</title><description>{description}</description>"
        f"<pubDate>{date}</pubDate></item>"
    )


class FakeHttp:
    def __init__(self, body: str) -> None:
        self.body = body
        self.etag = f'"{hashlib.sha1(body.encode()).hexdigest()}"'
        self.calls: list[tuple] = []

    def __call__(self, url, etag, last_modified):
        self.calls.append((url, etag, last_modified))
        if etag == self.etag:
            return HttpResponse(304)
        return HttpResponse(200, self.body, self.etag, None)


class StubSummarizer:
    """Keeps items whose title contains "major"."""

    name = "stub"
    fingerprint = "stub"

    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    def assess(self, items):
        self.seen.append([item.title for item in items])
        results = []
        for item in items:
            major = "major" in item.title.lower()
            brief = Brief(
                headline=item.title,
                summary="What changed.",
                architecture_impact="Why it matters.",
                status="ga",
                recommended_action="evaluate",
                services=["Azure NAT Gateway"],
                pillars=["reliability"],
            )
            results.append(
                Assessment(
                    id=item.id,
                    importance=5 if major else 2,
                    architecture_relevance=4 if major else 1,
                    reason="stub",
                    brief=brief if major else None,
                )
            )
        return results


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=str(tmp_path / "data"), state_dir=str(tmp_path / "state"))
