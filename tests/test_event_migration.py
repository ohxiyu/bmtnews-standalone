"""Safety and determinism checks for the reviewed event archive migration."""

from __future__ import annotations

from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from src.archive import ArchiveRecord, load_archive
from src.event_migration import (
    EventMigrationPlan,
    LegacyThreadReview,
    LegacyUrlAction,
    MigrationError,
    PlannedEvent,
    PlannedUpdate,
    ReviewDisposition,
    apply_migration,
    archive_digest,
    build_migration,
    load_migration_plan,
    render_audit_report,
)
from src.events import EventStatus, EventTimePrecision, EventType, EventUpdateType


REVIEW_DATE = date(2026, 9, 2)


def make_record(
    item_id: str,
    date_str: str,
    thread_id: str,
    *,
    rank: int = 1,
    title: str | None = None,
) -> ArchiveRecord:
    headline = title or f"Headline {item_id}"
    return ArchiveRecord(
        date=date_str,
        rank=rank,
        item_id=item_id,
        url=f"https://example.com/{item_id}",
        title_zh=headline,
        title_en=headline,
        summary_zh=f"Summary {item_id}",
        summary_en=f"Summary {item_id}",
        top_category="crypto",
        source_type="rss",
        source_label="Example",
        tags=["ExampleProtocol", "governance"],
        thread_id=thread_id,
    )


def sample_records() -> list[ArchiveRecord]:
    return [
        make_record("progress-1", "2026-08-28", "taaaaaaaaaa"),
        make_record("progress-2", "2026-08-29", "taaaaaaaaaa"),
        make_record("false-1", "2026-08-28", "tbbbbbbbbbb", rank=2),
        make_record("false-2", "2026-08-30", "tbbbbbbbbbb"),
        make_record("singleton", "2026-08-31", "tcccccccccc"),
    ]


def sample_plan(records: list[ArchiveRecord], *, approved: bool = False):
    digest, count = archive_digest(records, through_date=REVIEW_DATE)
    return EventMigrationPlan(
        reviewed_through_date=REVIEW_DATE,
        source_archive_digest=digest,
        source_record_count=count,
        approved=approved,
        reviews=[
            LegacyThreadReview(
                legacy_thread_id="taaaaaaaaaa",
                disposition=ReviewDisposition.PROGRESSION,
                legacy_url_action=LegacyUrlAction.REDIRECT,
                rationale_zh="同一治理投票的前后进展。",
                rationale_en="Two stages of the same governance vote.",
                events=[
                    PlannedEvent(
                        key="example-governance-vote",
                        title_zh="示例治理投票",
                        title_en="Example governance vote",
                        event_type=EventType.GOVERNANCE,
                        status=EventStatus.RESOLVED,
                        updates=[
                            PlannedUpdate(
                                story_ids=["progress-1"],
                                update_type=EventUpdateType.INITIAL,
                                what_changed_zh="投票开始。",
                                what_changed_en="Voting opened.",
                            ),
                            PlannedUpdate(
                                story_ids=["progress-2"],
                                update_type=EventUpdateType.RESOLUTION,
                                what_changed_zh="提案通过。",
                                what_changed_en="The proposal passed.",
                            ),
                        ],
                    )
                ],
            ),
            LegacyThreadReview(
                legacy_thread_id="tbbbbbbbbbb",
                disposition=ReviewDisposition.SPLIT_ALL,
                legacy_url_action=LegacyUrlAction.RETIRED_INDEX,
                rationale_zh="两条记录只是共享宽泛主题。",
                rationale_en="The records share only a broad topic.",
                events=[],
            ),
        ],
    )


def test_build_migration_splits_duplicates_and_uses_edition_precision() -> None:
    records = sample_records()
    result = build_migration(records, sample_plan(records))

    assert len(result.events) == 4
    assert len({record.event_id for record in result.records}) == 4
    progression = next(event for event in result.events if len(event.updates) == 2)
    assert [update.update_type for update in progression.updates] == [
        EventUpdateType.INITIAL,
        EventUpdateType.RESOLUTION,
    ]
    assert all(
        update.time_precision is EventTimePrecision.EDITION
        for update in progression.updates
    )
    assert progression.first_seen_at.utcoffset().total_seconds() == 8 * 3600
    assert result.legacy_urls.redirects == {
        "taaaaaaaaaa": progression.event_id
    }
    assert len(result.legacy_urls.retired["tbbbbbbbbbb"]) == 2
    split_targets = set(result.legacy_urls.retired["tbbbbbbbbbb"])
    split_events = [event for event in result.events if event.event_id in split_targets]
    assert all(
        event.legacy_thread_ids == ["tbbbbbbbbbb"] for event in split_events
    )


