"""Static thread, entity, and weekly pages generated from the archive.

These pages turn the daily stream into durable, linkable assets: a thread
page follows one event across days, an entity page collects everything
published about a company, protocol, or regulator. They are plain Jekyll
pages written by the pipeline, so no runtime service is involved.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import date as date_type, timedelta
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from ._file_utils import _atomic_write_text
from .archive import ArchiveRecord
from .threads import EntitySummary


# Shared HTML helpers; same escaping rules as the daily feed rendering.
from .web_feed import _escape as escape_text, _safe_url as safe_url

logger = logging.getLogger(__name__)


def _as_date(value: str) -> Optional[date_type]:
    try:
        return date_type.fromisoformat(value)
    except (TypeError, ValueError):
        return None

THREADS_ROOT = Path("docs/threads")
ENTITY_ROOT = Path("docs/entity")
WEEKLY_ROOT = Path("docs/weekly")
DATA_ROOT = Path("docs/_data")

_LABELS = {
    "zh": {
        "threads_title": "事件线",
        "threads_intro": "跨天追踪的持续事件，最新进展在最上面。",
        "entities_title": "实体索引",
        "entities_intro": "按公司、协议、监管机构聚合的历史报道。",
        "thread_prefix": "事件线",
        "entity_prefix": "实体",
        "days": "天",
        "entries": "条",
        "timeline": "时间线",
        "mentions": "报道",
        "empty": "暂无内容。",
        "back": "返回首页",
        "back_entities": "全部实体",
        "back_threads": "全部事件线",
        "last_seen": "最近报道",
        "peak_score": "最高评分",
        "weekly_title": "本周回顾",
    },
    "en": {
        "threads_title": "Story Threads",
        "threads_intro": "Continuing events tracked across days, most recent first.",
        "entities_title": "Entity Index",
        "entities_intro": "Coverage grouped by company, protocol, and regulator.",
        "thread_prefix": "Thread",
        "entity_prefix": "Entity",
        "days": "days",
        "entries": "entries",
        "timeline": "Timeline",
        "mentions": "Coverage",
        "empty": "Nothing here yet.",
        "back": "Back to the feed",
        "back_entities": "All entities",
        "back_threads": "All threads",
        "last_seen": "Last seen",
        "peak_score": "Peak score",
        "weekly_title": "Weekly Review",
    },
}


def _front_matter(
    *,
    title: str,
    permalink: str,
    language: str,
    description: str = "",
) -> str:
    # Titles reach the raw <title> element through Liquid, so markup
    # characters are removed here rather than escaped downstream.
    def _plain(value: str) -> str:
        return (
            str(value)
            .replace('"', "'")
            .replace("<", "")
            .replace(">", "")
            .replace("\n", " ")
            .strip()
        )

    safe_title = _plain(title)
    safe_description = _plain(description)[:180]
    return (
        "---\n"
        "layout: default\n"
        f'title: "{safe_title}"\n'
        f"permalink: {permalink}\n"
        f"interface_language: {language}\n"
        f'description: "{safe_description}"\n'
        "page_type: archive\n"
        "---\n\n"
    )


def _record_row(record: ArchiveRecord, language: str) -> str:
    labels = _LABELS[language]
    title = escape_text(record.title_for(language) or record.url)
    url = safe_url(record.url)
    title_html = (
        f'<a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a>'
        if url
        else title
    )
    score = (
        f'<span class="score-badge" data-tier="'
        f'{"high" if (record.score or 0) >= 9 else "good" if (record.score or 0) >= 7 else "mid"}'
        f'">{record.score:.1f}</span>'
        if record.score is not None
        else ""
    )
    summary = escape_text(record.summary_for(language))
    source = escape_text(record.source_label or record.source_type)
    return (
        '<li class="archive-row">'
        f'<time datetime="{escape_text(record.date)}">{escape_text(record.date)}</time>'
        f'<div class="archive-row-body"><h3>{title_html}</h3>'
        + (f'<p class="archive-row-summary">{summary}</p>' if summary else "")
        + f'<p class="archive-row-meta">{source}</p></div>'
        f"{score}</li>"
    )


def _records_list(records: Sequence[ArchiveRecord], language: str) -> str:
    if not records:
        return f'<p class="empty-state">{_LABELS[language]["empty"]}</p>'
    rows = "".join(_record_row(record, language) for record in records)
    return f'<ul class="archive-list">{rows}</ul>'


def render_thread_page(
    thread_id: str,
    records: Sequence[ArchiveRecord],
    language: str,
) -> str:
    labels = _LABELS[language]
    ordered = sorted(records, key=lambda r: (r.date, r.rank), reverse=True)
    latest = ordered[0]
    days = len({record.date for record in records})
    title = latest.title_for(language) or thread_id
    prefix = "" if language == "zh" else "/en"
    stats = (
        _stat(str(days), labels["days"])
        + _stat(str(len(ordered)), labels["entries"])
        + _stat(latest.date, labels["last_seen"])
    )
    body = (
        f'<div class="archive-stats">{stats}</div>'
        f"<h2>{escape_text(labels['timeline'])}</h2>"
        f"{_records_list(ordered, language)}"
        f'<p class="archive-back"><a href="{prefix}/threads/">'
        f'{labels["back_threads"]}</a> · '
        f'<a href="{prefix}/">{labels["back"]}</a></p>'
    )
    return (
        _front_matter(
            title=title,
            permalink=f"{prefix}/threads/{thread_id}/",
            language=language,
            description=latest.summary_for(language),
        )
        + body
        + "\n"
    )


def _stat(value: str, label: str) -> str:
    return (
        f'<div class="archive-stat"><strong>{escape_text(value)}</strong>'
        f"<span>{escape_text(label)}</span></div>"
    )


def render_entity_page(entity: EntitySummary, language: str) -> str:
    labels = _LABELS[language]
    prefix = "" if language == "zh" else "/en"
    dates = sorted({record.date for record in entity.records})
    top_score = max(
        (record.score for record in entity.records if record.score is not None),
        default=None,
    )
    stats = _stat(str(entity.count), labels["entries"]) + _stat(
        str(len(dates)), labels["days"]
    )
    if dates:
        stats += _stat(dates[-1], labels["last_seen"])
    if top_score is not None:
        stats += _stat(f"{top_score:.1f}", labels["peak_score"])
    body = (
        f'<div class="archive-stats">{stats}</div>'
        f"<h2>{escape_text(labels['mentions'])}</h2>"
        f"{_records_list(entity.records[:60], language)}"
        f'<p class="archive-back"><a href="{prefix}/entity/">'
        f'{labels["back_entities"]}</a> · '
        f'<a href="{prefix}/">{labels["back"]}</a></p>'
    )
    description = (
        entity.records[0].summary_for(language) if entity.records else ""
    )
    return (
        _front_matter(
            title=entity.label,
            permalink=f"{prefix}/entity/{entity.slug}/",
            language=language,
            description=description,
        )
        + body
        + "\n"
    )


def _dominant_category(records: Sequence[ArchiveRecord]) -> str:
    counts = Counter(
        record.top_category or record.category
        for record in records
        if (record.top_category or record.category)
    )
    return counts.most_common(1)[0][0] if counts else ""


def build_thread_index_data(
    threads: Sequence[tuple[str, List[ArchiveRecord]]],
) -> dict:
    """Data consumed by the always-present /threads/ index page."""
    rows = []
    for thread_id, records in threads:
        latest = max(records, key=lambda record: (record.date, record.rank))
        dates = {record.date for record in records}
        rows.append(
            {
                "thread_id": thread_id,
                "latest_date": latest.date,
                "first_date": min(dates),
                "days": len(dates),
                "entries": len(records),
                "category": _dominant_category(records),
                "title_zh": latest.title_zh,
                "title_en": latest.title_en,
                "summary_zh": latest.summary_zh,
                "summary_en": latest.summary_en,
            }
        )
    return {"threads": rows}


def build_entity_index_data(
    entities: Sequence[EntitySummary],
    *,
    recent_days: int = 7,
) -> dict:
    """Data consumed by the always-present /entity/ index page.

    A bare name and a count reads as a tag cloud: it says which words recur
    but nothing about what happened, so every entry looks equally worth a
    click. The extra fields here — what was published most recently, how
    long the coverage has run, whether it is still active — are what let the
    index be scanned rather than merely browsed.
    """
    newest = max(
        (record.date for entity in entities for record in entity.records),
        default="",
    )
    cutoff = ""
    newest_value = _as_date(newest)
    if newest_value is not None:
        cutoff = (newest_value - timedelta(days=recent_days - 1)).isoformat()

    rows = []
    for entity in entities:
        records = sorted(entity.records, key=lambda record: record.date)
        latest = records[-1]
        rows.append(
            {
                "slug": entity.slug,
                "label": entity.label,
                "mentions": entity.count,
                "days": len({record.date for record in records}),
                "first_date": records[0].date,
                "latest_date": latest.date,
                "recent": sum(1 for record in records if record.date >= cutoff)
                if cutoff
                else 0,
                "category": _dominant_category(records),
                "top_score": max(
                    (record.score for record in records if record.score is not None),
                    default=None,
                ),
                "title_zh": latest.title_zh,
                "title_en": latest.title_en,
            }
        )
    # Still-developing subjects first; a name last seen two weeks ago is a
    # lookup, not something to put at the top of the page.
    rows.sort(key=lambda row: (-row["recent"], -row["mentions"], row["slug"]))
    return {"entities": rows}


def write_index_data(
    threads: Sequence[tuple[str, List[ArchiveRecord]]],
    entities: Sequence[EntitySummary],
    *,
    data_root: Path = DATA_ROOT,
) -> List[Path]:
    """Write the Jekyll data files backing the index pages."""
    data_root.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for name, payload in (
        ("threads.json", build_thread_index_data(threads)),
        ("entities.json", build_entity_index_data(entities)),
    ):
        path = data_root / name
        _atomic_write_text(
            path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
        written.append(path)
    return written


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, content)


def publish_archive_pages(
    threads: Sequence[tuple[str, List[ArchiveRecord]]],
    entities: Sequence[EntitySummary],
    languages: Iterable[str],
    *,
    threads_root: Path = THREADS_ROOT,
    entity_root: Path = ENTITY_ROOT,
    data_root: Path = DATA_ROOT,
) -> dict[str, int]:
    """Write every thread and entity page plus the index data files.

    The index pages themselves are committed Jekyll pages that read these
    data files, so /threads/ and /entity/ resolve from the first deploy
    even before any archive content exists.
    """
    written = {"threads": 0, "entities": 0}
    write_index_data(threads, entities, data_root=data_root)
    for language in languages:
        normalized = "en" if str(language).lower().startswith("en") else "zh"
        suffix = "" if normalized == "zh" else "en-"
        for thread_id, records in threads:
            _write(
                threads_root / f"{suffix}{thread_id}.html",
                render_thread_page(thread_id, records, normalized),
            )
            written["threads"] += 1
        for entity in entities:
            _write(
                entity_root / f"{suffix}{entity.slug}.html",
                render_entity_page(entity, normalized),
            )
            written["entities"] += 1
    return written
