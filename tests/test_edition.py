from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.daily_feed import (
    DailyFeedState,
    load_daily_feed_state,
    save_daily_feed_state,
)
from src.edition import (
    StagingStateError,
    edition_window_for,
    edition_window_for_date,
    items_in_edition_window,
    items_in_supplemental_window,
    load_staging_state,
    merge_staged_items,
    save_staging_state,
)
from src.models import (
    AIConfig,
    CategoryGroupConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
    TelegramDeliveryConfig,
)
from src.orchestrator import BMTNewsOrchestrator
from src.run_report import load_run_report
from src.services.telegram_delivery import (
    TelegramDeliveryResult,
    TelegramDeliveryStatus,
)
from src.storage.manager import StorageManager


SHANGHAI = ZoneInfo("Asia/Shanghai")


def make_item(
    item_id: str,
    published_at: datetime,
    *,
    url: str | None = None,
    content: str | None = None,
    score: float = 8.0,
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=item_id,
        url=url or f"https://example.com/{item_id}",
        content=content,
        published_at=published_at,
        ai_score=score,
        metadata={"category": "crypto-markets"},
    )


def test_edition_window_uses_latest_completed_fixed_cutoff() -> None:
    after_cutoff = datetime(2026, 7, 29, 20, 17, tzinfo=SHANGHAI)
    before_cutoff = datetime(2026, 7, 29, 19, 59, tzinfo=SHANGHAI)

    current = edition_window_for(after_cutoff, "Asia/Shanghai", 20)
    previous = edition_window_for(before_cutoff, "Asia/Shanghai", 20)

    assert current.date == "2026-07-29"
    assert current.start == datetime(2026, 7, 28, 20, 0, tzinfo=SHANGHAI)
    assert current.end == datetime(2026, 7, 29, 20, 0, tzinfo=SHANGHAI)
    assert previous.date == "2026-07-28"
    assert previous.end == datetime(2026, 7, 28, 20, 0, tzinfo=SHANGHAI)


def test_explicit_edition_date_targets_morning_window() -> None:
    window = edition_window_for_date(
        date(2026, 7, 31),
        "Asia/Shanghai",
        8,
    )

    assert window.date == "2026-07-31"
    assert window.start == datetime(2026, 7, 30, 8, 0, tzinfo=SHANGHAI)
    assert window.end == datetime(2026, 7, 31, 8, 0, tzinfo=SHANGHAI)


def test_edition_window_is_start_inclusive_and_end_exclusive() -> None:
    window = edition_window_for(
        datetime(2026, 7, 29, 20, 17, tzinfo=SHANGHAI),
        "Asia/Shanghai",
        20,
    )
    items = [
        make_item("start", window.start),
        make_item("inside", window.end.replace(hour=19, minute=59)),
        make_item("end", window.end),
    ]

    assert [
        item.id for item in items_in_edition_window(items, window)
    ] == ["start", "inside"]


def test_supplemental_window_only_returns_preceding_segment() -> None:
    window = edition_window_for_date("2026-07-29", "Asia/Shanghai", 8)
    items = [
        make_item("too-old", datetime(2026, 7, 27, 19, 59, tzinfo=SHANGHAI)),
        make_item("supplemental", datetime(2026, 7, 28, 2, 0, tzinfo=SHANGHAI)),
        make_item("normal", datetime(2026, 7, 28, 8, 0, tzinfo=SHANGHAI)),
    ]

    assert [
        item.id for item in items_in_supplemental_window(items, window, 36)
    ] == ["supplemental"]


def test_staging_merge_deduplicates_urls_and_bounds_retention() -> None:
    now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
    existing = make_item(
        "existing",
        datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
        url="https://example.com/story?utm_source=old",
        content="short",
    )
    incoming = make_item(
        "incoming",
        datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
        url="https://example.com/story",
        content="a richer source body",
    )
    expired = make_item(
        "expired",
        datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
    )

    merged = merge_staged_items(
        [existing, expired],
        [incoming],
        now=now,
        retention_hours=72,
    )

    assert [item.id for item in merged] == ["incoming"]


def test_staging_state_round_trips_and_rejects_invalid_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "staging.json"
    item = make_item(
        "one",
        datetime(2026, 7, 29, 8, 0, tzinfo=timezone.utc),
    )
    save_staging_state([item], path)
    assert [loaded.id for loaded in load_staging_state(path).items] == ["one"]

    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(StagingStateError):
        load_staging_state(path)


