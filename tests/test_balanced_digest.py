import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from rich.console import Console

from src.models import (
    AIConfig,
    CategoryGroupConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
)
from src.orchestrator import BMTNewsOrchestrator


def make_item(
    item_id: str,
    score: float,
    category: str | None,
    *,
    feed_name: str | None = None,
) -> ContentItem:
    metadata = {"category": category} if category is not None else {}
    if feed_name is not None:
        metadata["feed_name"] = feed_name
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=item_id,
        url=f"https://example.com/{item_id}",
        published_at=datetime.now(timezone.utc),
        ai_score=score,
        metadata=metadata,
    )


def make_orchestrator(filtering: FilteringConfig) -> BMTNewsOrchestrator:
    orchestrator = BMTNewsOrchestrator.__new__(BMTNewsOrchestrator)
    orchestrator.config = SimpleNamespace(filtering=filtering)
    orchestrator.console = Console(record=True)
    return orchestrator


def test_unconfigured_balanced_digest_preserves_old_behavior() -> None:
    items = [make_item("lower", 7.0, "ai"), make_item("higher", 9.0, "finance")]
    result = make_orchestrator(FilteringConfig()).apply_balanced_digest(items)

    assert result.enabled is False
    assert result.items is items


def test_category_groups_apply_limits_and_default_group_limit() -> None:
    filtering = FilteringConfig(
        category_groups={
            "ai": CategoryGroupConfig(limit=2, categories=["ai", "ml"]),
            "finance": CategoryGroupConfig(limit=1, categories=["finance"]),
        },
        default_group_limit=1,
    )
    items = [
        make_item("ai-low", 7.0, "ai"),
        make_item("finance-low", 6.0, "finance"),
        make_item("other-high", 9.5, "world"),
        make_item("ai-high", 9.0, "ml"),
        make_item("finance-high", 8.5, "finance"),
        make_item("ai-mid", 8.0, "ai"),
        make_item("other-low", 5.0, None),
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == [
        "other-high",
        "ai-high",
        "finance-high",
        "ai-mid",
    ]
    assert result.group_counts == {"other": 1, "ai": 2, "finance": 1}


def test_max_items_applies_after_group_limits() -> None:
    filtering = FilteringConfig(
        max_items=2,
        category_groups={
            "ai": CategoryGroupConfig(limit=2, categories=["ai"]),
            "finance": CategoryGroupConfig(limit=2, categories=["finance"]),
        },
    )
    items = [
        make_item("finance", 8.0, "finance"),
        make_item("ai-top", 10.0, "ai"),
        make_item("ai-second", 9.0, "ai"),
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == ["ai-top", "ai-second"]
    assert result.group_counts == {"ai": 2}


def test_max_items_works_without_category_groups() -> None:
    filtering = FilteringConfig(max_items=1)
    items = [make_item("lower", 7.0, None), make_item("higher", 9.0, None)]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert [item.id for item in result.items] == ["higher"]


def test_primary_groups_reserve_crypto_slots_before_side_topics() -> None:
    filtering = FilteringConfig(
        max_items=12,
        category_groups={
            "exchange": CategoryGroupConfig(
                limit=5,
                categories=["exchange"],
            ),
            "markets": CategoryGroupConfig(limit=4, categories=["markets"]),
            "protocols": CategoryGroupConfig(limit=4, categories=["protocols"]),
            "technology": CategoryGroupConfig(limit=3, categories=["ai"]),
            "policy": CategoryGroupConfig(limit=2, categories=["policy"]),
        },
        primary_groups=["exchange", "markets", "protocols"],
        primary_group_min_items=9,
    )
    crypto_categories = [
        "exchange",
        "exchange",
        "exchange",
        "markets",
        "markets",
        "markets",
        "protocols",
        "protocols",
        "protocols",
        "protocols",
    ]
    items = [
        make_item(f"crypto-{index}", 8.0 - index / 100, category)
        for index, category in enumerate(crypto_categories)
    ]
    items += [
        make_item(f"ai-{index}", 10.0 - index / 100, "ai")
        for index in range(5)
    ]
    items += [
        make_item(f"policy-{index}", 9.0 - index / 100, "policy")
        for index in range(3)
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    categories = [item.metadata["category"] for item in result.items]
    assert len(result.items) == 12
    assert sum(
        category in {"exchange", "markets", "protocols"}
        for category in categories
    ) >= 9
    assert categories.count("ai") <= 3
    assert categories.count("policy") <= 2


def test_primary_groups_borrow_unused_capacity_without_relaxing_side_caps() -> None:
    filtering = FilteringConfig(
        max_items=12,
        category_groups={
            "markets": CategoryGroupConfig(limit=4, categories=["markets"]),
            "technology": CategoryGroupConfig(limit=3, categories=["ai"]),
            "policy": CategoryGroupConfig(limit=2, categories=["policy"]),
        },
        primary_groups=["markets"],
        primary_group_min_items=4,
        primary_group_borrow_limit=6,
        max_items_per_source=3,
    )
    items = [
        make_item(
            f"market-a-{index}",
            10 - index / 10,
            "markets",
            feed_name="a",
        )
        for index in range(5)
    ]
    items += [
        make_item(
            f"market-b-{index}",
            9 - index / 10,
            "markets",
            feed_name="b",
        )
        for index in range(2)
    ]
    items.append(
        make_item("market-c", 8.7, "markets", feed_name="c")
    )
    items += [
        make_item(f"ai-{index}", 8 - index / 10, "ai", feed_name="ai")
        for index in range(4)
    ]
    items += [
        make_item(f"policy-{index}", 7.5 - index / 10, "policy", feed_name="policy")
        for index in range(3)
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(
        items,
        allow_primary_borrowing=True,
    )

    categories = [item.metadata["category"] for item in result.items]
    assert categories.count("markets") == 6
    assert categories.count("ai") <= 3
    assert categories.count("policy") <= 2
    assert result.borrowed_count == 2
    assert result.group_limits["markets"] == 6


def test_source_limit_applies_before_category_limit() -> None:
    filtering = FilteringConfig(
        category_groups={
            "markets": CategoryGroupConfig(limit=4, categories=["markets"]),
        },
        max_items_per_source=3,
    )
    items = [
        make_item(
            f"market-{index}",
            10 - index / 10,
            "markets",
            feed_name="CoinDesk",
        )
        for index in range(6)
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(items)

    assert len(result.items) == 3
    assert result.source_limit_deferred == 3


def test_minimum_fill_recovers_qualified_crypto_from_one_source() -> None:
    filtering = FilteringConfig(
        max_items=12,
        minimum_display_items=7,
        category_groups={
            "markets": CategoryGroupConfig(limit=4, categories=["markets"]),
            "technology": CategoryGroupConfig(limit=3, categories=["ai"]),
            "policy": CategoryGroupConfig(limit=2, categories=["policy"]),
        },
        primary_groups=["markets"],
        primary_group_min_items=4,
        primary_group_borrow_limit=6,
        max_items_per_source=3,
    )
    items = [
        make_item(
            f"market-{index}",
            10 - index / 10,
            "markets",
            feed_name="CoinDesk",
        )
        for index in range(9)
    ]
    result = make_orchestrator(filtering).apply_balanced_digest(
        items,
        allow_primary_borrowing=True,
        fill_to_minimum=True,
    )

    categories = [item.metadata["category"] for item in result.items]
    assert len(result.items) == 7
    assert categories.count("markets") == 7
    assert result.minimum_fill_count == 4


def test_minimum_fill_does_not_relax_ai_or_policy_caps() -> None:
    filtering = FilteringConfig(
        max_items=12,
        minimum_display_items=12,
        category_groups={
            "markets": CategoryGroupConfig(limit=4, categories=["markets"]),
            "technology": CategoryGroupConfig(limit=3, categories=["ai"]),
            "policy": CategoryGroupConfig(limit=2, categories=["policy"]),
        },
        primary_groups=["markets"],
        primary_group_min_items=4,
        primary_group_borrow_limit=6,
        max_items_per_source=3,
    )
    items = [
        make_item(
            f"market-{index}",
            10 - index / 100,
            "markets",
            feed_name="CoinDesk",
        )
        for index in range(9)
    ]
    items += [
        make_item(f"ai-{index}", 8 - index / 100, "ai", feed_name="AI")
        for index in range(5)
    ]
    items += [
        make_item(
            f"policy-{index}",
            7.5 - index / 100,
            "policy",
            feed_name="Policy",
        )
        for index in range(4)
    ]

    result = make_orchestrator(filtering).apply_balanced_digest(
        items,
        allow_primary_borrowing=True,
        fill_to_minimum=True,
    )

    categories = [item.metadata["category"] for item in result.items]
    assert len(result.items) == 12
    assert categories.count("markets") == 7
    assert categories.count("ai") == 3
    assert categories.count("policy") == 2


def test_duplicate_category_warns_and_first_group_wins() -> None:
    filtering = FilteringConfig(
        category_groups={
            "first": CategoryGroupConfig(limit=1, categories=["shared"]),
            "second": CategoryGroupConfig(limit=2, categories=["shared"]),
        }
    )
    orchestrator = make_orchestrator(filtering)

    result = orchestrator.apply_balanced_digest(
        [make_item("top", 9.0, "shared"), make_item("second", 8.0, "shared")]
    )

    assert [item.id for item in result.items] == ["top"]
    assert result.duplicate_categories == ["shared"]
    assert "using 'first'" in orchestrator.console.export_text()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_items": 0},
        {"default_group_limit": 0},
        {"category_groups": {"ai": {"limit": 0, "categories": ["ai"]}}},
        {"category_groups": {"ai": {"limit": 1, "categories": []}}},
        {
            "primary_groups": ["missing"],
            "primary_group_min_items": 1,
        },
        {
            "category_groups": {
                "primary": {"limit": 1, "categories": ["main"]}
            },
            "primary_groups": ["primary"],
            "primary_group_min_items": 2,
        },
        {"minimum_display_items": 3, "max_items": 2},
        {"time_window_hours": 24, "fallback_window_hours": 24},
        {"primary_group_borrow_limit": 6},
    ],
)
def test_balanced_digest_config_rejects_non_positive_or_empty_limits(kwargs) -> None:
    with pytest.raises(ValidationError):
        FilteringConfig(**kwargs)


def test_run_applies_balanced_digest_before_enrichment(tmp_path, monkeypatch) -> None:
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
            category_groups={
                "ai": CategoryGroupConfig(limit=1, categories=["ai"]),
                "finance": CategoryGroupConfig(limit=1, categories=["finance"]),
            },
        ),
    )
    storage = SimpleNamespace()
    orchestrator = BMTNewsOrchestrator(config, storage)
    items = [
        make_item("ai", 9.0, "ai"),
        make_item("finance", 8.0, "finance"),
        make_item("below-threshold", 6.0, "ai"),
    ]
    enriched_ids: list[str] = []

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return items

    async def analyze_content(input_items):  # type: ignore[no-untyped-def]
        return input_items

    async def merge_topic_duplicates(input_items, *, log=True):  # type: ignore[no-untyped-def]
        return input_items

    async def expand_twitter_discussion(input_items):  # type: ignore[no-untyped-def]
        return None

    async def enrich_important_items(input_items):  # type: ignore[no-untyped-def]
        enriched_ids.extend(item.id for item in input_items)

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", merge_topic_duplicates)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", expand_twitter_discussion)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", enrich_important_items)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run())

    assert enriched_ids == ["ai"]


def test_run_balances_after_twitter_reanalysis(tmp_path, monkeypatch) -> None:
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=[],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(ai_score_threshold=7.0, max_items=1),
    )
    orchestrator = BMTNewsOrchestrator(config, SimpleNamespace())
    items = [make_item("first", 9.0, "ai"), make_item("second", 8.0, "ai")]
    enriched_ids: list[str] = []

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return items

    async def analyze_content(input_items):  # type: ignore[no-untyped-def]
        return input_items

    async def merge_topic_duplicates(input_items, *, log=True):  # type: ignore[no-untyped-def]
        return input_items

    async def expand_twitter_discussion(input_items):  # type: ignore[no-untyped-def]
        input_items[0].ai_score = 7.0
        input_items[1].ai_score = 10.0
        input_items.sort(key=lambda item: item.ai_score or 0, reverse=True)

    async def enrich_important_items(input_items):  # type: ignore[no-untyped-def]
        enriched_ids.extend(item.id for item in input_items)

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(orchestrator, "merge_topic_duplicates", merge_topic_duplicates)
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", expand_twitter_discussion)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", enrich_important_items)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run())

    assert enriched_ids == ["second"]
