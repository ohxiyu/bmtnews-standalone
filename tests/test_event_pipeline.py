"""Incremental event publishing contract tests."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.archive import ArchiveRecord
from src.daily_feed import DailyFeedState, save_daily_feed_state
from src.event_brief_backfill import backfill_catalog
from src.event_pipeline import (
    backfill_event_briefs,
    load_event_catalog,
    save_event_catalog,
    update_events,
)
from src.events import (
    EventRelation,
    EventRelationDecision,
    EventSource,
    EventStatus,
    EventType,
    EventUpdate,
    EventUpdateType,
    TrackedEvent,
)
from src.edition import load_staging_state, save_staging_state
from src.models import (
    AIConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
)
from src.orchestrator import BMTNewsOrchestrator
from src.storage.manager import StorageManager


NOW = datetime(2026, 9, 3, 4, 0, tzinfo=timezone.utc)


def item(
    name: str,
    *,
    title: str,
    url: str | None = None,
) -> ContentItem:
    return ContentItem(
        id=f"rss:{name}",
        source_type=SourceType.RSS,
        title=title,
        url=url or f"https://example.com/{name}",
        published_at=NOW,
        fetched_at=NOW + timedelta(minutes=5),
        metadata={
            "feed_name": f"Source {name}",
            "category": "crypto-security",
            "detailed_summary_zh": f"{title} 的详细中文摘要。",
            "detailed_summary_en": f"Detailed summary for {title}.",
            "background_zh": f"{title} 的背景。",
            "background_en": f"Background for {title}.",
            "community_discussion_zh": f"{title} 的讨论。",
            "community_discussion_en": f"Discussion of {title}.",
            "market_impact_zh": f"{title} 的市场影响。",
            "market_impact_en": f"Market impact of {title}.",
            "sources": [
                {
                    "url": f"https://reference.example.com/{name}",
                    "title": f"Reference {name}",
                }
            ],
        },
        ai_score=8.5,
        ai_summary=f"{title} changed materially.",
        ai_tags=["Tectonic", "security", "exploit"],
    )


def existing_event() -> TrackedEvent:
    event_id = "evt_tectonic1"
    update = EventUpdate(
        update_id="upd_initial01",
        event_id=event_id,
        occurred_at=NOW - timedelta(days=1),
        published_at=NOW - timedelta(days=1),
        first_seen_at=NOW - timedelta(days=1) + timedelta(minutes=5),
        update_type=EventUpdateType.INITIAL,
        what_changed_zh="Tectonic 首次报告安全事件。",
        what_changed_en="Tectonic first reported a security incident.",
        current_state_zh="事件调查中。",
        current_state_en="The incident is under investigation.",
        confidence=0.97,
        story_ids=["rss:initial"],
        sources=[
            EventSource(
                url="https://example.com/initial",
                label="Initial source",
                source_type="rss",
            )
        ],
    )
    return TrackedEvent(
        event_id=event_id,
        event_type=EventType.SECURITY_INCIDENT,
        status=EventStatus.DEVELOPING,
        category="crypto",
        title_zh="Tectonic 安全事件",
        title_en="Tectonic security incident",
        current_state_zh=update.current_state_zh,
        current_state_en=update.current_state_en,
        entities=["tectonic"],
        topics=["security", "exploit"],
        first_seen_at=update.first_seen_at,
        last_updated_at=update.first_seen_at,
        last_material_change_at=update.first_seen_at,
        confidence=0.97,
        updates=[update],
    )


def decision(
    relation: EventRelation,
    *,
    confidence: float = 0.96,
    update_type: EventUpdateType | None = None,
) -> EventRelationDecision:
    material = relation is EventRelation.SAME_EVENT_UPDATE
    return EventRelationDecision(
        candidate_event_id="evt_tectonic1",
        target_update_id=(
            "upd_initial01"
            if relation is EventRelation.DUPLICATE_COVERAGE
            else None
        ),
        relation=relation,
        confidence=confidence,
        update_type=update_type if material else None,
        material_change=material,
        what_changed_zh="损失规模得到确认。" if material else "",
        what_changed_en="The loss estimate was confirmed." if material else "",
        current_state_zh="事件损失已确认。" if material else "",
        current_state_en="The incident loss is now confirmed." if material else "",
        rationale="The protocol and root incident match.",
    )


def test_no_candidate_creates_event_without_relation_call() -> None:
    story = item("new", title="Unrelated protocol launches a new product")
    calls = 0

    async def classify(client, event, evidence):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        raise AssertionError("hard gate should prevent this call")

    events, result = asyncio.run(
        update_events([story], [], client=object(), classifier=classify)  # type: ignore[arg-type]
    )

    assert calls == 0
    assert result.new_events == 1
    assert result.candidates_classified == 0
    assert story.metadata["event_id"] == events[0].event_id
    assert story.metadata["event_update_id"] == events[0].updates[0].update_id
    update = events[0].updates[0]
    assert update.background_zh == f"{story.title} 的背景。"
    assert update.importance_score == 8.5
    assert update.references[0].url == "https://reference.example.com/new"


def test_material_update_is_added_once_and_reused_on_retry() -> None:
    story = item("recovery", title="Tectonic confirms recovery after exploit")

    async def classify(client, event, evidence):  # type: ignore[no-untyped-def]
        return decision(
            EventRelation.SAME_EVENT_UPDATE,
            update_type=EventUpdateType.RESOLUTION,
        )

    events, result = asyncio.run(
        update_events(
            [story], [existing_event()], client=object(), classifier=classify  # type: ignore[arg-type]
        )
    )
    assert result.material_updates == 1
    assert result.candidates_classified == 1
    assert len(events[0].updates) == 2
    assert events[0].status is EventStatus.RESOLVED

    async def never_again(client, event, evidence):  # type: ignore[no-untyped-def]
        raise AssertionError("a catalogued story must never be reclassified")

    retried, retry_result = asyncio.run(
        update_events([story], events, client=object(), classifier=never_again)  # type: ignore[arg-type]
    )
    assert retry_result.already_known == 1
    assert retry_result.candidates_classified == 0
    assert len(retried[0].updates) == 2


def test_known_story_is_enriched_without_relation_call() -> None:
    story = item("initial", title="Tectonic first reported a security incident")

    async def never_again(client, event, evidence):  # type: ignore[no-untyped-def]
        raise AssertionError("a catalogued story must never be reclassified")

    events, result = asyncio.run(
        update_events(
            [story], [existing_event()], client=None, classifier=never_again
        )
    )

    assert result.already_known == 1
    assert result.briefs_enriched == 1
    assert events[0].updates[0].background_zh.endswith("的背景。")
    assert events[0].updates[0].importance_score == 8.5


def test_brief_backfill_is_idempotent_and_uses_archive_fallback() -> None:
    event = existing_event()
    archived = ArchiveRecord(
        date="2026-09-02",
        rank=1,
        item_id="rss:initial",
        url="https://example.com/initial",
        summary_zh="历史归档中的详细事件摘要。",
        summary_en="Detailed event summary from the public archive.",
        score=9.0,
    )
    hydrated, changed = backfill_event_briefs(
        [event], archive_records=[archived]
    )
    repeated, repeated_changed = backfill_event_briefs(
        hydrated, archive_records=[archived]
    )

    assert changed == 1
    assert repeated_changed == 0
    assert repeated == hydrated
    assert hydrated[0].updates[0].detailed_summary_zh.startswith("历史归档")
    assert hydrated[0].updates[0].importance_score == 9.0


def test_catalog_backfill_prefers_enriched_public_daily_state(
    tmp_path: Path,
) -> None:
    catalog_path = tmp_path / "events.json"
    staging_path = tmp_path / "staging.json"
    daily_state_path = tmp_path / "daily.json"
    archive_root = tmp_path / "archive"
    save_event_catalog({"schema_version": 1}, [existing_event()], catalog_path)
    staging_story = item(
        "initial", title="Tectonic first reported a security incident"
    ).model_copy(update={"metadata": {"category": "crypto-security"}})
    save_staging_state([staging_story], staging_path, updated_at=NOW)
    enriched_story = item(
        "initial", title="Tectonic first reported a security incident"
    )
    save_daily_feed_state(
        DailyFeedState(
            date="2026-09-03",
            timezone="Asia/Shanghai",
            updated_at=NOW,
            items=[enriched_story],
        ),
        daily_state_path,
    )

    changed = backfill_catalog(
        catalog_path=catalog_path,
        staging_path=staging_path,
        daily_state_path=daily_state_path,
        archive_root=archive_root,
    )
    repeated = backfill_catalog(
        catalog_path=catalog_path,
        staging_path=staging_path,
        daily_state_path=daily_state_path,
        archive_root=archive_root,
    )
    _, events = load_event_catalog(catalog_path)

    assert changed == 1
    assert repeated == 0
    assert events[0].updates[0].background_zh.endswith("的背景。")
    assert events[0].updates[0].community_discussion_zh.endswith("的讨论。")
    assert events[0].updates[0].references[0].title == "Reference initial"


def test_duplicate_coverage_adds_source_but_not_timeline_node() -> None:
    story = item("repeat", title="Tectonic exploit report repeats known facts")

    async def classify(client, event, evidence):  # type: ignore[no-untyped-def]
        return decision(EventRelation.DUPLICATE_COVERAGE)

    events, result = asyncio.run(
        update_events(
            [story], [existing_event()], client=object(), classifier=classify  # type: ignore[arg-type]
        )
    )
    assert result.duplicate_sources == 1
    assert result.material_updates == 0
    assert len(events[0].updates) == 1
    assert events[0].updates[0].story_ids == ["rss:initial", "rss:repeat"]
    assert len(events[0].updates[0].sources) == 2


def test_duplicate_with_unknown_update_target_fails_safe() -> None:
    story = item("bad-target", title="Tectonic report repeats known facts")

    async def classify(client, event, evidence):  # type: ignore[no-untyped-def]
        return EventRelationDecision(
            candidate_event_id=event.event_id,
            target_update_id="upd_missing01",
            relation=EventRelation.DUPLICATE_COVERAGE,
            confidence=0.98,
            rationale="The model selected an update that is not in the event.",
        )

    events, result = asyncio.run(
        update_events(
            [story], [existing_event()], client=object(), classifier=classify  # type: ignore[arg-type]
        )
    )

    assert result.classifier_errors == 1
    assert result.new_events == 1
    assert result.duplicate_sources == 0
    assert len(events) == 2
    assert story.metadata["event_id"] != "evt_tectonic1"


def test_low_confidence_relation_remains_a_separate_event() -> None:
    story = item("uncertain", title="Tectonic discusses a different security tool")

    async def classify(client, event, evidence):  # type: ignore[no-untyped-def]
        return decision(
            EventRelation.SAME_EVENT_UPDATE,
            confidence=0.89,
            update_type=EventUpdateType.CONFIRMATION,
        )

    events, result = asyncio.run(
        update_events(
            [story], [existing_event()], client=object(), classifier=classify  # type: ignore[arg-type]
        )
    )
    assert result.candidates_classified == 1
    assert result.new_events == 1
    assert len(events) == 2
    assert story.metadata["event_id"] != "evt_tectonic1"


def test_catalog_round_trip_preserves_review_audit_fields(tmp_path: Path) -> None:
    path = tmp_path / "events.json"
    metadata = {
        "schema_version": 1,
        "reviewed_through_date": "2026-09-02",
        "source_archive_digest": "a" * 64,
    }
    save_event_catalog(metadata, [existing_event()], path)
    loaded_metadata, loaded_events = load_event_catalog(path)

    assert loaded_metadata == metadata
    assert loaded_events == [existing_event()]


def test_catalog_rejects_cross_event_story_membership(tmp_path: Path) -> None:
    first = existing_event()
    second = existing_event().model_copy(deep=True)
    second.event_id = "evt_tectonic2"
    second.updates[0].event_id = second.event_id

    with pytest.raises(ValueError, match="multiple event updates"):
        save_event_catalog({}, [first, second], tmp_path / "events.json")


def test_four_hour_collection_analyzes_only_new_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    catalog_path = tmp_path / "docs" / "_data" / "events.json"
    save_event_catalog({"schema_version": 1}, [], catalog_path)
    staging_path = tmp_path / "data" / "staging-items.json"
    old = item("old", title="Previously staged story")
    new = item("new", title="Newly collected protocol release")
    save_staging_state([old], staging_path, updated_at=NOW)
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=["zh", "en"],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            daily_timezone="Asia/Shanghai",
        ),
    )
    orchestrator = BMTNewsOrchestrator(
        config,
        StorageManager(data_dir=str(tmp_path / "data")),
    )
    analyzed: list[str] = []

    async def fetch(since):  # type: ignore[no-untyped-def]
        return [old.model_copy(deep=True), new]

    async def analyze(items):  # type: ignore[no-untyped-def]
        analyzed.extend(row.id for row in items)
        return items

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze)
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda config: object())

    asyncio.run(
        orchestrator.fetch_to_staging(
            force_hours=12,
            staging_path=staging_path,
            now=NOW + timedelta(hours=1),
        )
    )

    assert analyzed == ["rss:new"]
    assert {row.id for row in load_staging_state(staging_path).items} == {
        "rss:old",
        "rss:new",
    }
    _, events = load_event_catalog(catalog_path)
    assert len(events) == 1
    assert events[0].updates[0].story_ids == ["rss:new"]
    assert (tmp_path / "docs" / "api" / "events.json").exists()
