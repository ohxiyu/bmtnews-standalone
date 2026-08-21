"""Cross-run staging and fixed daily-edition window helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as date_type, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError

from ._file_utils import _atomic_write_text
from .daily_feed import item_identity
from .models import ContentItem


DEFAULT_STAGING_PATH = Path("data/staging-items.json")
DEFAULT_STAGING_RETENTION_HOURS = 72


class StagingStateError(ValueError):
    """Raised when staged source items cannot be read safely."""


class StagingState(BaseModel):
    """Raw source items retained between scheduled collection runs."""

    version: int = 1
    updated_at: datetime
    items: list[ContentItem] = Field(default_factory=list)


@dataclass(frozen=True)
class EditionWindow:
    """One fixed local-time edition window."""

    start: datetime
    end: datetime
    date: str
    timezone: str


def edition_window_for(
    moment: datetime,
    timezone_name: str,
    cutoff_hour: int = 8,
) -> EditionWindow:
    """Return the latest completed ``[previous cutoff, cutoff)`` window."""
    if not 0 <= cutoff_hour <= 23:
        raise ValueError("cutoff_hour must be between 0 and 23")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    local_now = moment.astimezone(ZoneInfo(timezone_name))
    edition_date = local_now.date()
    if local_now.hour < cutoff_hour:
        edition_date -= timedelta(days=1)
    return edition_window_for_date(
        edition_date,
        timezone_name,
        cutoff_hour,
    )


def edition_window_for_date(
    edition_date: date_type | str,
    timezone_name: str,
    cutoff_hour: int = 8,
) -> EditionWindow:
    """Return the fixed window ending on an explicit local edition date."""
    if not 0 <= cutoff_hour <= 23:
        raise ValueError("cutoff_hour must be between 0 and 23")
    if isinstance(edition_date, str):
        edition_date = date_type.fromisoformat(edition_date)

    end = datetime(
        edition_date.year,
        edition_date.month,
        edition_date.day,
        cutoff_hour,
        tzinfo=ZoneInfo(timezone_name),
    )
    start = end - timedelta(days=1)
    return EditionWindow(
        start=start,
        end=end,
        date=edition_date.isoformat(),
        timezone=timezone_name,
    )


def _aware_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def items_in_edition_window(
    items: Iterable[ContentItem],
    window: EditionWindow,
) -> list[ContentItem]:
    """Keep items whose publication time falls inside the edition window."""
    start = _aware_utc(window.start)
    end = _aware_utc(window.end)
    return [
        item
        for item in items
        if start <= _aware_utc(item.published_at) < end
    ]


def items_in_supplemental_window(
    items: Iterable[ContentItem],
    window: EditionWindow,
    lookback_hours: int,
) -> list[ContentItem]:
    """Return older items added by an extended lookback window.

    The normal edition remains a fixed 24-hour interval. This helper returns
    only the preceding supplemental segment, so callers cannot accidentally
    count the regular candidates twice.
    """
    edition_hours = (
        _aware_utc(window.end) - _aware_utc(window.start)
    ).total_seconds() / 3600
    if lookback_hours <= edition_hours:
        raise ValueError("lookback_hours must exceed the edition window")
    start = _aware_utc(window.end) - timedelta(hours=lookback_hours)
    normal_start = _aware_utc(window.start)
    return [
        item
        for item in items
        if start <= _aware_utc(item.published_at) < normal_start
    ]


def load_staging_state(
    path: Path = DEFAULT_STAGING_PATH,
) -> StagingState:
    """Load staged items, returning an empty state when no cache exists."""
    if not path.exists():
        return StagingState(updated_at=datetime.now(timezone.utc))
    try:
        return StagingState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise StagingStateError(f"Invalid staging state: {path}") from exc


def merge_staged_items(
    existing: Iterable[ContentItem],
    incoming: Iterable[ContentItem],
    *,
    now: datetime,
    retention_hours: int = DEFAULT_STAGING_RETENTION_HOURS,
) -> list[ContentItem]:
    """Merge staged items by canonical URL and bound the cache retention."""
    if retention_hours <= 0:
        raise ValueError("retention_hours must be positive")

    cutoff = _aware_utc(now) - timedelta(hours=retention_hours)
    merged: dict[str, ContentItem] = {}
    for item in [*existing, *incoming]:
        if _aware_utc(item.published_at) < cutoff:
            continue
        key = item_identity(item)
        current = merged.get(key)
        if current is None:
            merged[key] = item.model_copy(deep=True)
            continue

        richer = (
            item
            if len(item.content or "") >= len(current.content or "")
            else current
        )
        combined = richer.model_copy(deep=True)
        for metadata_key, metadata_value in {
            **current.metadata,
            **item.metadata,
        }.items():
            if metadata_value and not combined.metadata.get(metadata_key):
                combined.metadata[metadata_key] = metadata_value
        sources = []
        for source_item in (current, item):
            for source in [
                *source_item.metadata.get("merged_sources", []),
                source_item.source_type.value,
            ]:
                if source not in sources:
                    sources.append(source)
        if len(sources) > 1:
            combined.metadata["merged_sources"] = sources
        merged[key] = combined

    return sorted(
        merged.values(),
        key=lambda item: (
            -_aware_utc(item.published_at).timestamp(),
            item_identity(item),
        ),
    )


def save_staging_state(
    items: Iterable[ContentItem],
    path: Path = DEFAULT_STAGING_PATH,
    *,
    updated_at: datetime | None = None,
) -> Path:
    """Atomically persist staged raw items for the next scheduled run."""
    moment = updated_at or datetime.now(timezone.utc)
    state = StagingState(
        updated_at=_aware_utc(moment),
        items=list(items),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        state.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    _atomic_write_text(path, f"{payload}\n")
    return path
