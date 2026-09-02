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
from .events import EventUpdate, TrackedEvent
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
EVENTS_ROOT = Path("docs/events")
EVENT_API_ROOT = Path("docs/api/events")
EVENT_API_INDEX = Path("docs/api/events.json")
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
    redirect_to: str = "",
    alternate_url: str = "",
    noindex: bool = False,
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
    extra = ""
    if redirect_to:
        extra += f"redirect_to: {_plain(redirect_to)}\n"
    if alternate_url:
        extra += f"alternate_url: {_plain(alternate_url)}\n"
    if noindex:
        extra += "noindex: true\n"
    return (
        "---\n"
        "layout: default\n"
        f'title: "{safe_title}"\n'
        f"permalink: {permalink}\n"
        f"interface_language: {language}\n"
        f'description: "{safe_description}"\n'
        "page_type: archive\n"
        f"{extra}"
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


def _event_value(event: TrackedEvent, field: str, language: str) -> str:
    preferred = getattr(event, f"{field}_{language}")
    fallback = getattr(event, f"{field}_{'en' if language == 'zh' else 'zh'}")
    return preferred or fallback


def _event_update_value(update: EventUpdate, field: str, language: str) -> str:
    preferred = getattr(update, f"{field}_{language}")
    fallback = getattr(update, f"{field}_{'en' if language == 'zh' else 'zh'}")
    return preferred or fallback


_EVENT_LABELS = {
    "zh": {
        "status": "状态",
        "updates": "次实质进展",
        "sources": "个来源",
        "timeline": "进展时间线",
        "back": "全部事件线",
        "home": "返回首页",
        "first_seen": "首次追踪",
        "last_changed": "最近变化",
        "current_state": "当前状态",
        "json": "JSON 数据",
        "source_evidence": "来源依据",
        "state_after": "此后状态",
        "precision_exact": "事件时间",
        "precision_published": "报道时间",
        "precision_edition": "历史刊期",
    },
    "en": {
        "status": "status",
        "updates": "material updates",
        "sources": "sources",
        "timeline": "Progress timeline",
        "back": "All events",
        "home": "Back to the feed",
        "first_seen": "First tracked",
        "last_changed": "Last changed",
        "current_state": "Current state",
        "json": "JSON data",
        "source_evidence": "Source evidence",
        "state_after": "State after update",
        "precision_exact": "event time",
        "precision_published": "publication time",
        "precision_edition": "edition date",
    },
}

_STATUS_LABELS = {
    "developing": {"zh": "进展中", "en": "Developing"},
    "monitoring": {"zh": "持续观察", "en": "Monitoring"},
    "resolved": {"zh": "已解决", "en": "Resolved"},
    "closed": {"zh": "已结束", "en": "Closed"},
    "disputed": {"zh": "存在争议", "en": "Disputed"},
}

_UPDATE_LABELS = {
    "initial": {"zh": "首次出现", "en": "Initial"},
    "confirmation": {"zh": "确认", "en": "Confirmation"},
    "escalation": {"zh": "升级", "en": "Escalation"},
    "response": {"zh": "回应", "en": "Response"},
    "remediation": {"zh": "修复", "en": "Remediation"},
    "resolution": {"zh": "解决", "en": "Resolution"},
    "aftermath": {"zh": "后续影响", "en": "Aftermath"},
    "correction": {"zh": "更正", "en": "Correction"},
}


def _event_stamp(value, language: str, *, include_time: bool = False) -> str:
    if include_time:
        return value.strftime("%Y.%m.%d %H:%M" if language == "zh" else "%Y-%m-%d %H:%M")
    return value.strftime("%Y.%m.%d" if language == "zh" else "%Y-%m-%d")


def event_payload(event: TrackedEvent, *, site_url: str = "https://bmt.news") -> dict:
    """Return one stable, bilingual public event document."""
    base = site_url.rstrip("/")
    return {
        "version": 1,
        "event_id": event.event_id,
        "url": f"{base}/events/{event.event_id}/",
        "json": f"{base}/api/events/{event.event_id}.json",
        "type": event.event_type.value,
        "status": event.status.value,
        "category": event.category,
        "title": {"zh": event.title_zh, "en": event.title_en},
        "current_state": {
            "zh": event.current_state_zh,
            "en": event.current_state_en,
        },
        "first_seen_at": event.first_seen_at.isoformat(),
        "last_updated_at": event.last_updated_at.isoformat(),
        "last_material_change_at": event.last_material_change_at.isoformat(),
        "confidence": event.confidence,
        "updates_count": len(
            [update for update in event.updates if update.material_change]
        ),
        "sources_count": len(
            {
                source.url
                for update in event.updates
                for source in update.sources
            }
        ),
        "entities": event.entities,
        "identifiers": event.identifiers,
        "topics": event.topics,
        "updates": [update.model_dump(mode="json") for update in event.updates],
    }


def write_event_api(
    events: Sequence[TrackedEvent],
    *,
    api_root: Path = EVENT_API_ROOT,
    index_path: Path = EVENT_API_INDEX,
) -> list[Path]:
    """Write an event index and one independently cacheable JSON document each."""
    visible = [
        event
        for event in events
        if len([update for update in event.updates if update.material_change]) >= 2
    ]
    visible.sort(
        key=lambda event: (event.last_material_change_at, event.event_id),
        reverse=True,
    )
    paths: list[Path] = []
    api_root.mkdir(parents=True, exist_ok=True)
    for event in events:
        path = api_root / f"{event.event_id}.json"
        _write(
            path,
            json.dumps(event_payload(event), ensure_ascii=False, indent=2) + "\n",
        )
        paths.append(path)
    index = {
        "version": 1,
        "events": [
            {
                "event_id": event.event_id,
                "url": f"https://bmt.news/events/{event.event_id}/",
                "json": f"https://bmt.news/api/events/{event.event_id}.json",
                "status": event.status.value,
                "type": event.event_type.value,
                "title": {"zh": event.title_zh, "en": event.title_en},
                "current_state": {
                    "zh": event.current_state_zh,
                    "en": event.current_state_en,
                },
                "first_seen_at": event.first_seen_at.isoformat(),
                "last_material_change_at": event.last_material_change_at.isoformat(),
                "updates_count": len(
                    [update for update in event.updates if update.material_change]
                ),
                "sources_count": len(
                    {
                        source.url
                        for update in event.updates
                        for source in update.sources
                    }
                ),
            }
            for event in visible
        ],
    }
    _write(index_path, json.dumps(index, ensure_ascii=False, indent=2) + "\n")
    paths.append(index_path)
    return paths


def render_event_page(event: TrackedEvent, language: str) -> str:
    """Render a compact event header and evidence-backed chronological timeline."""
    normalized = "en" if language == "en" else "zh"
    prefix = "" if normalized == "zh" else "/en"
    title = _event_value(event, "title", normalized) or event.event_id
    current_state = _event_value(event, "current_state", normalized)
    labels = _EVENT_LABELS[normalized]
    status_label = _STATUS_LABELS[event.status.value][normalized]
    material_updates = [update for update in event.updates if update.material_change]
    source_count = len(
        {source.url for update in event.updates for source in update.sources}
    )
    stats = (
        _stat(status_label, labels["status"])
        + _stat(str(len(material_updates)), labels["updates"])
        + _stat(str(source_count), labels["sources"])
        + _stat(_event_stamp(event.first_seen_at, normalized), labels["first_seen"])
        + _stat(
            _event_stamp(event.last_material_change_at, normalized),
            labels["last_changed"],
        )
    )
    rows = []
    for update in event.updates:
        changed = _event_update_value(update, "what_changed", normalized)
        update_title = _event_update_value(update, "title", normalized) or changed
        state_after = _event_update_value(update, "current_state", normalized)
        sources = []
        for source in update.sources:
            url = safe_url(source.url)
            label = escape_text(source.label or source.source_type or source.url)
            sources.append(
                f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'
                if url
                else label
            )
        source_html = " · ".join(sources)
        stamp = update.occurred_at.isoformat()
        include_time = update.time_precision.value != "edition"
        display_stamp = _event_stamp(
            update.occurred_at, normalized, include_time=include_time
        )
        precision = labels[f"precision_{update.time_precision.value}"]
        update_label = _UPDATE_LABELS[update.update_type.value][normalized]
        correction = " is-correction" if update.update_type.value == "correction" else ""
        rows.append(
            f'<li class="event-update{correction}" id="{escape_text(update.update_id)}">'
            '<div class="event-update-marker" aria-hidden="true"></div>'
            '<div class="event-update-content">'
            '<p class="event-update-kicker">'
            f'<time datetime="{escape_text(stamp)}">{escape_text(display_stamp)}</time>'
            f'<span class="event-update-type">{escape_text(update_label)}</span>'
            f'<span>{escape_text(precision)}</span></p>'
            f'<h3>{escape_text(update_title)}</h3>'
            f'<p class="event-update-change">{escape_text(changed)}</p>'
            + (
                f'<p class="event-update-state"><strong>{escape_text(labels["state_after"])}：</strong>'
                f'{escape_text(state_after)}</p>'
                if state_after and state_after != changed
                else ""
            )
            + (
                f'<p class="event-update-sources"><strong>{escape_text(labels["source_evidence"])}：</strong>'
                f"{source_html}</p>"
                if source_html
                else ""
            )
            + "</div></li>"
        )
    body = (
        f'<div class="event-status-line"><span class="event-status" data-status="{event.status.value}">'
        f'{escape_text(status_label)}</span><span>{escape_text(event.event_type.value)}</span></div>'
        f'<div class="archive-stats event-stats">{stats}</div>'
        + (
            f'<section class="event-current-state"><h2>{escape_text(labels["current_state"])}</h2>'
            f'<p>{escape_text(current_state)}</p></section>'
            if current_state
            else ""
        )
        + f'<div class="event-timeline-heading"><h2>{escape_text(labels["timeline"])}</h2>'
        + f'<a href="/api/events/{event.event_id}.json">{escape_text(labels["json"])}</a></div>'
        + f'<ol class="event-timeline">{"".join(rows)}</ol>'
        + f'<p class="archive-back"><a href="{prefix}/threads/">'
        + f'{escape_text(labels["back"])}</a> · '
        + f'<a href="{prefix}/">{escape_text(labels["home"])}</a></p>'
    )
    return (
        _front_matter(
            title=title,
            permalink=f"{prefix}/events/{event.event_id}/",
            language=normalized,
            description=current_state,
            alternate_url=(
                f"/en/events/{event.event_id}/"
                if normalized == "zh"
                else f"/events/{event.event_id}/"
            ),
        )
        + body
        + "\n"
    )


def render_legacy_event_redirect(
    legacy_thread_id: str,
    event: TrackedEvent,
    language: str,
) -> str:
    normalized = "en" if language == "en" else "zh"
    prefix = "" if normalized == "zh" else "/en"
    destination = f"{prefix}/events/{event.event_id}/"
    title = _event_value(event, "title", normalized) or event.event_id
    copy = (
        "这条旧事件线已经迁移到新的事件页面。"
        if normalized == "zh"
        else "This legacy thread has moved to the new event page."
    )
    link = "查看事件" if normalized == "zh" else "View event"
    return (
        _front_matter(
            title=title,
            permalink=f"{prefix}/threads/{legacy_thread_id}/",
            language=normalized,
            description=copy,
            redirect_to=destination,
            noindex=True,
        )
        + f'<p class="archive-lede">{escape_text(copy)}</p>'
        + f'<p><a href="{destination}">{escape_text(link)}</a></p>\n'
    )


def render_retired_thread_page(
    legacy_thread_id: str,
    events: Sequence[TrackedEvent],
    language: str,
) -> str:
    normalized = "en" if language == "en" else "zh"
    prefix = "" if normalized == "zh" else "/en"
    title = "旧事件线已拆分" if normalized == "zh" else "Legacy thread retired"
    copy = (
        "旧页面曾把多个不同事件放在一起，现已拆分。原始链接保留在此，避免读者进入错误的事件脉络。"
        if normalized == "zh"
        else "This page previously combined distinct events. The URL remains as an index to the corrected event pages."
    )
    items = []
    for event in sorted(events, key=lambda item: (item.first_seen_at, item.event_id)):
        event_title = _event_value(event, "title", normalized) or event.event_id
        items.append(
            '<li class="archive-row"><div class="archive-row-body">'
            f'<h3><a href="{prefix}/events/{event.event_id}/">'
            f"{escape_text(event_title)}</a></h3>"
            f'<p class="archive-row-meta">{escape_text(event.status.value)}</p>'
            "</div></li>"
        )
    return (
        _front_matter(
            title=title,
            permalink=f"{prefix}/threads/{legacy_thread_id}/",
            language=normalized,
            description=copy,
            noindex=True,
        )
        + f'<p class="archive-lede">{escape_text(copy)}</p>'
        + f'<ul class="archive-list">{"".join(items)}</ul>\n'
    )


def build_event_index_data(events: Sequence[TrackedEvent]) -> dict:
    """Build a shape compatible with the existing threads index template."""
    rows = []
    for event in events:
        material = [update for update in event.updates if update.material_change]
        if len(material) < 2:
            continue
        first = min(update.first_seen_at for update in material).date().isoformat()
        latest = max(update.first_seen_at for update in material).date().isoformat()
        rows.append(
            {
                "thread_id": event.event_id,
                "event_id": event.event_id,
                "latest_date": latest,
                "first_date": first,
                "days": len({update.first_seen_at.date() for update in material}),
                "entries": len(material),
                "updates_count": len(material),
                "sources_count": len(
                    {
                        source.url
                        for update in event.updates
                        for source in update.sources
                    }
                ),
                "category": event.category,
                "status": event.status.value,
                "status_zh": _STATUS_LABELS[event.status.value]["zh"],
                "status_en": _STATUS_LABELS[event.status.value]["en"],
                "event_type": event.event_type.value,
                "title_zh": event.title_zh,
                "title_en": event.title_en,
                "summary_zh": event.current_state_zh,
                "summary_en": event.current_state_en,
            }
        )
    rows.sort(key=lambda row: (row["latest_date"], row["event_id"]), reverse=True)
    return {"threads": rows}


def publish_event_compatibility_pages(
    events: Sequence[TrackedEvent],
    redirects: dict[str, str],
    retired: dict[str, list[str]],
    languages: Iterable[str],
    *,
    events_root: Path = EVENTS_ROOT,
    threads_root: Path = THREADS_ROOT,
    thread_index_path: Path = DATA_ROOT / "threads.json",
    event_api_root: Path | None = None,
    event_api_index: Path | None = None,
) -> dict[str, int]:
    """Write stable event targets and preserve every reviewed legacy URL."""
    by_id = {event.event_id: event for event in events}
    mapped_targets = set(redirects.values())
    for target_ids in retired.values():
        mapped_targets.update(target_ids)
    missing = mapped_targets - by_id.keys()
    if missing:
        raise ValueError(
            "legacy URL map references missing events: "
            + ", ".join(sorted(missing))
        )
    _write(
        thread_index_path,
        json.dumps(
            build_event_index_data(events), ensure_ascii=False, indent=2
        )
        + "\n",
    )
    site_root = thread_index_path.parent.parent
    write_event_api(
        events,
        api_root=event_api_root or site_root / "api" / "events",
        index_path=event_api_index or site_root / "api" / "events.json",
    )
    written = {"events": 0, "redirects": 0, "retired": 0}
    for language in languages:
        normalized = "en" if str(language).lower().startswith("en") else "zh"
        suffix = "" if normalized == "zh" else "en-"
        for event in events:
            _write(
                events_root / f"{suffix}{event.event_id}.html",
                render_event_page(event, normalized),
            )
            written["events"] += 1
        for legacy_id, event_id in redirects.items():
            _write(
                threads_root / f"{suffix}{legacy_id}.html",
                render_legacy_event_redirect(legacy_id, by_id[event_id], normalized),
            )
            written["redirects"] += 1
        for legacy_id, target_ids in retired.items():
            _write(
                threads_root / f"{suffix}{legacy_id}.html",
                render_retired_thread_page(
                    legacy_id, [by_id[target] for target in target_ids], normalized
                ),
            )
            written["retired"] += 1
    return written


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
