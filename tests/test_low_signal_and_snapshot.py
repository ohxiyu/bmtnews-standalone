"""Tests for low-signal rescue selection and edition header extras."""

from datetime import datetime, timezone
from types import SimpleNamespace

from rich.console import Console

from src.market_snapshot import MarketSnapshot
from src.models import ContentItem, FilteringConfig, SourceType
from src.orchestrator import BMTNewsOrchestrator
from src.web_feed import render_web_feed


def make_item(
    item_id: str,
    score: float | None,
    *,
    feed_name: str = "Example Feed",
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Title {item_id}",
        url=f"https://example.com/{item_id}",
        published_at=datetime.now(timezone.utc),
        ai_score=score,
        metadata={"feed_name": feed_name, "category": "crypto-markets"},
    )


def make_orchestrator() -> BMTNewsOrchestrator:
    orchestrator = BMTNewsOrchestrator.__new__(BMTNewsOrchestrator)
    orchestrator.config = SimpleNamespace(filtering=FilteringConfig())
    orchestrator.console = Console(record=True)
    return orchestrator


def test_rescue_picks_highest_scores_with_source_diversity() -> None:
    items = [
        make_item("a", 6.5, feed_name="Feed A"),
        make_item("b", 6.0, feed_name="Feed A"),
        make_item("c", 5.5, feed_name="Feed A"),
        make_item("d", 5.0, feed_name="Feed B"),
        make_item("e", None, feed_name="Feed C"),
    ]
    rescued = make_orchestrator()._rescue_low_signal_items(items, limit=3)
    assert [item.id for item in rescued] == ["a", "b", "d"]


def test_rescue_respects_limit() -> None:
    items = [make_item(str(i), 6.0 - i * 0.1, feed_name=f"F{i}") for i in range(8)]
    rescued = make_orchestrator()._rescue_low_signal_items(items, limit=5)
    assert len(rescued) == 5


def test_render_web_feed_includes_overview_and_market_snapshot() -> None:
    market = MarketSnapshot(
        btc_price=116235.0,
        btc_change_24h=1.23,
        eth_price=4321.0,
        eth_change_24h=-2.5,
        fear_greed_value=62,
        fear_greed_label="Greed",
    )
    markup = render_web_feed(
        [make_item("story", 8.0)],
        date="2026-08-08",
        total_fetched=40,
        language="zh",
        display_timezone="Asia/Shanghai",
        overview="今日重点：<示例> 导语。",
        market=market,
    )
    assert 'class="feed-overview"' in markup
    assert "&lt;示例&gt;" in markup  # escaped
    assert 'class="market-snapshot"' in markup
    assert "$116,235" in markup
    assert 'data-direction="down"' in markup
    assert "贪婪" in markup


def test_render_web_feed_omits_extras_when_absent() -> None:
    markup = render_web_feed(
        [make_item("story", 8.0)],
        date="2026-08-08",
        total_fetched=40,
        language="en",
        display_timezone="Asia/Shanghai",
    )
    assert "feed-overview" not in markup
    assert "market-snapshot" not in markup


class _ScriptedClient:
    """Returns a fixed completion, standing in for the AI client."""

    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, **_kwargs) -> str:
        return self.response


def test_edition_overview_unwraps_a_json_wrapped_lede() -> None:
    """Most prompts here ask for JSON, so a prose prompt sometimes gets it."""
    import asyncio

    from src.ai.summarizer import generate_edition_overview

    client = _ScriptedClient('{"lede": "BitMart 创始人否认跑路，提现仍停滞。"}')
    overview = asyncio.run(
        generate_edition_overview(
            client, [make_item("a", 8.0)], date="2026-08-11", language="zh"
        )
    )
    assert overview == "BitMart 创始人否认跑路，提现仍停滞。"


def test_edition_overview_keeps_plain_prose_untouched() -> None:
    import asyncio

    from src.ai.summarizer import generate_edition_overview

    client = _ScriptedClient("BitMart 创始人否认跑路，提现仍停滞。")
    overview = asyncio.run(
        generate_edition_overview(
            client, [make_item("a", 8.0)], date="2026-08-11", language="zh"
        )
    )
    assert overview == "BitMart 创始人否认跑路，提现仍停滞。"
