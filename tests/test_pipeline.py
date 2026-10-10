from datetime import timedelta

from conftest import NOW, SOURCE, FakeHttp, StubSummarizer, rss, rss_item

from azure_news.config import Settings
from azure_news.feeds import parse_feed
from azure_news.pipeline import run_ingest
from azure_news.storage import read_json
from azure_news.summarize import HeuristicSummarizer

FEED = rss(
    rss_item("1", "Major: zone-redundant NAT Gateway"),
    rss_item("2", "Minor SDK bump"),
    rss_item("3", "Major but old", date="Mon, 03 Aug 2026 10:00:00 Z"),
)


def ingest(settings, summarizer, body=FEED, now=NOW):
    return run_ingest(settings, summarizer, sources=[SOURCE], get=FakeHttp(body), now=now)


def test_keeps_only_major_recent_items(settings):
    summarizer = StubSummarizer()
    result = ingest(settings, summarizer)

    assert (result.fetched, result.assessed, result.kept, result.total) == (2, 2, 1, 1)
    assert summarizer.seen == [["Major: zone-redundant NAT Gateway", "Minor SDK bump"]]

    document = read_json(settings.news_path)
    (item,) = document["items"]
    assert item["headline"] == "Major: zone-redundant NAT Gateway"
    assert item["architecture_impact"] == "Why it matters."
    assert item["summarised_by"] == "stub"
    assert item["link"] == "https://example.test/1"
    assert "text" not in item
    assert len(read_json(settings.assessments_path)) == 2


def test_assessed_items_are_not_sent_again_unless_changed(settings):
    summarizer = StubSummarizer()
    ingest(settings, summarizer)
    later = NOW + timedelta(hours=6)

    result = ingest(settings, summarizer, now=later)
    assert result.assessed == 0 and result.total == 1
    assert len(summarizer.seen) == 1

    changed = rss(rss_item("1", "Major: zone-redundant NAT Gateway"), rss_item("2", "Major after all"))
    result = ingest(settings, summarizer, body=changed, now=later + timedelta(hours=6))
    assert summarizer.seen[-1] == ["Major after all"]
    assert result.total == 2


def test_item_downgraded_on_reassessment_is_removed(settings):
    summarizer = StubSummarizer()
    ingest(settings, summarizer)
    downgraded = rss(rss_item("1", "Correction: small change"))
    result = ingest(settings, summarizer, body=downgraded, now=NOW + timedelta(hours=6))
    assert result.total == 0


def test_items_past_retention_are_dropped(settings):
    ingest(settings, StubSummarizer())
    far_future = NOW + timedelta(days=settings.retention_days + 2)
    result = ingest(settings, StubSummarizer(), body=rss(), now=far_future)
    assert result.total == 0
    assert read_json(settings.assessments_path) == {}


def test_broken_feed_does_not_lose_stored_items(settings):
    ingest(settings, StubSummarizer())
    result = ingest(settings, StubSummarizer(), body="not xml", now=NOW + timedelta(hours=6))
    assert result.fetched == 0 and result.total == 1


def test_heuristic_summarizer_rules():
    summarizer = HeuristicSummarizer(Settings())
    body = rss(
        rss_item("1", "[Launched] Generally Available: Private Link for X"),
        rss_item("2", "[Launched] Generally Available: PostgreSQL in East US 3"),
    )
    kept, region = summarizer.assess(parse_feed(SOURCE, body))
    assert kept.brief is not None and kept.brief.headline == "Generally Available: Private Link for X"
    assert region.brief is None and region.importance == 2


def test_switching_summarizer_reassesses(settings):
    ingest(settings, StubSummarizer())
    other = StubSummarizer()
    other.name = "other"
    result = ingest(settings, other, now=NOW + timedelta(hours=6))
    assert result.assessed == 2
    assert read_json(settings.news_path)["items"][0]["summarised_by"] == "other"
