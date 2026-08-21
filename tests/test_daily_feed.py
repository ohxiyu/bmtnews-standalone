"""Tests for incremental daily-feed persistence and ordering."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from src.daily_feed import (
    DailyFeedState,
    DailyFeedStateError,
    analyzed_item_key,
    item_identity,
    items_for_local_date,
    load_daily_feed_state,
    local_date_for,
    merge_daily_items,
    save_daily_feed_state,
)
from src.models import (
    AIConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
)
from src.orchestrator import BMTNewsOrchestrator


def make_item(
    item_id: str,
    url: str,
    published_at: datetime,
    score: float,
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Title {item_id}",
        url=url,
        content=f"Fetched body {item_id}",
        author="publisher",
        published_at=published_at,
        metadata={
            "category": "crypto-markets",
            "detailed_summary_zh": f"Summary {item_id}",
            "raw_comments": ["must not be persisted"],
        },
        ai_score=score,
        ai_reason="internal rationale",
        ai_summary=f"AI summary {item_id}",
        ai_tags=["internal"],
    )


def test_local_date_uses_configured_timezone_across_utc_midnight() -> None:
    before_midnight = datetime(2026, 7, 26, 15, 59, tzinfo=timezone.utc)
    after_midnight = datetime(2026, 7, 26, 16, 1, tzinfo=timezone.utc)

    assert local_date_for(before_midnight, "Asia/Shanghai") == "2026-07-26"
    assert local_date_for(after_midnight, "Asia/Shanghai") == "2026-07-27"


def test_items_for_local_date_excludes_previous_shanghai_day() -> None:
    previous = make_item(
        "previous",
        "https://example.com/previous",
        datetime(2026, 7, 26, 15, 59, tzinfo=timezone.utc),
        9.0,
    )
    today = make_item(
        "today",
        "https://example.com/today",
        datetime(2026, 7, 26, 16, 1, tzinfo=timezone.utc),
        8.0,
    )

    assert items_for_local_date(
        [previous, today],
        "2026-07-27",
        "Asia/Shanghai",
    ) == [today]


def test_merge_retains_earlier_items_deduplicates_and_sorts() -> None:
    earlier = make_item(
        "earlier",
        "https://example.com/earlier?utm_source=feed",
        datetime(2026, 7, 27, 1, 0, tzinfo=timezone.utc),
        8.0,
    )
    replaced = make_item(
        "replaced",
        "https://example.com/story?utm_source=old",
        datetime(2026, 7, 27, 2, 0, tzinfo=timezone.utc),
        7.5,
    )
    replacement = make_item(
        "replacement",
        "https://example.com/story",
        datetime(2026, 7, 27, 3, 0, tzinfo=timezone.utc),
        9.0,
    )
    newest_tie = make_item(
        "newest-tie",
        "https://example.com/newest",
        datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        8.0,
    )

    merged = merge_daily_items(
        [earlier, replaced],
        [replacement, newest_tie],
        "2026-07-27",
        "Asia/Shanghai",
    )

    assert [item.id for item in merged] == [
        "replacement",
        "newest-tie",
        "earlier",
    ]


def test_state_round_trip_keeps_public_fields_only(tmp_path: Path) -> None:
    path = tmp_path / "docs" / "_data" / "bmtnews_state.json"
    item = make_item(
        "item",
        "https://example.com/item",
        datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        8.5,
    )
    historical_item = make_item(
        "historical",
        "https://example.com/historical",
        datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        8.0,
    )
    state = DailyFeedState(
        date="2026-07-27",
        timezone="Asia/Shanghai",
        updated_at=datetime(2026, 7, 27, 4, 5, tzinfo=timezone.utc),
        analyzed_keys=["key-one", "key-two"],
        items=[item],
        dedup_history=[historical_item],
    )

    save_daily_feed_state(state, path)
    loaded = load_daily_feed_state("2026-07-27", "Asia/Shanghai", path)

    assert loaded.analyzed_keys == ["key-one", "key-two"]
    assert loaded.items[0].content is None
    assert loaded.items[0].ai_reason is None
    assert loaded.items[0].ai_tags == []
    assert loaded.items[0].metadata == {
        "category": "crypto-markets",
        "detailed_summary_zh": "Summary item",
    }
    assert loaded.dedup_history[0].content is None
    assert loaded.dedup_history[0].ai_reason is None


def test_previous_day_items_roll_into_dedup_history(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    previous = make_item(
        "previous",
        "https://example.com/story?utm_source=first",
        datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        8.5,
    )
    state = DailyFeedState(
        date="2026-07-27",
        timezone="Asia/Shanghai",
        updated_at=datetime(2026, 7, 27, 4, 5, tzinfo=timezone.utc),
        analyzed_keys=["old"],
        items=[previous],
    )
    save_daily_feed_state(state, path)

    loaded = load_daily_feed_state("2026-07-28", "Asia/Shanghai", path)

    assert loaded.date == "2026-07-28"
    assert loaded.items == []
    assert loaded.analyzed_keys == []
    assert [item.id for item in loaded.dedup_history] == ["previous"]


def test_dedup_history_drops_items_older_than_two_days(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    old = make_item(
        "old",
        "https://example.com/old",
        datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        8.0,
    )
    state = DailyFeedState(
        date="2026-07-28",
        timezone="Asia/Shanghai",
        updated_at=datetime(2026, 7, 28, 4, 5, tzinfo=timezone.utc),
        dedup_history=[old],
    )
    save_daily_feed_state(state, path)

    loaded = load_daily_feed_state("2026-07-29", "Asia/Shanghai", path)

    assert loaded.dedup_history == []


def test_state_from_previous_day_starts_empty(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    state = DailyFeedState(
        date="2026-07-26",
        timezone="Asia/Shanghai",
        updated_at=datetime(2026, 7, 26, tzinfo=timezone.utc),
        analyzed_keys=["old"],
        items=[],
    )
    save_daily_feed_state(state, path)

    loaded = load_daily_feed_state("2026-07-27", "Asia/Shanghai", path)

    assert loaded.date == "2026-07-27"
    assert loaded.analyzed_keys == []
    assert loaded.items == []


def test_invalid_state_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(DailyFeedStateError):
        load_daily_feed_state("2026-07-27", "Asia/Shanghai", path)


def test_filtering_config_validates_iana_timezone() -> None:
    assert FilteringConfig(daily_timezone="Asia/Shanghai").daily_timezone == "Asia/Shanghai"
    with pytest.raises(ValidationError, match="Unknown IANA timezone"):
        FilteringConfig(daily_timezone="Mars/Olympus")


def test_orchestrator_retains_selected_items_across_same_day_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    earlier = make_item(
        "earlier",
        "https://example.com/earlier",
        datetime.combine(
            local_today,
            datetime.min.time().replace(hour=1),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).astimezone(timezone.utc),
        8.0,
    )
    later = make_item(
        "later",
        "https://example.com/later",
        datetime.combine(
            local_today,
            datetime.min.time().replace(hour=2),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).astimezone(timezone.utc),
        9.0,
    )
    batches = [[earlier], [earlier, later], [earlier, later]]
    analyzed_batches: list[list[str]] = []
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            daily_timezone="Asia/Shanghai",
            preserve_daily_items=True,
        ),
    )
    orchestrator = BMTNewsOrchestrator(config, storage=object())

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return batches.pop(0)

    async def analyze_content(items):  # type: ignore[no-untyped-def]
        analyzed_batches.append([item.id for item in items])
        return items

    async def merge_topic_duplicates(items, *, log=True):  # type: ignore[no-untyped-def]
        return items

    async def no_op(items):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", merge_topic_duplicates)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", no_op)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", no_op)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run(force_hours=24))
    asyncio.run(orchestrator.run(force_hours=24))
    asyncio.run(orchestrator.run(force_hours=24))

    date = local_today.isoformat()
    state = load_daily_feed_state(
        date,
        "Asia/Shanghai",
        tmp_path / "docs" / "_data" / "bmtnews_state.json",
    )
    assert [item.id for item in state.items] == ["later", "earlier"]
    assert state.analyzed_keys == sorted(
        [analyzed_item_key(earlier), analyzed_item_key(later)]
    )
    assert analyzed_batches == [["earlier"], ["later"]]


def test_orchestrator_reapplies_limits_after_merging_daily_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_today = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    earlier = make_item(
        "earlier",
        "https://example.com/earlier",
        datetime.combine(
            local_today,
            datetime.min.time().replace(hour=1),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).astimezone(timezone.utc),
        8.0,
    )
    later = make_item(
        "later",
        "https://example.com/later",
        datetime.combine(
            local_today,
            datetime.min.time().replace(hour=2),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        ).astimezone(timezone.utc),
        9.0,
    )
    batches = [[earlier], [later]]
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            max_items=1,
            daily_timezone="Asia/Shanghai",
            preserve_daily_items=True,
        ),
    )
    orchestrator = BMTNewsOrchestrator(config, storage=object())

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return batches.pop(0)

    async def analyze_content(items):  # type: ignore[no-untyped-def]
        return items

    async def merge_topic_duplicates(items, *, log=True):  # type: ignore[no-untyped-def]
        return items

    async def no_op(items):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", merge_topic_duplicates)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", no_op)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", no_op)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run(force_hours=24))
    asyncio.run(orchestrator.run(force_hours=24))

    state = load_daily_feed_state(
        local_today.isoformat(),
        "Asia/Shanghai",
        tmp_path / "docs" / "_data" / "bmtnews_state.json",
    )
    assert [item.id for item in state.items] == ["later"]


def test_filter_items_drops_published_url_before_semantic_dedup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = make_item(
        "published",
        "https://example.com/story?utm_source=first",
        datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        8.0,
    )
    incoming = make_item(
        "incoming",
        "https://example.com/story",
        datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        9.0,
    )
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(ai_score_threshold=7.0),
    )
    orchestrator = BMTNewsOrchestrator(config, storage=object())

    async def unexpected_topic_dedup(items, *, log=True):  # type: ignore[no-untyped-def]
        raise AssertionError("exact published URL should not reach semantic dedup")

    monkeypatch.setattr(
        orchestrator,
        "merge_topic_duplicates",
        unexpected_topic_dedup,
    )

    result = asyncio.run(
        orchestrator.filter_items(
            [incoming],
            apply_balance=False,
            dedup_context=[published],
        )
    )

    assert item_identity(incoming) == item_identity(published)
    assert result.items == []
    assert result.topic_dedup_removed == 1


def test_filter_items_drops_semantic_duplicate_from_published_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = make_item(
        "published",
        "https://first.example/sberbank",
        datetime(2026, 7, 26, 4, 0, tzinfo=timezone.utc),
        8.0,
    )
    incoming = make_item(
        "incoming",
        "https://second.example/sberbank",
        datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc),
        9.0,
    )
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(ai_score_threshold=7.0),
    )
    orchestrator = BMTNewsOrchestrator(config, storage=object())

    async def keep_first(items, *, log=True):  # type: ignore[no-untyped-def]
        assert [item.id for item in items] == ["published", "incoming"]
        return items[:1]

    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", keep_first)

    result = asyncio.run(
        orchestrator.filter_items(
            [incoming],
            apply_balance=False,
            dedup_context=[published],
        )
    )

    assert result.items == []
    assert result.topic_dedup_removed == 1