def test_daily_edition_combines_staging_and_final_fetch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 29, 8, 30, tzinfo=SHANGHAI)
    staged = make_item(
        "staged",
        datetime(2026, 7, 28, 12, 0, tzinfo=SHANGHAI),
        score=8.0,
    )
    fresh = make_item(
        "fresh",
        datetime(2026, 7, 29, 7, 0, tzinfo=SHANGHAI),
        score=9.0,
    )
    next_edition = make_item(
        "next",
        datetime(2026, 7, 29, 8, 5, tzinfo=SHANGHAI),
        score=10.0,
    )
    staging_path = tmp_path / "data" / "staging-items.json"
    save_staging_state([staged], staging_path, updated_at=now)
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=["zh"],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            daily_timezone="Asia/Shanghai",
            category_groups={
                "markets": CategoryGroupConfig(
                    name="Crypto Markets",
                    limit=4,
                    categories=["crypto-markets"],
                )
            },
            primary_groups=["markets"],
            primary_group_min_items=3,
        ),
        telegram_delivery=TelegramDeliveryConfig(enabled=True),
    )
    orchestrator = BMTNewsOrchestrator(
        config,
        storage=StorageManager(data_dir=str(tmp_path / "data")),
    )
    analyzed_ids: list[str] = []
    telegram_calls: list[tuple[str, int, str]] = []

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return [fresh, next_edition]

    async def analyze_content(items):  # type: ignore[no-untyped-def]
        analyzed_ids.extend(item.id for item in items)
        return items

    async def no_topic_duplicates(items, *, log=True):  # type: ignore[no-untyped-def]
        return items

    async def no_op(items):  # type: ignore[no-untyped-def]
        return None

    async def send_telegram(
        items, *, date, total_candidates, language
    ):  # type: ignore[no-untyped-def]
        if language != "zh":
            return TelegramDeliveryResult(TelegramDeliveryStatus.SKIPPED)
        telegram_calls.append((date, total_candidates, language))
        return TelegramDeliveryResult(
            TelegramDeliveryStatus.SUCCESS,
            message_length=1234,
        )

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(
        orchestrator,
        "merge_topic_duplicates",
        no_topic_duplicates,
    )
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", no_op)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", no_op)
    monkeypatch.setattr(
        orchestrator.telegram_publisher,
        "send_daily_edition",
        send_telegram,
    )
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        orchestrator.run_daily_edition(
            force_hours=24,
            staging_path=staging_path,
            now=now,
        )
    )

    state = load_daily_feed_state(
        "2026-07-29",
        "Asia/Shanghai",
        tmp_path / "docs" / "_data" / "bmtnews_state.json",
    )
    assert analyzed_ids == ["fresh", "staged"]
    assert [item.id for item in state.items] == ["fresh", "staged"]
    assert "next" not in analyzed_ids
    post = (
        tmp_path / "docs" / "_posts" / "2026-07-29-summary-zh.md"
    ).read_text(encoding="utf-8")
    assert 'window_start: "2026-07-28T08:00:00+08:00"' in post
    assert 'window_end: "2026-07-29T08:00:00+08:00"' in post
    assert "fetched_count: 2" in post
    assert "selected_count: 2" in post
    assert 'fragment_url: "/editions/2026-07-29/zh.html"' in post
    assert (
        'class="daily-feed-layout is-editorial-grid feed-rendered-static"'
        in post
    )
    fragment = (
        tmp_path / "docs" / "editions" / "2026-07-29" / "zh.html"
    ).read_text(encoding="utf-8")
    assert 'data-feed-fragment="2"' in fragment
    assert 'id="zh-2026-07-29-item-1"' in fragment
    report = load_run_report(tmp_path / "data" / "run-report.json")
    assert report["kind"] == "daily_publish"
    assert report["metrics"]["staging_items_before"] == 1
    assert report["metrics"]["staging_only_candidates"] == 1
    assert report["metrics"]["cutoff_lag_minutes"] == 30
    assert report["window_start"] == "2026-07-28T08:00:00+08:00"
    assert report["window_end"] == "2026-07-29T08:00:00+08:00"
    assert report["breakdowns"]["candidate_sources"] == {
        "rss/unknown": 2
    }
    assert report["breakdowns"]["selected_groups"] == {
        "Crypto Markets": 2
    }
    assert report["metrics"]["primary_selected"] == 2
    assert report["metrics"]["primary_required"] == 3
    assert report["metrics"]["telegram_messages_sent"] == 1
    assert report["metrics"]["telegram_message_chars"] == 1234
    assert telegram_calls == [("2026-07-29", 2, "zh")]
    assert any(
        alert["code"] == "primary_quota_shortfall"
        for alert in report["alerts"]
    )

    asyncio.run(
        orchestrator.run_daily_edition(
            force_hours=24,
            staging_path=staging_path,
            now=datetime(2026, 7, 29, 9, 17, tzinfo=SHANGHAI),
        )
    )
    retry_report = load_run_report(tmp_path / "data" / "run-report.json")
    assert analyzed_ids == ["fresh", "staged"]
    assert telegram_calls == [("2026-07-29", 2, "zh")]
    assert retry_report["metrics"]["displayed_today"] == 2
    assert any(
        alert["code"] == "edition_already_published"
        for alert in retry_report["alerts"]
    )


