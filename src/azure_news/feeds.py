"""Fetch and parse the Azure news feeds, with an on-disk HTTP cache."""

from __future__ import annotations

import hashlib
import logging
import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable

import truststore
from defusedxml import ElementTree

from .config import Settings
from .storage import read_json, write_json

log = logging.getLogger(__name__)

USER_AGENT = "azure-news/0.1"
MAX_FEED_BYTES = 10 * 1024 * 1024
# Verify TLS against the operating system trust store, so corporate proxies' roots are honoured.
_TLS = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
# Item text sent for assessment is capped: the Architecture Blog feed embeds whole
# articles (up to ~70k characters), and the opening is enough to triage and summarise.
MAX_TEXT_CHARS = 6000


@dataclass(frozen=True)
class FeedSource:
    key: str
    name: str
    url: str
    max_age_days: int | None = None  # overrides Settings.max_age_days


SOURCES = [
    FeedSource(
        "updates",
        "Azure Updates",
        "https://www.microsoft.com/releasecommunications/api/v2/azure/rss",
    ),
    FeedSource("blog", "Azure Blog", "https://azure.microsoft.com/en-us/blog/feed/"),
    FeedSource(
        "architecture",
        "Azure Architecture Blog",
        "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=AzureArchitectureBlog",
        # Guidance stays useful for longer than a product update does.
        max_age_days=120,
    ),
]


@dataclass(frozen=True)
class FeedItem:
    id: str
    source: str
    source_name: str
    title: str
    link: str
    published: str  # ISO 8601, UTC
    categories: list[str]
    text: str

    @property
    def content_hash(self) -> str:
        payload = "\x1f".join([self.title, self.text, *self.categories])
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str | None = None
    etag: str | None = None
    last_modified: str | None = None


HttpGet = Callable[[str, str | None, str | None], HttpResponse]


def http_get(url: str, etag: str | None, last_modified: str | None) -> HttpResponse:
    """Conditional GET. Returns status 304 with no body when the feed is unchanged."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30, context=_TLS) as r:
            raw = r.read(MAX_FEED_BYTES + 1)
            if len(raw) > MAX_FEED_BYTES:
                raise ValueError(f"feed larger than {MAX_FEED_BYTES} bytes: {url}")
            return HttpResponse(
                r.status,
                raw.decode(r.headers.get_content_charset() or "utf-8", errors="replace"),
                r.headers.get("ETag"),
                r.headers.get("Last-Modified"),
            )
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return HttpResponse(304)
        raise


def load_feed(
    source: FeedSource,
    settings: Settings,
    now: datetime,
    get: HttpGet = http_get,
) -> str:
    """Return the feed body, reusing the cached copy while it is fresh or unchanged.

    If the fetch fails and a cached copy exists, the stale copy is returned.
    """
    path = settings.feed_cache_path(source.key)
    cached = read_json(path)
    if cached and cached.get("url") != source.url:
        cached = None
    if cached:
        age = now - datetime.fromisoformat(cached["fetched_at"])
        if age < timedelta(minutes=settings.feed_ttl_minutes):
            return cached["body"]

    try:
        if cached:
            response = get(source.url, cached.get("etag"), cached.get("last_modified"))
        else:
            response = get(source.url, None, None)
    except (OSError, ValueError) as e:
        if cached:
            log.warning("Fetching %s failed (%s); using cached copy", source.name, e)
            return cached["body"]
        raise

    if response.status == 304 and cached:
        entry = {**cached, "fetched_at": now.isoformat()}
    else:
        entry = {
            "url": source.url,
            "etag": response.etag,
            "last_modified": response.last_modified,
            "fetched_at": now.isoformat(),
            "body": response.body or "",
        }
    write_json(path, entry)
    return entry["body"]


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skipping += 1
        else:
            self._parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skipping = max(0, self._skipping - 1)
        else:
            self._parts.append(" ")

    def handle_data(self, data):
        if not self._skipping:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


def parse_feed(source: FeedSource, body: str) -> list[FeedItem]:
    """Parse an RSS 2.0 document. Items without a title, http(s) link or date are skipped."""
    root = ElementTree.fromstring(body)
    items = []
    for node in root.iter("item"):
        title = html_to_text(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        try:
            published = parsedate_to_datetime(node.findtext("pubDate") or "")
        except (TypeError, ValueError):
            continue
        if not title or not re.match(r"https?://", link):
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        guid = (node.findtext("guid") or link).strip()
        categories = [c.text.strip() for c in node.findall("category") if c.text and c.text.strip()]
        items.append(
            FeedItem(
                id=f"{source.key}-{hashlib.sha1(guid.encode('utf-8')).hexdigest()[:12]}",
                source=source.key,
                source_name=source.name,
                title=title,
                link=link,
                published=published.astimezone(timezone.utc).isoformat(),
                categories=list(dict.fromkeys(categories)),
                text=html_to_text(node.findtext("description") or "")[:MAX_TEXT_CHARS],
            )
        )
    return items
