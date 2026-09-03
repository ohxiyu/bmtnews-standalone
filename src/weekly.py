"""Weekly digest and scoring-calibration review built from the archive.

Both outputs read only archived editions, so the weekly job is cheap and
independent of the daily pipeline's staging state:

- the **weekly digest** is a reader-facing page summarizing the week
- the **calibration review** is a maintainer-facing note comparing what the
  curator scored highly against what actually kept generating coverage

Neither can block the daily edition: they run in their own workflow.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta
from pathlib import Path
from typing import List, Literal, Mapping, Optional, Sequence

from pydantic import BaseModel, Field, ValidationError

from ._file_utils import _atomic_write_text
from .ai.utils import parse_json_response, unwrap_prose_response
from .archive import ArchiveRecord
from .threads import collect_entities, collect_threads
from .web_feed import _safe_url as safe_url

logger = logging.getLogger(__name__)

WEEKLY_ROOT = Path("docs/weekly")
DATA_ROOT = Path("docs/_data")
CALIBRATION_ROOT = DATA_ROOT / "calibration"

_LANGUAGE_NAMES = {
    "zh": "Simplified Chinese (简体中文)",
    "en": "English",
}
_LABELS = {
    "zh": {
        "title": "本周回顾",
        "intro": "过去 7 天的重点回顾，按主线、持续事件和值得记住三部分整理。",
        "stats": "本周共发布 {items} 条，覆盖 {days} 天，其中 {threads} 条持续事件。",
        "index_title": "周报存档",
        "empty": "本周暂无归档内容。",
        "back": "返回首页",
    },
    "en": {
        "title": "Weekly Review",
        "intro": "The past seven days, organized by throughline, continuing threads, and stories worth remembering.",
        "stats": "{items} stories published across {days} days, including {threads} continuing threads.",
        "index_title": "Weekly Archive",
        "empty": "Nothing archived for this week yet.",
        "back": "Back to the feed",
    },
}


@dataclass
class WeeklyContext:
    """Everything the weekly prompts need, derived from the archive."""

    start: date_type
    end: date_type
    records: List[ArchiveRecord] = field(default_factory=list)
    threads: List[tuple[str, List[ArchiveRecord]]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.records

    @property
    def stats(self) -> dict[str, int]:
        return {
            "items": len(self.records),
            "days": len({record.date for record in self.records}),
            "threads": len(self.threads),
        }


class WeeklyThroughline(BaseModel):
    """The one conclusion that frames a weekly edition."""

    title: str
    summary: str


class WeeklyDigestItem(BaseModel):
    """One scannable development backed by archived record identifiers."""

    section: Literal["continuing", "remember"]
    title: str
    change: str
    why_it_matters: str
    evidence_ids: List[str] = Field(default_factory=list)


class WeeklyDigest(BaseModel):
    """Structured editorial output rendered by deterministic templates."""

    throughline: WeeklyThroughline
    items: List[WeeklyDigestItem] = Field(default_factory=list)


def build_weekly_context(
    records: Sequence[ArchiveRecord],
    *,
    end: date_type,
    days: int = 7,
) -> WeeklyContext:
    """Select the archive slice for the week ending on ``end`` (inclusive)."""
    start = end - timedelta(days=days - 1)
    window = [
        record
        for record in records
        if (value := record.date_value) is not None and start <= value <= end
    ]
    window.sort(key=lambda record: (record.date, record.rank))
    return WeeklyContext(
        start=start,
        end=end,
        records=window,
        threads=collect_threads(window, minimum_days=2, limit=12),
    )


def _format_items(records: Sequence[ArchiveRecord], language: str) -> str:
    lines = []
    for record in records:
        score = f"{record.score:.1f}" if record.score is not None else "—"
        summary = record.summary_for(language)
        event = record.event_id or record.thread_id or "none"
        lines.append(
            f"- [id={record.item_id}] [date={record.date}] [score={score}/10] "
            f"[event={event}] {record.title_for(language)}"
            + (f" — {summary}" if summary else "")
        )
    return "\n".join(lines) if lines else "(none)"


def _format_threads(
    threads: Sequence[tuple[str, List[ArchiveRecord]]],
    language: str,
) -> str:
    lines = []
    for thread_id, records in threads:
        dates = sorted({record.date for record in records})
        titles = " → ".join(
            record.title_for(language)
            for record in sorted(records, key=lambda r: (r.date, r.rank))
        )
        lines.append(f"- [{thread_id}] {dates[0]}…{dates[-1]}: {titles}")
    return "\n".join(lines) if lines else "(none)"


def _clean_copy(value: object, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


def _normalize_digest(digest: WeeklyDigest) -> WeeklyDigest:
    throughline = WeeklyThroughline(
        title=_clean_copy(digest.throughline.title, limit=120),
        summary=_clean_copy(digest.throughline.summary, limit=900),
    )
    items = []
    for item in digest.items[:8]:
        title = _clean_copy(item.title, limit=140)
        change = _clean_copy(item.change, limit=520)
        why = _clean_copy(item.why_it_matters, limit=360)
        if not title or not change:
            continue
        items.append(
            WeeklyDigestItem(
                section=item.section,
                title=title,
                change=change,
                why_it_matters=why,
                evidence_ids=list(dict.fromkeys(item.evidence_ids))[:5],
            )
        )
    return WeeklyDigest(throughline=throughline, items=items)


_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)


def _legacy_digest(text: str, language: str) -> Optional[WeeklyDigest]:
    """Turn pre-structured Markdown into a safe fallback edition.

    The provider is still called in text mode because some configured models
    reject JSON response-format flags. If a provider ignores the new JSON
    instruction and returns the old Markdown shape, the weekly job remains
    publishable instead of silently losing the whole edition.
    """
    matches = list(_HEADING.finditer(text))
    if not matches:
        return None
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).lower()] = text[match.end() : end].strip()
    main_key = next(
        (key for key in sections if "主线" in key or "throughline" in key), None
    )
    if not main_key:
        return None
    main = re.sub(r"^[-*]\s+", "", sections[main_key]).strip()
    title = "本周判断" if language == "zh" else "This week's judgment"
    items: list[WeeklyDigestItem] = []
    for key, section in sections.items():
        if key == main_key:
            continue
        kind: Literal["continuing", "remember"] = (
            "remember" if "记住" in key or "remember" in key else "continuing"
        )
        for raw in re.findall(r"(?:^|\n)[-*]\s+(.+?)(?=\n[-*]\s+|\Z)", section, re.S):
            copy = re.sub(r"\s+", " ", raw).strip()
            item_title, separator, rest = copy.partition("：")
            if not separator:
                item_title, separator, rest = copy.partition(":")
            items.append(
                WeeklyDigestItem(
                    section=kind,
                    title=item_title[:140],
                    change=(rest or copy)[:520],
                    why_it_matters="",
                )
            )
    return _normalize_digest(
        WeeklyDigest(
            throughline=WeeklyThroughline(title=title, summary=main),
            items=items,
        )
    )


def parse_weekly_digest(response: object, language: str) -> Optional[WeeklyDigest]:
    """Parse the structured contract, retaining a Markdown compatibility path."""
    text = str(response or "").strip()
    payload = parse_json_response(text)
    if isinstance(payload, dict):
        try:
            digest = WeeklyDigest.model_validate(payload)
        except ValidationError:
            digest = None
        if digest is not None:
            normalized = _normalize_digest(digest)
            if normalized.throughline.summary:
                return normalized
    prose = unwrap_prose_response(
        response, keys=("digest", "review", "body", "markdown", "text")
    ).strip()
    return _legacy_digest(prose, language)


async def generate_weekly_digest(
    ai_client,
    context: WeeklyContext,
    *,
    language: str,
    max_items: int = 60,
) -> Optional[WeeklyDigest]:
    """Generate one structured weekly digest.

    Returns None only when there is nothing to write about or the model
    returned nothing usable. Provider errors are raised, not swallowed.
    """
    if context.is_empty:
        return None
    from .ai.prompts import WEEKLY_DIGEST_SYSTEM, WEEKLY_DIGEST_USER

    ranked = sorted(
        context.records,
        key=lambda record: (-(record.score or 0), record.date),
    )[:max_items]
    # Errors propagate to the caller, which owns the run report and can say
    # *why* nothing was produced. Swallowing them here is what let a 400 from
    # the provider look like a successful run for two weeks.
    response = await ai_client.complete(
        system=WEEKLY_DIGEST_SYSTEM,
        user=WEEKLY_DIGEST_USER.format(
            date=context.end.isoformat(),
            language_name=_LANGUAGE_NAMES.get(language, "English"),
            items=_format_items(ranked, language),
            threads=_format_threads(context.threads, language),
        ),
        response_format="text",
    )
    return parse_weekly_digest(response, language)


async def generate_calibration_review(
    ai_client,
    context: WeeklyContext,
    *,
    high_threshold: float = 8.0,
    language: str = "zh",
) -> Optional[str]:
    """Generate the maintainer-facing scoring audit.

    Returns None when there is nothing to audit. Provider errors are raised.
    """
    if context.is_empty:
        return None
    from .ai.prompts import SCORE_CALIBRATION_SYSTEM, SCORE_CALIBRATION_USER

    high = [r for r in context.records if (r.score or 0) >= high_threshold]
    low = [r for r in context.records if (r.score or 0) < high_threshold]
    if not high and not low:
        return None
    response = await ai_client.complete(
        system=SCORE_CALIBRATION_SYSTEM,
        user=SCORE_CALIBRATION_USER.format(
            date=context.end.isoformat(),
            high_threshold=f"{high_threshold:g}",
            high_items=_format_items(high[:40], language),
            low_items=_format_items(low[:40], language),
            threads=_format_threads(context.threads, language),
        ),
        response_format="text",
    )
    text = unwrap_prose_response(
        response, keys=("review", "calibration", "body", "markdown", "text")
    ).strip()
    return text or None


def _display_date(value: date_type, language: str) -> str:
    return value.strftime("%Y.%m.%d" if language == "zh" else "%Y-%m-%d")


def _digest_language_payload(
    digest: WeeklyDigest,
    context: WeeklyContext,
    language: str,
) -> dict:
    record_by_id = {record.item_id: record for record in context.records}
    entities = collect_entities(context.records, minimum_mentions=3, limit=12)
    entity_by_record: dict[str, list[dict]] = {}
    for entity in entities:
        link = f"{'/en' if language == 'en' else ''}/entity/{entity.slug}/"
        value = {"slug": entity.slug, "label": entity.label, "url": link}
        for record in entity.records:
            entity_by_record.setdefault(record.item_id, []).append(value)

    items = []
    for item in digest.items:
        evidence = []
        selected_records = []
        for item_id in item.evidence_ids:
            record = record_by_id.get(item_id)
            if record is None or record in selected_records:
                continue
            selected_records.append(record)
            url = safe_url(record.url)
            if url:
                evidence.append(
                    {
                        "date": record.date,
                        "title": record.title_for(language),
                        "url": url,
                        "source": record.source_label or record.source_type,
                    }
                )
        dates = sorted({record.date for record in selected_records})
        event_id = next(
            (record.event_id for record in selected_records if record.event_id), None
        )
        thread_id = next(
            (record.thread_id for record in selected_records if record.thread_id), None
        )
        linked_entities: list[dict] = []
        seen_entities: set[str] = set()
        for record in selected_records:
            for entity in entity_by_record.get(record.item_id, []):
                if entity["slug"] in seen_entities:
                    continue
                seen_entities.add(entity["slug"])
                linked_entities.append(entity)
        score_values = [
            record.score for record in selected_records if record.score is not None
        ]
        items.append(
            {
                "section": item.section,
                "title": item.title,
                "change": item.change,
                "why_it_matters": item.why_it_matters,
                "date_start": dates[0] if dates else context.start.isoformat(),
                "date_end": dates[-1] if dates else context.end.isoformat(),
                "score": max(score_values) if score_values else None,
                "sources_count": sum(
                    max(1, record.sources_count) for record in selected_records
                ),
                "event_url": (
                    f"{'/en' if language == 'en' else ''}/events/{event_id}/"
                    if event_id
                    else (
                        f"{'/en' if language == 'en' else ''}/threads/{thread_id}/"
                        if thread_id
                        else ""
                    )
                ),
                "entities": linked_entities[:4],
                "evidence": evidence[:3],
            }
        )

    event_groups: dict[str, list[ArchiveRecord]] = {}
    for record in context.records:
        event_id = record.event_id or record.thread_id
        if event_id:
            event_groups.setdefault(event_id, []).append(record)
    event_ranking = []
    for event_id, records in event_groups.items():
        latest = max(records, key=lambda record: (record.date, -record.rank))
        scores = [record.score for record in records if record.score is not None]
        is_event = any(record.event_id == event_id for record in records)
        event_ranking.append(
            {
                "id": event_id,
                "title": latest.title_for(language),
                "url": (
                    f"{'/en' if language == 'en' else ''}/"
                    f"{'events' if is_event else 'threads'}/{event_id}/"
                ),
                "entries": len(records),
                "latest_date": latest.date,
                "score": max(scores) if scores else None,
            }
        )
    event_ranking.sort(
        key=lambda row: (
            row["score"] if row["score"] is not None else -1,
            row["entries"],
            row["latest_date"],
        ),
        reverse=True,
    )
    entity_ranking = [
        {
            "slug": entity.slug,
            "label": entity.label,
            "mentions": entity.count,
            "url": f"{'/en' if language == 'en' else ''}/entity/{entity.slug}/",
        }
        for entity in entities[:5]
    ]
    return {
        "throughline": digest.throughline.model_dump(),
        "items": items,
        "event_ranking": event_ranking[:5],
        "entity_ranking": entity_ranking,
    }


def build_weekly_index_entry(
    context: WeeklyContext,
    digests: Mapping[str, WeeklyDigest],
) -> dict:
    """Build one bilingual edition for the data-driven weekly templates."""
    entities = collect_entities(context.records, minimum_mentions=3, limit=60)
    entry = {
        "date": context.end.isoformat(),
        "start": context.start.isoformat(),
        "stats": {**context.stats, "entities": len(entities)},
    }
    for language, digest in digests.items():
        normalized = "en" if language == "en" else "zh"
        entry[normalized] = _digest_language_payload(digest, context, normalized)
    return entry


def render_weekly_page(
    digest: WeeklyDigest,
    context: WeeklyContext,
    *,
    language: str,
) -> str:
    """Write a stable permalink that renders from the weekly data contract."""
    labels = _LABELS[language]
    prefix = "" if language == "zh" else "/en"
    start = _display_date(context.start, language)
    end = _display_date(context.end, language)
    title = f"{labels['title']} · {start}—{end}"
    description = digest.throughline.summary.replace('"', "'")[:180]
    alternate = (
        f"/en/weekly/{context.end.isoformat()}/"
        if language == "zh"
        else f"/weekly/{context.end.isoformat()}/"
    )
    header = (
        "---\n"
        "layout: default\n"
        f'title: "{title}"\n'
        f"permalink: {prefix}/weekly/{context.end.isoformat()}/\n"
        f"interface_language: {language}\n"
        f'description: "{description}"\n'
        "page_type: weekly\n"
        "page_class: weekly-detail-page\n"
        f'weekly_key: "{context.end.isoformat()}"\n'
        f"alternate_url: {alternate}\n"
        "---\n\n"
    )
    return (
        header
        + f'{{% include weekly-detail.html language="{language}" '
        "week=page.weekly_key %}\n"
    )


def build_weeks_index_data(
    weeks: Sequence[str],
    entries: Sequence[Mapping[str, object]] = (),
) -> dict:
    """Data consumed by the always-present /weekly/ index page."""
    by_date = {
        str(entry.get("date")): dict(entry)
        for entry in entries
        if isinstance(entry, Mapping) and entry.get("date")
    }
    ordered = []
    for week in sorted({*weeks, *by_date.keys()}, reverse=True):
        ordered.append(by_date.get(week, {"date": week}))
    return {"version": 2, "weeks": ordered}


def save_weekly_page(
    content: str,
    *,
    end: date_type,
    language: str,
    root: Path = WEEKLY_ROOT,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    suffix = "" if language == "zh" else "en-"
    path = root / f"{suffix}{end.isoformat()}.md"
    _atomic_write_text(path, content)
    return path


def save_weeks_index_data(
    weeks: Sequence[str],
    *,
    entry: Mapping[str, object] | None = None,
    data_root: Path = DATA_ROOT,
) -> Path:
    """Write the data file backing the committed /weekly/ index page."""
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / "weeks.json"
    entries: list[Mapping[str, object]] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = {}
        for value in payload.get("weeks", []) if isinstance(payload, dict) else []:
            if isinstance(value, str):
                entries.append({"date": value})
            elif isinstance(value, dict) and value.get("date"):
                entries.append(value)
    if entry and entry.get("date"):
        previous = next(
            (value for value in entries if value.get("date") == entry.get("date")),
            {},
        )
        merged_entry = {**previous, **entry}
        entries = [value for value in entries if value.get("date") != entry.get("date")]
        entries.append(merged_entry)
    _atomic_write_text(
        path,
        json.dumps(
            build_weeks_index_data(weeks, entries), ensure_ascii=False, indent=2
        )
        + "\n",
    )
    return path


def save_calibration_review(
    body: str,
    *,
    end: date_type,
    root: Path = CALIBRATION_ROOT,
) -> Path:
    """Store the audit next to the site data (not linked from any page)."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{end.isoformat()}.md"
    _atomic_write_text(path, body.strip() + "\n")
    return path


def known_weeks(root: Path = WEEKLY_ROOT) -> List[str]:
    """List the weekly pages already published (zh filenames are canonical)."""
    if not root.exists():
        return []
    weeks = []
    for path in root.glob("*.md"):
        stem = path.stem
        if stem.startswith("en-") or stem.endswith("index"):
            continue
        weeks.append(stem)
    return sorted(set(weeks), reverse=True)
