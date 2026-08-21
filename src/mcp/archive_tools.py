"""Archive query helpers exposed over MCP for historical questions.

These read the published archive only — no fetching, no AI, no writes — so
they are safe to call at any time and answer questions like "what did SEC
do to exchanges last month" or "show me the timeline of the Coldcard
incident".
"""

from __future__ import annotations

from datetime import date as date_type, timedelta
from typing import Any, Dict, List, Optional, Sequence

from ..archive import ArchiveRecord, load_archive
from ..threads import collect_entities, collect_threads, normalize_tag

MAX_RESULTS = 100


def _record_payload(record: ArchiveRecord) -> Dict[str, Any]:
    return {
        "date": record.date,
        "rank": record.rank,
        "title_zh": record.title_zh,
        "title_en": record.title_en,
        "summary_zh": record.summary_zh,
        "summary_en": record.summary_en,
        "url": record.url,
        "score": record.score,
        "category": record.category,
        "top_category": record.top_category,
        "source": record.source_label or record.source_type,
        "tags": record.tags,
        "sources_count": record.sources_count,
        "thread_id": record.thread_id,
        "thread_day": record.thread_day,
    }


def _matches(record: ArchiveRecord, needles: Sequence[str]) -> bool:
    if not needles:
        return True
    haystack = " ".join(
        [
            record.title_zh,
            record.title_en,
            record.summary_zh,
            record.summary_en,
            record.source_label,
            " ".join(record.tags),
        ]
    ).lower()
    return all(needle in haystack for needle in needles)


def search_archive(
    query: str = "",
    *,
    since: Optional[str] = None,
    until: Optional[str] = None,
    category: Optional[str] = None,
    min_score: Optional[float] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Full-text search across archived editions."""
    limit = max(1, min(int(limit), MAX_RESULTS))
    since_date = _parse_date(since)
    records = load_archive(since=since_date)
    until_date = _parse_date(until)
    needles = [token for token in str(query or "").lower().split() if token]

    selected: List[ArchiveRecord] = []
    for record in records:
        value = record.date_value
        if until_date is not None and (value is None or value > until_date):
            continue
        if category and record.top_category != category:
            continue
        if min_score is not None and (record.score or 0) < min_score:
            continue
        if not _matches(record, needles):
            continue
        selected.append(record)

    selected.sort(key=lambda record: (record.date, -record.rank), reverse=True)
    return {
        "query": query,
        "matched": len(selected),
        "results": [_record_payload(record) for record in selected[:limit]],
    }


def get_thread(thread_id: str) -> Dict[str, Any]:
    """Return the full timeline of one story thread."""
    records = [
        record
        for record in load_archive()
        if record.thread_id == thread_id
    ]
    records.sort(key=lambda record: (record.date, record.rank))
    return {
        "thread_id": thread_id,
        "days": len({record.date for record in records}),
        "entries": len(records),
        "timeline": [_record_payload(record) for record in records],
    }


def list_threads(days: int = 30, limit: int = 20) -> Dict[str, Any]:
    """List recent multi-day threads, most recently active first."""
    limit = max(1, min(int(limit), MAX_RESULTS))
    since = date_type.today() - timedelta(days=max(1, int(days)))
    records = load_archive(since=since)
    threads = collect_threads(records, minimum_days=2, limit=limit)
    return {
        "days": days,
        "threads": [
            {
                "thread_id": thread_id,
                "days": len({record.date for record in thread_records}),
                "entries": len(thread_records),
                "latest_date": max(record.date for record in thread_records),
                "title_zh": thread_records[-1].title_zh,
                "title_en": thread_records[-1].title_en,
            }
            for thread_id, thread_records in threads
        ],
    }


def get_entity(name: str, limit: int = 30) -> Dict[str, Any]:
    """Return archived coverage for one entity (tag)."""
    limit = max(1, min(int(limit), MAX_RESULTS))
    slug = normalize_tag(name)
    records = [
        record
        for record in load_archive()
        if any(normalize_tag(tag) == slug for tag in record.tags)
    ]
    records.sort(key=lambda record: (record.date, record.rank), reverse=True)
    return {
        "entity": slug,
        "mentions": len(records),
        "coverage": [_record_payload(record) for record in records[:limit]],
    }


def list_entities(days: int = 60, limit: int = 40) -> Dict[str, Any]:
    """List recurring entities in the recent archive."""
    limit = max(1, min(int(limit), MAX_RESULTS))
    since = date_type.today() - timedelta(days=max(1, int(days)))
    entities = collect_entities(
        load_archive(since=since),
        minimum_mentions=2,
        limit=limit,
    )
    return {
        "days": days,
        "entities": [
            {"slug": entity.slug, "label": entity.label, "mentions": entity.count}
            for entity in entities
        ],
    }


def _parse_date(value: Optional[str]) -> Optional[date_type]:
    if not value:
        return None
    try:
        return date_type.fromisoformat(str(value))
    except ValueError:
        return None
