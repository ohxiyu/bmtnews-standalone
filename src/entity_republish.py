"""Rebuild entity pages from the immutable published archive."""

from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from typing import Sequence

from .archive import ArchiveRecord, load_archive
from .site_pages import publish_entity_pages
from .threads import collect_entities


def recent_records(records: Sequence[ArchiveRecord], *, days: int) -> list[ArchiveRecord]:
    """Return the trailing archive window relative to its newest valid date."""
    dated = [record for record in records if record.date_value is not None]
    if not dated:
        return []
    newest = max(record.date_value for record in dated)
    assert newest is not None
    cutoff = newest - timedelta(days=days - 1)
    return [record for record in dated if record.date_value >= cutoff]


def republish_entities(
    *,
    archive_root: Path,
    entity_root: Path,
    data_root: Path,
    days: int = 120,
    minimum_mentions: int = 3,
    limit: int = 40,
) -> tuple[int, int]:
    records = recent_records(load_archive(root=archive_root, months=12), days=days)
    if not records:
        raise RuntimeError(f"published archive is empty: {archive_root}")
    entities = collect_entities(
        records,
        minimum_mentions=minimum_mentions,
        limit=limit,
    )
    pages = publish_entity_pages(
        entities,
        ["zh", "en"],
        entity_root=entity_root,
        data_root=data_root,
    )
    return len(entities), pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--entity-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    entities, pages = republish_entities(
        archive_root=args.archive_root,
        entity_root=args.entity_root,
        data_root=args.data_root,
    )
    print(f"Republished {entities} entities across {pages} bilingual pages")


if __name__ == "__main__":
    main()
