from dataclasses import replace
from datetime import timedelta

import pytest
from conftest import NOW, SOURCE, FakeHttp, StubSummarizer, rss, rss_item

from azure_news.notify import build_email, run_notify
from azure_news.pipeline import run_ingest
from azure_news.storage import read_json

FEED = rss(rss_item("1", "Major: zone-redundant NAT Gateway"), rss_item("2", "Minor SDK bump"))


class Outbox:
    def __init__(self) -> None:
        self.emails = []

    def __call__(self, email):
        self.emails.append(email)


@pytest.fixture
def settings(settings):
    return replace(
        settings,
        acs_connection_string="endpoint=https://example.test/;accesskey=a2V5",
        notify_from="DoNotReply@example.test",
        notify_to=("architects@example.test",),
        site_url="https://example.test/news/",
    )


def ingest(settings, summarizer=None, body=FEED, now=NOW):
    return run_ingest(
        settings, summarizer or StubSummarizer(), sources=[SOURCE], get=FakeHttp(body), now=now
    )


def pending(settings):
    return read_json(settings.notifications_path)["pending"]


def test_new_item_is_emailed_once(settings):
    assert ingest(settings).pending == 1
    outbox = Outbox()

    assert run_notify(settings, outbox) == 1
    (email,) = outbox.emails
    assert email.subject == "Azure news: Major: zone-redundant NAT Gateway"
    assert "Why it matters." in email.text and "https://example.test/1" in email.text
    assert "Generally available · Evaluate" in email.html
    assert 'href="https://example.test/news/"' in email.html
    assert pending(settings) == []

    ingest(settings, now=NOW + timedelta(hours=6))
    assert run_notify(settings, outbox) == 0
    assert len(outbox.emails) == 1


def test_reassessed_item_is_not_emailed_again(settings):
    ingest(settings)
    run_notify(settings, Outbox())
    other = StubSummarizer()
    other.name = other.fingerprint = "other"

    result = ingest(settings, other, now=NOW + timedelta(hours=6))
    assert (result.kept, result.pending) == (1, 0)


def test_failed_send_keeps_the_queue(settings):
    ingest(settings)

    def failing(email):
        raise RuntimeError("service unavailable")

    with pytest.raises(RuntimeError):
        run_notify(settings, failing)
    assert len(pending(settings)) == 1

    # The next run sends the item that failed together with what is new by then.
    both = rss(rss_item("1", "Major: zone-redundant NAT Gateway"), rss_item("3", "Major: second"))
    ingest(settings, body=both, now=NOW + timedelta(hours=6))
    outbox = Outbox()
    assert run_notify(settings, outbox) == 2
    assert outbox.emails[0].subject == "Azure news: 2 new updates"


def test_item_removed_before_sending_is_not_emailed(settings):
    ingest(settings)
    ingest(settings, body=rss(rss_item("1", "Correction: small change")), now=NOW + timedelta(hours=6))
    outbox = Outbox()
    assert run_notify(settings, outbox) == 0
    assert outbox.emails == []


def test_tier_filter(settings):
    class Detail(StubSummarizer):
        def assess(self, items):
            return [a.model_copy(update={"architecture_relevance": 3}) for a in super().assess(items)]

    ingest(settings, Detail())
    outbox = Outbox()
    assert run_notify(settings, outbox) == 0
    assert outbox.emails == [] and pending(settings) == []

    ingest(settings, Detail(), body=rss(rss_item("4", "Major: detail tier")), now=NOW + timedelta(hours=6))
    assert run_notify(replace(settings, notify_tier="all"), outbox) == 1


def test_not_configured_drops_the_queue_without_sending(settings):
    ingest(settings)
    off = replace(settings, acs_connection_string="", notify_from="", notify_to=())
    assert run_notify(off) == 0
    assert pending(settings) == []


def test_partial_configuration_is_an_error(settings):
    ingest(settings)
    with pytest.raises(ValueError, match="AZURE_NEWS_NOTIFY_TO"):
        run_notify(replace(settings, notify_to=()))
    assert len(pending(settings)) == 1


def test_content_is_escaped(settings):
    ingest(settings)
    (item,) = read_json(settings.news_path)["items"]
    item = {**item, "headline": "<script>alert(1)</script>", "summary": 'a "b" <img src=x>'}
    html = build_email([item], settings).html
    assert "<script>" not in html and "<img" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
