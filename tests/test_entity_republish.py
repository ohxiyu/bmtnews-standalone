from pathlib import Path

import pytest

from src.archive import ArchiveRecord, save_edition_records
from src.entity_republish import recent_records, republish_entities


def record(date: str, rank: int = 1) -> ArchiveRecord:
    return ArchiveRecord(
        date=date,
        rank=rank,
        item_id=f"{date}-{rank}",
        url=f"https://example.com/{date}/{rank}",
        title_zh="Bybit 发布进展",
        title_en="Bybit publishes an update",
        summary_zh="最新情况。",
        summary_en="Latest context.",
        tags=["bybit"],
    )


def test_recent_records_uses_newest_archive_date_as_boundary() -> None:
    rows = [record("2026-01-01"), record("2026-05-01"), record("2026-05-03")]
    assert [row.date for row in recent_records(rows, days=3)] == [
        "2026-05-01",
        "2026-05-03",
    ]


def test_republish_entities_rebuilds_data_and_bilingual_pages(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"
    save_edition_records(
        [record("2026-05-03", rank) for rank in range(1, 4)],
        date="2026-05-03",
        root=archive_root,
    )

    entities, pages = republish_entities(
        archive_root=archive_root,
        entity_root=tmp_path / "entity",
        data_root=tmp_path / "_data",
    )

    assert entities == 1
    assert pages == 2
    assert (tmp_path / "_data" / "entities.json").exists()
    assert (tmp_path / "entity" / "bybit.html").exists()
    assert (tmp_path / "entity" / "en-bybit.html").exists()


def test_republish_entities_rejects_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="published archive is empty"):
        republish_entities(
            archive_root=tmp_path / "missing",
            entity_root=tmp_path / "entity",
            data_root=tmp_path / "_data",
        )
