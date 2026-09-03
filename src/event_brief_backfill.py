"""Backfill event brief fields from existing analyzed and archived stories."""

from __future__ import annotations

import argparse
from pathlib import Path

from .archive import ARCHIVE_ROOT, load_archive
from .daily_feed import DAILY_FEED_STATE_PATH, DailyFeedState, DailyFeedStateError
from .edition import DEFAULT_STAGING_PATH, load_staging_state
from .event_pipeline import (
    EVENT_CATALOG_PATH,
    backfill_event_briefs,
    load_event_catalog,
    save_event_catalog,
)
from .models import ContentItem


def _load_public_daily_items(path: Path) -> list[ContentItem]:
    """Read retained public items without applying current-day rollover rules."""
    if not path.exists():
        return []
    try:
        state = DailyFeedState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DailyFeedStateError(f"Invalid daily feed state: {path}") from exc
    return [*state.items, *state.dedup_history]


def backfill_catalog(
    *,
    catalog_path: Path = EVENT_CATALOG_PATH,
    staging_path: Path = DEFAULT_STAGING_PATH,
    daily_state_path: Path = DAILY_FEED_STATE_PATH,
    archive_root: Path = ARCHIVE_ROOT,
) -> int:
    """Enrich a catalog without network or model calls and return changed nodes."""
    metadata, events = load_event_catalog(catalog_path)
    staging = load_staging_state(staging_path)
    hydrated, changed = backfill_event_briefs(
        events,
        # The published daily state retains editorial enrichment that the
        # staging cache intentionally does not. Put it last so duplicate story
        # IDs prefer the richer public record.
        items=[*staging.items, *_load_public_daily_items(daily_state_path)],
        archive_records=load_archive(root=archive_root, months=24),
    )
    if changed:
        save_event_catalog(metadata, hydrated, catalog_path)
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill event briefs from local caches without AI calls."
    )
    parser.add_argument("--catalog", type=Path, default=EVENT_CATALOG_PATH)
    parser.add_argument("--staging", type=Path, default=DEFAULT_STAGING_PATH)
    parser.add_argument(
        "--daily-state", type=Path, default=DAILY_FEED_STATE_PATH
    )
    parser.add_argument("--archive-root", type=Path, default=ARCHIVE_ROOT)
    args = parser.parse_args()
    changed = backfill_catalog(
        catalog_path=args.catalog,
        staging_path=args.staging,
        daily_state_path=args.daily_state,
        archive_root=args.archive_root,
    )
    print(f"Event brief backfill: {changed} update nodes enriched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
