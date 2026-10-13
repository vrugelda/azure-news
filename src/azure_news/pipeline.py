"""Ingest: fetch feeds, assess what is new, and store the items worth keeping."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from .config import Settings
from .feeds import SOURCES, FeedItem, FeedSource, HttpGet, http_get, load_feed, parse_feed
from .storage import read_json, write_json
from .summarize import Assessment, Summarizer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    fetched: int
    assessed: int
    kept: int
    total: int
    pending: int  # published items not emailed yet


def _clamp(score: int) -> int:
    return max(1, min(5, score))


def _is_kept(assessment: Assessment, settings: Settings) -> bool:
    return (
        assessment.brief is not None
        and assessment.importance >= settings.min_importance
        and assessment.architecture_relevance >= settings.min_architecture_relevance
    )


def _news_item(
    item: FeedItem, assessment: Assessment, summarised_by: str, settings: Settings
) -> dict:
    record = asdict(item)
    del record["text"]
    major = assessment.architecture_relevance >= settings.major_architecture_relevance
    return {
        **record,
        "tier": "major" if major else "detail",
        "importance": _clamp(assessment.importance),
        "architecture_relevance": _clamp(assessment.architecture_relevance),
        "summarised_by": summarised_by,
        **assessment.brief.model_dump(),
    }


def run_ingest(
    settings: Settings,
    summarizer: Summarizer,
    *,
    sources: list[FeedSource] = SOURCES,
    get: HttpGet = http_get,
    now: datetime | None = None,
) -> IngestResult:
    now = now or datetime.now(timezone.utc)
    retention_cutoff = (now - timedelta(days=settings.retention_days)).isoformat()

    recent: dict[str, FeedItem] = {}
    for source in sources:
        try:
            items = parse_feed(source, load_feed(source, settings, now, get))
        except Exception:
            log.exception("Skipping %s: could not fetch or parse the feed", source.name)
            continue
        max_age_days = source.max_age_days or settings.max_age_days
        cutoff = (now - timedelta(days=max_age_days)).isoformat()
        recent.update((i.id, i) for i in items if i.published >= cutoff)

    assessments = read_json(settings.assessments_path) or {}
    # Re-assess when the content changed or the summariser (model, prompt, thresholds) did.
    pending = [
        item
        for item in recent.values()
        if (assessments.get(item.id, {}).get("hash"), assessments.get(item.id, {}).get("by"))
        != (item.content_hash, summarizer.fingerprint)
    ]
    log.info("%d recent feed items, %d to assess", len(recent), len(pending))

    document = read_json(settings.news_path) or {}
    stored = {item["id"]: item for item in document.get("items", [])}
    # Items published for the first time wait here until `azure-news notify` emails them.
    unsent = list((read_json(settings.notifications_path) or {}).get("pending", []))

    kept = 0
    results = summarizer.assess(pending) if pending else []
    for assessment in results:
        item = recent.get(assessment.id)
        if item is None:
            log.warning("Ignoring assessment for unknown item id %r", assessment.id)
            continue
        keep = _is_kept(assessment, settings)
        assessments[item.id] = {
            "hash": item.content_hash,
            "by": summarizer.fingerprint,
            "kept": keep,
            "importance": assessment.importance,
            "architecture_relevance": assessment.architecture_relevance,
            "reason": assessment.reason,
            "assessed_at": now.isoformat(),
        }
        if keep:
            # A re-assessment of an item that is already published is not news.
            if item.id not in stored and item.id not in unsent:
                unsent.append(item.id)
            stored[item.id] = _news_item(item, assessment, summarizer.name, settings)
            kept += 1
        else:
            stored.pop(item.id, None)

    items = sorted(
        (item for item in stored.values() if item["published"] >= retention_cutoff),
        key=lambda item: item["published"],
        reverse=True,
    )
    assessments = {
        id_: entry for id_, entry in assessments.items() if entry["assessed_at"] >= retention_cutoff
    }

    published = {item["id"] for item in items}
    unsent = [id_ for id_ in unsent if id_ in published]

    write_json(settings.assessments_path, assessments)
    write_json(settings.notifications_path, {"pending": unsent})
    write_json(settings.news_path, {"updated_at": now.isoformat(), "items": items})
    result = IngestResult(
        fetched=len(recent), assessed=len(results), kept=kept, total=len(items), pending=len(unsent)
    )
    log.info("Ingest finished: %s", result)
    return result