def test_audit_report_is_review_only_and_covers_every_public_thread() -> None:
    records = sample_records()
    plan = sample_plan(records)
    result = build_migration(records, plan)
    report = render_audit_report(
        records, plan, result, source_revision="deadbeef"
    )

    assert "does not modify `gh-pages`" in report
    assert "Plan approval: `pending`" in report
    assert "`taaaaaaaaaa`" in report
    assert "`tbbbbbbbbbb`" in report
    assert "Conservative singleton defaults: 1" in report


def test_unreviewed_public_thread_is_a_hard_error() -> None:
    records = sample_records()
    plan = sample_plan(records)
    plan.reviews.pop()
    with pytest.raises(MigrationError, match="review coverage mismatch"):
        build_migration(records, plan)


def test_archive_drift_is_a_hard_error() -> None:
    records = sample_records()
    plan = sample_plan(records)
    changed = [*records]
    changed[0] = changed[0].model_copy(update={"title_en": "Changed after review"})
    with pytest.raises(MigrationError, match="fingerprint changed"):
        build_migration(changed, plan)


def test_fingerprint_covers_metadata_but_ignores_migration_annotations() -> None:
    records = sample_records()
    original = archive_digest(records, through_date=REVIEW_DATE)
    annotated = [
        record.model_copy(
            update={
                "event_id": "evt_annotation1",
                "event_update_id": "upd_annotation1",
            }
        )
        for record in records
    ]
    changed_tags = [*records]
    changed_tags[0] = changed_tags[0].model_copy(update={"tags": ["changed"]})

    assert archive_digest(annotated, through_date=REVIEW_DATE) == original
    assert archive_digest(changed_tags, through_date=REVIEW_DATE) != original


def test_records_after_review_cutoff_default_to_separate_events() -> None:
    records = sample_records()
    plan = sample_plan(records)
    records.append(
        make_record("future-story", "2026-09-03", "taaaaaaaaaa")
    )

    result = build_migration(records, plan)

    future = next(
        record for record in result.records if record.item_id == "future-story"
    )
    progression_ids = {
        record.event_id
        for record in result.records
        if record.item_id.startswith("progress-")
    }
    assert future.event_id not in progression_ids
    assert result.default_singleton_count == 2


def test_apply_refuses_unapproved_plan_without_writing(tmp_path: Path) -> None:
    records = sample_records()
    with pytest.raises(MigrationError, match="not approved"):
        apply_migration(
            records,
            sample_plan(records),
            archive_root=tmp_path / "archive",
            catalog_path=tmp_path / "events.json",
            legacy_map_path=tmp_path / "legacy.json",
        )
    assert not list(tmp_path.rglob("*"))


def test_approved_apply_is_byte_idempotent(tmp_path: Path) -> None:
    records = sample_records()
    plan = sample_plan(records, approved=True)
    archive_root = tmp_path / "archive"
    catalog = tmp_path / "events.json"
    legacy = tmp_path / "legacy.json"

    apply_migration(
        records,
        plan,
        archive_root=archive_root,
        catalog_path=catalog,
        legacy_map_path=legacy,
        events_root=tmp_path / "events",
        legacy_pages_root=tmp_path / "threads",
        thread_index_path=tmp_path / "threads.json",
    )
    first = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    migrated = load_archive(root=archive_root, months=120)
    apply_migration(
        migrated,
        plan,
        archive_root=archive_root,
        catalog_path=catalog,
        legacy_map_path=legacy,
        events_root=tmp_path / "events",
        legacy_pages_root=tmp_path / "threads",
        thread_index_path=tmp_path / "threads.json",
    )
    second = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    assert first == second
    assert all(record.event_id and record.event_update_id for record in migrated)


def test_checked_in_production_plan_is_approved_and_complete() -> None:
    plan = load_migration_plan(Path("data/event-migration-v1.json"))
    dispositions = Counter(review.disposition for review in plan.reviews)

    assert plan.approved is True
    assert len(plan.reviews) == 22
    assert dispositions == {
        ReviewDisposition.PROGRESSION: 5,
        ReviewDisposition.COLLAPSE_DUPLICATES: 3,
        ReviewDisposition.SPLIT_ALL: 10,
        ReviewDisposition.SPLIT_GROUPS: 4,
    }
    bitmart = next(
        review for review in plan.reviews if review.legacy_thread_id == "tbdf211e6dd"
    )
    bitmart_ids = {
        story
        for event in bitmart.events
        for update in event.updates
        for story in update.story_ids
    }
    assert "google_news:article:468ab309354b77ad" in bitmart_ids
    assert "rss:cryptoslate.com_feed_:c1f6d470fda7bdc5" in bitmart_ids
