"""Tests for drip-mode X distribution."""

import asyncio
from datetime import datetime, timezone

from src.models import ContentItem, SourceType, XDeliveryConfig
from src.services.x_delivery import (
    TWEET_LIMIT,
    _weighted_length,
    build_story_post,
)


def make_item(
    title: str,
    *,
    summary: str = "",
    impact: str = "",
    url: str = "https://example.com/story",
) -> ContentItem:
    metadata = {"title_zh": title}
    if summary:
        metadata["detailed_summary_zh"] = summary
    if impact:
        metadata["market_impact_zh"] = impact
    return ContentItem(
        id=title,
        source_type=SourceType.RSS,
        title=title,
        url=url,
        published_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ai_score=9.0,
        metadata=metadata,
    )


def test_story_post_prefers_market_impact_and_fits() -> None:
    item = make_item(
        "Bybit 起诉朝鲜与 Lazarus Group",
        summary=(
            "8月9日，新加坡，Bybit起诉朝鲜与Lazarus Group，指控其参与盗币。"
            "第二句不应出现。"
        ),
        impact="影响集中在托管与合规成本。第二句不应出现。",
    )
    text = build_story_post(
        item, language="zh", site_url="https://bmt.news/", link_target="site"
    )
    assert "Bybit" in text and "Lazarus Group" in text
    assert "影响集中在托管与合规成本。" in text
    assert "第二句不应出现" not in text
    assert text.split("\n\n", 1)[0].startswith("8月9日，新加坡")
    assert text.rstrip().endswith("https://bmt.news/")
    assert _weighted_length(text) <= TWEET_LIMIT


def test_story_post_falls_back_to_summary_and_source_link() -> None:
    item = make_item("标题", summary="只有摘要可用。")
    text = build_story_post(
        item, language="zh", site_url="https://bmt.news/", link_target="source"
    )
    assert "只有摘要可用。" in text
    assert text.rstrip().endswith("https://example.com/story")


def test_story_post_truncates_a_very_long_headline() -> None:
    item = make_item("超长标题" * 60)
    text = build_story_post(
        item, language="zh", site_url="https://bmt.news/", limit=TWEET_LIMIT
    )
    assert _weighted_length(text) <= TWEET_LIMIT
    # Truncation must respect CJK double-weighting, not slice by character.
    text_with_link = build_story_post(
        item,
        language="zh",
        site_url="https://bmt.news/",
        link_target="site",
        limit=TWEET_LIMIT,
    )
    assert _weighted_length(text_with_link) <= TWEET_LIMIT


def test_story_post_does_not_break_on_abbreviations() -> None:
    item = make_item(
        "CLARITY法案将于9月面临参议院60票对决",
        summary=(
            "参议院多数党领袖约翰·图恩对《CLARITY法案》（H.R. 3633）表态支持。"
            "第二句不应出现。"
        ),
    )
    text = build_story_post(item, language="zh", site_url="https://bmt.news/")
    assert "（H.R. 3633）表态支持。" in text
    assert "第二句不应出现" not in text


def test_story_post_handles_english_sentences() -> None:
    item = ContentItem(
        id="en",
        source_type=SourceType.RSS,
        title="Headline",
        url="https://example.com/en",
        published_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ai_score=9.0,
        metadata={
            "title_en": "US Senate schedules the vote",
            "detailed_summary_en": "The U.S. Senate set a date. A second sentence.",
        },
    )
    text = build_story_post(item, language="en", site_url="https://bmt.news/")
    assert "The U.S. Senate set a date." in text
    assert "A second sentence" not in text


# --- X character counting (twitter-text v3 weighting) ---------------------

def test_weighted_length_counts_cjk_as_two() -> None:
    from src.services.x_delivery import _weighted_length

    assert _weighted_length("abc") == 3
    assert _weighted_length("比特币") == 6
    assert _weighted_length("BTC 分叉") == 3 + 1 + 4


def test_weighted_length_collapses_urls_to_a_tco_token() -> None:
    from src.services.x_delivery import TCO_LENGTH, _weighted_length

    long_url = "https://example.com/" + "a" * 200
    assert _weighted_length(long_url) == TCO_LENGTH
    assert _weighted_length(f"甲 {long_url} 乙") == 2 + 1 + TCO_LENGTH + 1 + 2


# --- AI-composed posts ----------------------------------------------------

# A post at the length the compact brief asks for: the event remains complete,
# but only the essential timeline, mechanism and current status are retained.
GOOD = (
    "8月22日，美国华盛顿，CFTC主席Michael Selig表示正推动Hyperliquid在合规框架下进入美国市场。\n\n"
    "消息公布后HYPE上涨23%，平台仍需完成衍生品规则要求的注册与客户保护安排，目前尚无正式上线日期。"
)


