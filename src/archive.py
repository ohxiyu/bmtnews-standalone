"""Cross-day archive of published editions.

Every published edition appends one record per displayed story to
``docs/_data/archive/YYYY-MM.jsonl``. The archive lives under ``docs/`` so
it deploys to ``gh-pages`` with the rest of the site and is restored at the
start of the next run — the same "git is the database" pattern the daily
feed state already uses.

The archive is the foundation for story threads, entity pages, the weekly
digest, and the MCP history tools. Every function here is fail-soft: a
missing or partly corrupt archive degrades to fewer records, never to a
failed publish.
"""

from __future__ import annotations

import json
import logging
from datetime import date as date_type, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, List, Optional

from pydantic import BaseModel, Field, ValidationError

from ._file_utils import _atomic_write_text
from .models import ContentItem

logger = logging.getLogger(__name__)

ARCHIVE_ROOT = Path("docs/_data/archive")


class ArchiveRecord(BaseModel):
    """One published story, flattened for cross-day analysis."""

    date: str
    rank: int
    item_id: str
    url: str
    title_zh: str = ""
    title_en: str = ""
    summary_zh: str = ""
    summary_en: str = ""
    score: Optional[float] = None
    category: str = ""
    top_category: str = ""
    source_type: str = ""
    source_label: str = ""
    tags: List[str] = Field(default_factory=list)
    sources_count: int = 1
    editorial: bool = False
    thread_id: Optional[str] = None
    thread_day: Optional[int] = None

    @property
    def date_value(self) -> Optional[date_type]:
        try:
            return date_type.fromisoformat(self.date)
        except ValueError:
            return None

    def title_for(self, language: str) -> str:
        preferred = self.title_zh if language == "zh" else self.title_en
        return preferred or self.title_en or self.title_zh

    def summary_for(self, language: str) -> str:
        preferred = self.summary_zh if language == "zh" else self.summary_en
        return preferred or self.summary_en or self.summary_zh


def archive_path_for(date: str, root: Path = ARCHIVE_ROOT) -> Path:
    """Return the monthly archive file that owns ``date``."""
    return root / f"{date[:7]}.jsonl"


def _read_records(path: Path) -> List[ArchiveRecord]:
    if not path.exists():
        return []
    records: List[ArchiveRecord] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Unreadable archive %s: %s", path, exc)
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            records.append(ArchiveRecord.model_validate_json(line))
        except (ValidationError, ValueError):
            logger.warning("Skipping corrupt archive line in %s", path)
    return records


def load_archive(
    *,
    root: Path = ARCHIVE_ROOT,
    since: date_type | None = None,
    months: int = 6,
) -> List[ArchiveRecord]:
    """Load records newest-file-first, optionally limited to ``since``."""
    if not root.exists():
        return []
    paths = sorted(root.glob("*.jsonl"), reverse=True)[:months]
    records: List[ArchiveRecord] = []
    for path in paths:
        records.extend(_read_records(path))
    if since is not None:
        records = [
            record
            for record in records
            if (value := record.date_value) is not None and value >= since
        ]
    records.sort(key=lambda record: (record.date, record.rank))
    return records


def load_recent_archive(
    days: int,
    *,
    today: date_type,
    root: Path = ARCHIVE_ROOT,
) -> List[ArchiveRecord]:
    """Load the records published in the last ``days`` days."""
    return load_archive(root=root, since=today - timedelta(days=days))


def iter_dates(records: Iterable[ArchiveRecord]) -> Iterator[str]:
    seen: set[str] = set()
    for record in records:
        if record.date not in seen:
            seen.add(record.date)
            yield record.date


def build_records(
    items: Iterable[ContentItem],
    *,
    date: str,
    top_category_of,
) -> List[ArchiveRecord]:
    """Flatten published items into archive records."""
    records: List[ArchiveRecord] = []
    for rank, item in enumerate(items, start=1):
        metadata = item.metadata or {}
        merged = metadata.get("merged_sources")
        sources_count = len(merged) if isinstance(merged, list) and merged else 1
        source_label = ""
        for key in ("feed_name", "channel", "subreddit", "repo", "source_name"):
            value = metadata.get(key)
            if isinstance(value, str) and value:
                source_label = value
                break
        records.append(
            ArchiveRecord(
                date=date,
                rank=rank,
                item_id=item.id,
                url=str(item.url),
                title_zh=str(metadata.get("title_zh") or item.title),
                title_en=str(metadata.get("title_en") or item.title),
                summary_zh=str(
                    metadata.get("detailed_summary_zh") or item.ai_summary or ""
                ),
                summary_en=str(
                    metadata.get("detailed_summary_en") or item.ai_summary or ""
                ),
                score=item.ai_score,
                category=str(metadata.get("category") or ""),
                top_category=top_category_of(item),
                source_type=item.source_type.value,
                source_label=source_label or (item.author or ""),
                tags=list(item.ai_tags or []),
                sources_count=sources_count,
                editorial=bool(metadata.get("editorial")),
                thread_id=metadata.get("thread_id"),
                thread_day=metadata.get("thread_day"),
            )
        )
    return records


def save_edition_records(
    records: List[ArchiveRecord],
    *,
    date: str,
    root: Path = ARCHIVE_ROOT,
) -> Path:
    """Write ``records`` for ``date``, replacing any previous run's rows.

    Re-publishing the same edition (``--force-publish``) overwrites that
    date's rows instead of duplicating them.
    """
    path = archive_path_for(date, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = [record for record in _read_records(path) if record.date != date]
    combined = [*kept, *records]
    combined.sort(key=lambda record: (record.date, record.rank))
    payload = "\n".join(
        record.model_dump_json(exclude_none=False) for record in combined
    )
    _atomic_write_text(path, payload + "\n" if payload else "")
    return path


def archive_stats(records: List[ArchiveRecord]) -> dict[str, int]:
    """Small summary used by run reports and the weekly digest."""
    return {
        "records": len(records),
        "days": len(set(record.date for record in records)),
        "threads": len(
            {record.thread_id for record in records if record.thread_id}
        ),
    }


def parse_date(value: str) -> Optional[date_type]:
    try:
        return date_type.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def utc_today() -> date_type:
    return datetime.utcnow().date()
