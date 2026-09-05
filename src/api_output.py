"""Machine-readable outputs: edition JSON API and per-category feeds.

Everything here is a static file written at publish time, so the "API" is
just the site: no server, no rate limits, cacheable at the edge. Other
tools (bots, notebooks, the user's own scripts) can consume an edition
without scraping HTML.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

from ._file_utils import _atomic_write_text
from .archive import ArchiveRecord
from .market_snapshot import MarketSnapshot
from .publication_revision import story_revision

logger = logging.getLogger(__name__)

API_ROOT = Path("docs/api")
FEEDS_ROOT = Path("docs/feeds")
EDITIONS_ROOT = Path("docs/editions")
SITEMAP_PATH = Path("docs/sitemap.xml")

DEFAULT_SITE_URL = "https://bmt.news"
FEED_CATEGORIES = ("crypto", "technology", "policy")
_FEED_TITLES = {
    ("crypto", "zh"): "BMTNews · Crypto",
    ("crypto", "en"): "BMTNews · Crypto",
    ("technology", "zh"): "BMTNews · AI 科技",
    ("technology", "en"): "BMTNews · AI & Tech",
    ("policy", "zh"): "BMTNews · 政策",
    ("policy", "en"): "BMTNews · Policy",
}

_SITEMAP_STATIC_PATHS = (
    "/",
    "/en/",
    "/threads/",
    "/en/threads/",
    "/entity/",
    "/en/entity/",
    "/weekly/",
    "/en/weekly/",
    "/developers/",
    "/about/",
    "/contact/",
    "/legal/",
)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_edition_payload(
    records: Sequence[ArchiveRecord],
    *,
    date: str,
    stats: dict[str, int],
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    market: MarketSnapshot | None = None,
    overviews: dict[str, str] | None = None,
    site_url: str = DEFAULT_SITE_URL,
) -> dict:
    """Build the public JSON document for one edition."""
    base = site_url.rstrip("/")
    items = []
    for record in records:
        thread = None
        if record.thread_id:
            thread = {
                "id": record.thread_id,
                "day": record.thread_day or 1,
                "url": f"{base}/threads/{record.thread_id}/",
            }
        event = None
        if record.event_id and record.event_update_id:
            event = {
                "event_id": record.event_id,
                "update_id": record.event_update_id,
                "url": (
                    f"{base}/events/{record.event_id}/"
                    f"#{record.event_update_id}"
                ),
                "json": f"{base}/api/events/{record.event_id}.json",
            }
        items.append(
            {
                "rank": record.rank,
                "url": record.url,
                "title": {"zh": record.title_zh, "en": record.title_en},
                "summary": {"zh": record.summary_zh, "en": record.summary_en},
                "content_revision": {
                    "zh": story_revision(record.url, record.title_zh, record.summary_zh),
                    "en": story_revision(record.url, record.title_en, record.summary_en),
                },
                "score": record.score,
                "category": record.category,
                "top_category": record.top_category,
                "source": {
                    "type": record.source_type,
                    "label": record.source_label,
                },
                "tags": record.tags,
                "sources_count": record.sources_count,
                "editorial": record.editorial,
                "thread": thread,
                "event": event,
            }
        )
    payload = {
        "version": 1,
        "content_revision_version": 1,
        "date": date,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "site": base,
        "window": {"start": _iso(window_start), "end": _iso(window_end)},
        "stats": dict(stats),
        "overview": dict(overviews or {}),
        "market": (
            {
                "btc_usd": market.btc_price,
                "btc_change_24h": market.btc_change_24h,
                "eth_usd": market.eth_price,
                "eth_change_24h": market.eth_change_24h,
                "fear_greed": market.fear_greed_value,
                "fear_greed_label": market.fear_greed_label,
            }
            if market is not None
            else None
        ),
        "items": items,
    }
    return payload


def write_edition_api(
    payload: dict,
    *,
    date: str,
    editions_root: Path = EDITIONS_ROOT,
    api_root: Path = API_ROOT,
) -> List[Path]:
    """Write ``edition.json`` for the date plus the ``latest.json`` pointer."""
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    edition_path = editions_root / date / "edition.json"
    edition_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(edition_path, body)

    latest_path = api_root / "latest.json"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(latest_path, body)
    return [edition_path, latest_path]


def write_editions_index(
    records: Sequence[ArchiveRecord],
    *,
    api_root: Path = API_ROOT,
    site_url: str = DEFAULT_SITE_URL,
    limit: int = 90,
) -> Path:
    """Write the list of available editions for API consumers."""
    base = site_url.rstrip("/")
    counts: dict[str, int] = {}
    for record in records:
        counts[record.date] = counts.get(record.date, 0) + 1
    dates = sorted(counts, reverse=True)[:limit]
    payload = {
        "version": 1,
        "generated_at": _iso(datetime.now(timezone.utc)),
        "editions": [
            {
                "date": date,
                "items": counts[date],
                "json": f"{base}/editions/{date}/edition.json",
            }
            for date in dates
        ],
    }
    api_root.mkdir(parents=True, exist_ok=True)
    path = api_root / "editions.json"
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return path


def render_sitemap(
    records: Sequence[ArchiveRecord],
    *,
    threads: Iterable[tuple[str, Sequence[ArchiveRecord]]] = (),
    entities: Iterable[object] = (),
    events: Iterable[object] = (),
    site_url: str = DEFAULT_SITE_URL,
    generated_date: str | None = None,
) -> str:
    """Render indexable site pages as a deterministic XML sitemap."""
    base = site_url.rstrip("/")
    valid_records = [record for record in records if record.date_value is not None]
    latest = max((record.date for record in valid_records), default=generated_date)
    if latest is None:
        latest = datetime.now(timezone.utc).date().isoformat()

    urls: dict[str, str] = {
        f"{base}{path}": latest for path in _SITEMAP_STATIC_PATHS
    }
    for edition_date in sorted({record.date for record in valid_records}):
        urls[f"{base}/editions/{edition_date}/zh.html"] = edition_date
        urls[f"{base}/editions/{edition_date}/en.html"] = edition_date

    for thread_id, thread_records in threads:
        dates = [
            record.date
            for record in thread_records
            if record.date_value is not None
        ]
        if not thread_id or not dates:
            continue
        lastmod = max(dates)
        urls[f"{base}/threads/{thread_id}/"] = lastmod
        urls[f"{base}/en/threads/{thread_id}/"] = lastmod

    for entity in entities:
        slug = str(getattr(entity, "slug", "")).strip()
        entity_records = getattr(entity, "records", ())
        dates = [
            record.date
            for record in entity_records
            if isinstance(record, ArchiveRecord) and record.date_value is not None
        ]
        if not slug or not dates:
            continue
        lastmod = max(dates)
        urls[f"{base}/entity/{slug}/"] = lastmod
        urls[f"{base}/en/entity/{slug}/"] = lastmod

    for event in events:
        event_id = str(getattr(event, "event_id", "")).strip()
        changed = getattr(event, "last_material_change_at", None)
        if not event_id or not isinstance(changed, datetime):
            continue
        lastmod = changed.date().isoformat()
        urls[f"{base}/events/{event_id}/"] = lastmod
        urls[f"{base}/en/events/{event_id}/"] = lastmod

    entries = "\n".join(
        "  <url>"
        f"<loc>{html.escape(url, quote=True)}</loc>"
        f"<lastmod>{html.escape(lastmod)}</lastmod>"
        "</url>"
        for url, lastmod in sorted(urls.items())
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{entries}\n"
        "</urlset>\n"
    )


def write_sitemap(
    records: Sequence[ArchiveRecord],
    *,
    threads: Iterable[tuple[str, Sequence[ArchiveRecord]]] = (),
    entities: Iterable[object] = (),
    events: Iterable[object] = (),
    path: Path = SITEMAP_PATH,
    site_url: str = DEFAULT_SITE_URL,
) -> Path:
    """Write the sitemap refreshed by every published daily edition."""
    _atomic_write_text(
        path,
        render_sitemap(
            records,
            threads=threads,
            entities=entities,
            events=events,
            site_url=site_url,
        ),
    )
    return path


def _atom_entry(
    record: ArchiveRecord,
    language: str,
    *,
    base: str,
) -> str:
    title = html.escape(record.title_for(language) or record.url, quote=True)
    summary = html.escape(record.summary_for(language), quote=True)
    link = html.escape(record.url, quote=True)
    entry_id = html.escape(f"{base}/editions/{record.date}/#{record.item_id}", quote=True)
    updated = f"{record.date}T00:00:00Z"
    return (
        "  <entry>\n"
        f"    <title>{title}</title>\n"
        f'    <link href="{link}"/>\n'
        f"    <id>{entry_id}</id>\n"
        f"    <updated>{updated}</updated>\n"
        f"    <summary>{summary}</summary>\n"
        "  </entry>\n"
    )


def render_category_feed(
    records: Sequence[ArchiveRecord],
    *,
    category: str,
    language: str,
    site_url: str = DEFAULT_SITE_URL,
    limit: int = 40,
) -> str:
    """Render one Atom feed for a top-level category."""
    base = site_url.rstrip("/")
    title = _FEED_TITLES.get((category, language), f"BMTNews · {category}")
    self_url = f"{base}/feeds/{category}-{language}.xml"
    selected = [
        record for record in records if record.top_category == category
    ][:limit]
    updated = (
        f"{selected[0].date}T00:00:00Z"
        if selected
        else _iso(datetime.now(timezone.utc))
    )
    entries = "".join(
        _atom_entry(record, language, base=base) for record in selected
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom">\n'
        f"  <title>{html.escape(title, quote=True)}</title>\n"
        f'  <link href="{self_url}" rel="self"/>\n'
        f'  <link href="{base}/"/>\n'
        f"  <id>{self_url}</id>\n"
        f"  <updated>{updated}</updated>\n"
        f"{entries}"
        "</feed>\n"
    )


def write_category_feeds(
    records: Sequence[ArchiveRecord],
    languages: Iterable[str],
    *,
    feeds_root: Path = FEEDS_ROOT,
    site_url: str = DEFAULT_SITE_URL,
) -> List[Path]:
    """Write one Atom feed per top-level category and language."""
    ordered = sorted(
        records, key=lambda record: (record.date, -record.rank), reverse=True
    )
    feeds_root.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for language in languages:
        normalized = "en" if str(language).lower().startswith("en") else "zh"
        for category in FEED_CATEGORIES:
            path = feeds_root / f"{category}-{normalized}.xml"
            _atomic_write_text(
                path,
                render_category_feed(
                    ordered,
                    category=category,
                    language=normalized,
                    site_url=site_url,
                ),
            )
            written.append(path)
    return written