def test_sanitize_keeps_a_clean_post() -> None:
    from src.services.x_delivery import sanitize_composed_post

    assert sanitize_composed_post(GOOD, limit=400) == GOOD


def test_sanitize_strips_links_tags_and_markdown() -> None:
    from src.services.x_delivery import sanitize_composed_post

    raw = f'"**{GOOD}** #比特币 #BTC https://example.com/x"'
    cleaned = sanitize_composed_post(raw, limit=400)
    assert cleaned is not None
    assert "#" not in cleaned
    assert "http" not in cleaned
    assert "**" not in cleaned
    assert not cleaned.startswith('"')
    assert "8月22日，美国华盛顿" in cleaned


def test_sanitize_rejects_unusable_output() -> None:
    from src.services.x_delivery import sanitize_composed_post

    assert sanitize_composed_post("", limit=400) is None
    assert sanitize_composed_post("   ", limit=400) is None
    # Too short to be a real post.
    assert sanitize_composed_post("分叉了。", limit=400) is None
    # Over the configured limit.
    assert sanitize_composed_post("超长" * 300, limit=400) is None


def test_sanitize_requires_a_one_sentence_lede_and_body_paragraph() -> None:
    from src.services.x_delivery import sanitize_composed_post

    no_body_break = GOOD.replace("\n\n", " ")
    two_sentence_lede = GOOD.replace(
        "表示正推动", "宣布调整监管路径。该机构正推动", 1
    )
    assert sanitize_composed_post(no_body_break, limit=400) is None
    assert sanitize_composed_post(two_sentence_lede, limit=400) is None


class ComposingClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def complete(
        self, *, system: str, user: str, response_format: str = "json"
    ) -> str:
        self.calls.append(
            {"system": system, "user": user, "response_format": response_format}
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


async def _test_compose_uses_enriched_fields() -> None:
    from src.services.x_delivery import compose_story_post

    item = make_item("标题")
    item.metadata.update(
        {
            "detailed_summary_zh": "摘要内容",
            "background_zh": "背景内容",
            "market_impact_zh": "影响内容",
        }
    )
    client = ComposingClient(GOOD)
    text = await compose_story_post(client, item, language="zh", limit=400)
    assert text == GOOD
    sent = client.calls[0]["user"]
    assert "摘要内容" in sent and "背景内容" in sent and "影响内容" in sent
    assert "禁止话题标签" in client.calls[0]["system"]


async def _test_compose_returns_none_on_failure_or_bad_output() -> None:
    from src.services.x_delivery import compose_story_post

    item = make_item("标题")
    assert (
        await compose_story_post(
            ComposingClient(RuntimeError("boom")), item, language="zh"
        )
        is None
    )
    assert (
        await compose_story_post(ComposingClient("太短。"), item, language="zh")
        is None
    )


def test_compose_uses_enriched_fields() -> None:
    asyncio.run(_test_compose_uses_enriched_fields())


def test_compose_returns_none_on_failure_or_bad_output() -> None:
    asyncio.run(_test_compose_returns_none_on_failure_or_bad_output())


def test_template_post_omits_the_link_by_default() -> None:
    from src.services.x_delivery import build_story_post

    item = make_item("标题", summary="一句摘要内容。")
    text = build_story_post(item, language="zh", site_url="https://bmt.news/")
    assert "http" not in text
    assert "标题" in text and "一句摘要内容。" in text


async def _test_compose_never_shows_the_article_body() -> None:
    """Posts draw only on published fields; raw article text stays out."""
    from src.services.x_delivery import compose_story_post

    item = make_item("标题")
    item.content = "区块 961,632 触发自动执行条款，矿工信号率 2.6%。" * 40
    item.metadata["detailed_summary_zh"] = "摘要内容"
    client = ComposingClient(GOOD)
    await compose_story_post(client, item, language="zh", limit=400)
    sent = client.calls[0]["user"]
    assert "区块 961,632" not in sent
    assert "原文" not in sent
    assert "摘要内容" in sent
    system = client.calls[0]["system"]
    assert "90-150" in system
    assert "第一段只能有一句话" in system
    assert "时间、地点或场合、人物或机构" in system
    assert "不能推算、合计或改动数值" in system


def test_compose_never_shows_the_article_body() -> None:
    asyncio.run(_test_compose_never_shows_the_article_body())


def test_sanitize_rejects_a_headline_only_post() -> None:
    """A headline and one detail are still a failed generation."""
    from src.services.x_delivery import sanitize_composed_post

    short = "比特币发生分叉。矿工信号只有 2.6%，远不到 55% 的门槛。"
    assert sanitize_composed_post(short, limit=400) is None
    assert sanitize_composed_post(GOOD, limit=400) == GOOD


def test_x_delivery_defaults_to_the_compact_limit() -> None:
    assert XDeliveryConfig().max_post_chars == 400