def test_daily_edition_uses_unpublished_36_hour_fallback_when_short(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 7, 29, 8, 30, tzinfo=SHANGHAI)
    normal = make_item(
        "normal",
        datetime(2026, 7, 29, 7, 0, tzinfo=SHANGHAI),
        score=8.0,
    )
    supplemental = make_item(
        "supplemental",
        datetime(2026, 7, 28, 2, 0, tzinfo=SHANGHAI),
        score=8.5,
    )
    already_published = make_item(
        "published-again",
        datetime(2026, 7, 28, 3, 0, tzinfo=SHANGHAI),
        url="https://example.com/published",
        score=9.0,
    )
    staging_path = tmp_path / "data" / "staging-items.json"
    save_staging_state(
        [supplemental, already_published],
        staging_path,
        updated_at=now,
    )
    save_daily_feed_state(
        DailyFeedState(
            date="2026-07-28",
            timezone="Asia/Shanghai",
            updated_at=datetime(2026, 7, 28, 8, 30, tzinfo=SHANGHAI),
            items=[already_published],
        ),
        tmp_path / "docs" / "_data" / "bmtnews_state.json",
    )
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
            time_window_hours=24,
            daily_timezone="Asia/Shanghai",
            max_items=4,
            minimum_candidate_items=3,
            minimum_qualified_items=3,
            minimum_display_items=2,
            fallback_window_hours=36,
            primary_group_borrow_limit=6,
            max_items_per_source=3,
            category_groups={
                "markets": CategoryGroupConfig(
                    name="Crypto Markets",
                    limit=4,
                    categories=["crypto-markets"],
                )
            },
            primary_groups=["markets"],
            primary_group_min_items=2,
        ),
    )
    orchestrator = BMTNewsOrchestrator(
        config,
        storage=StorageManager(data_dir=str(tmp_path / "data")),
    )
    analyzed_ids: list[str] = []
    requested_since: list[datetime] = []

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        requested_since.append(since)
        return [normal]

    async def analyze_content(items):  # type: ignore[no-untyped-def]
        analyzed_ids.extend(item.id for item in items)
        return items

    async def no_topic_duplicates(items, *, log=True):  # type: ignore[no-untyped-def]
        return items

    async def no_op(items):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(
        orchestrator,
        "merge_topic_duplicates",
        no_topic_duplicates,
    )
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", no_op)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", no_op)
    monkeypatch.chdir(tmp_path)

    asyncio.run(
        orchestrator.run_daily_edition(
            staging_path=staging_path,
            now=now,
        )
    )

    state = load_daily_feed_state(
        "2026-07-29",
        "Asia/Shanghai",
        tmp_path / "docs" / "_data" / "bmtnews_state.json",
    )
    report = load_run_report(tmp_path / "data" / "run-report.json")
    assert requested_since == [datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)]
    assert analyzed_ids == ["normal", "supplemental"]
    assert [item.id for item in state.items] == ["supplemental", "normal"]
    assert report["metrics"]["edition_candidates"] == 1
    assert report["metrics"]["fallback_candidates"] == 2
    assert report["metrics"]["fallback_analyzed"] == 1
    assert report["metrics"]["skipped_published_history"] == 1
    assert {alert["code"] for alert in report["alerts"]} >= {
        "candidate_shortage",
        "qualified_content_shortage",
        "fallback_window_used",
    }


def test_workflows_stage_twice_and_publish_once() -> None:
    root = Path(__file__).parents[1]
    collection = (
        root / ".github" / "workflows" / "feed-collection.yml"
    ).read_text(encoding="utf-8")
    publication = (
        root / ".github" / "workflows" / "daily-summary.yml"
    ).read_text(encoding="utf-8")

    assert "cron: '30 0,4,12,16,20 * * *'" in collection
    assert "17 2,8,14" not in collection
    assert "staging-cache" in collection
    assert "staging-cache" in publication
    assert "bmtnews --mode fetch --hours 12" in collection
    assert "Restore published event state" in collection
    assert "Collect sources and increment event timelines" in collection
    assert "Deploy incremental event pages" in collection
    assert "\n  schedule:" not in publication
    assert "args=(--mode publish --hours 24 --cutoff-hour 8)" in publication
    assert "edition_date:" in publication
    assert 'args+=(--edition-date "${{ inputs.edition_date }}")' in publication
    assert "force_publish:" in publication
    assert "args+=(--force-publish)" in publication
    assert "bmtnews-staging-v1-" in collection
    assert "bmtnews-staging-v1-" in publication
    assert "timeout-minutes: 30" in collection
    assert "timeout-minutes: 30" in publication
    assert "GITHUB_TOKEN: ${{ github.token }}" in collection
    assert "GITHUB_TOKEN: ${{ github.token }}" in publication
    assert "actions: write" in publication
    assert "gh workflow run x-distribution.yml" in publication
    assert '-f kickoff_only=true' in publication
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in publication
    assert "TELEGRAM_CHANNEL_ID: ${{ secrets.TELEGRAM_CHANNEL_ID }}" in publication
