from datetime import timedelta

import pytest
from conftest import NOW, SOURCE, FakeHttp, rss, rss_item

from azure_news.feeds import MAX_TEXT_CHARS, html_to_text, load_feed, parse_feed


def test_parse_feed_extracts_fields():
    body = rss(rss_item("1", "[Launched] NAT Gateway v2", "&lt;p&gt;Now &lt;b&gt;GA&lt;/b&gt;.&lt;/p&gt;"))
    (item,) = parse_feed(SOURCE, body)
    assert item.title == "[Launched] NAT Gateway v2"
    assert item.link == "https://example.test/1"
    assert item.published == "2026-10-09T20:27:17+00:00"
    assert item.categories == ["Launched", "Networking"]
    assert item.text == "Now GA ."
    assert item.id.startswith("updates-")


def test_parse_feed_skips_unusable_items_and_caps_text():
    body = rss(
        "<item><title>No link</title><pubDate>Fri, 09 Oct 2026 20:27:17 Z</pubDate></item>",
        "<item><title>Bad scheme</title><link>javascript:alert(1)</link>"
        "<pubDate>Fri, 09 Oct 2026 20:27:17 Z</pubDate></item>",
        "<item><title>No date</title><link>https://example.test/x</link></item>",
        rss_item("ok", "Kept", "x" * (MAX_TEXT_CHARS + 500)),
    )
    (item,) = parse_feed(SOURCE, body)
    assert item.title == "Kept"
    assert len(item.text) == MAX_TEXT_CHARS


def test_parse_feed_rejects_entity_expansion():
    body = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><rss><channel>&a;</channel></rss>'
    with pytest.raises(Exception):
        parse_feed(SOURCE, body)


def test_html_to_text_drops_scripts():
    assert html_to_text("<p>Hi</p><script>evil()</script><style>p{}</style> there") == "Hi there"


def test_load_feed_uses_cache_then_revalidates(settings):
    http = FakeHttp(rss(rss_item("1", "One")))

    first = load_feed(SOURCE, settings, NOW, http)
    assert load_feed(SOURCE, settings, NOW + timedelta(minutes=5), http) == first
    assert len(http.calls) == 1  # fresh: served from the cache

    later = NOW + timedelta(minutes=settings.feed_ttl_minutes + 1)
    assert load_feed(SOURCE, settings, later, http) == first
    assert http.calls[-1][1] == http.etag  # stale: conditional request, 304 keeps the body

    load_feed(SOURCE, settings, later + timedelta(minutes=1), http)
    assert len(http.calls) == 2  # the 304 refreshed the cache timestamp


def test_load_feed_falls_back_to_stale_copy_on_error(settings):
    first = load_feed(SOURCE, settings, NOW, FakeHttp(rss(rss_item("1", "One"))))

    def failing(url, etag, last_modified):
        raise OSError("network down")

    assert load_feed(SOURCE, settings, NOW + timedelta(days=1), failing) == first
    settings.feed_cache_path("updates").unlink()
    with pytest.raises(OSError):
        load_feed(SOURCE, settings, NOW, failing)
