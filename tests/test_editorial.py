"""Tests for the manual editorial layer."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from src.editorial import (
    EditorialEntry,
    editorial_content_item,
    load_editorial_plan,
)
from src.models import ContentItem, SourceType
from src.web_feed import render_web_feed


def write_editorial(tmp_path: Path, items: list) -> Path:
    path = tmp_path / "editorial.json"
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    return path


def make_story(item_id: str = "story") -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Title {item_id}",
        url=f"https://example.com/{item_id}",
        published_at=datetime(2026, 8, 9, 1, tzinfo=timezone.utc),
        ai_score=8.0,
        metadata={"category": "crypto-markets", "feed_name": "Feed"},
    )


def test_plan_filters_by_date_window(tmp_path: Path) -> None:
    path = write_editorial(
        tmp_path,
        [
            {
                "type": "editorial",
                "url": "https://example.com/a",
                "title_zh": "今天",
                "date": "2026-08-09",
            },
            {
                "type": "editorial",
                "url": "https://example.com/b",
                "title_zh": "昨天",
                "date": "2026-08-08",
            },
            {
                "type": "sponsored",
                "url": "https://example.com/ad",
                "title_zh": "广告",
                "starts": "2026-08-01",
                "expires": "2026-08-09",
            },
            {
                "type": "sponsored",
                "url": "https://example.com/expired",
                "title_zh": "过期广告",
                "expires": "2026-08-08",
            },
            {
                "type": "editorial",
                "url": "https://example.com/off",
                "title_zh": "停用",
                "enabled": False,
            },
            {"type": "suppress", "url": "https://example.com/hide"},
        ],
    )
    plan = load_editorial_plan(date(2026, 8, 9), path)
    assert [e.url for e in plan.editorial] == ["https://example.com/a"]
    assert [e.url for e in plan.sponsored] == ["https://example.com/ad"]
    assert plan.suppressed_urls == ["https://example.com/hide"]


def test_plan_is_fail_soft(tmp_path: Path) -> None:
    missing = load_editorial_plan(date(2026, 8, 9), tmp_path / "nope.json")
    assert missing.is_empty

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert load_editorial_plan(date(2026, 8, 9), broken).is_empty

    path = write_editorial(
        tmp_path,
        [
            {"type": "editorial", "title_zh": "缺 url"},
            {"type": "unknown", "url": "https://example.com/x", "title_zh": "x"},
            {"type": "editorial", "url": "https://example.com/ok", "title_zh": "好"},
        ],
    )
    plan = load_editorial_plan(date(2026, 8, 9), path)
    assert [e.url for e in plan.editorial] == ["https://example.com/ok"]


def test_editorial_content_item_carries_bilingual_metadata() -> None:
    entry = EditorialEntry(
        type="editorial",
        url="https://example.com/pick",
        title_zh="中文标题",
        title_en="English title",
        summary_zh="中文摘要。",
    )
    item = editorial_content_item(entry, date(2026, 8, 9))
    assert item.source_type == SourceType.EDITORIAL
    assert item.metadata["editorial"] is True
    assert item.metadata["title_zh"] == "中文标题"
    assert item.metadata["title_en"] == "English title"
    assert item.metadata["detailed_summary_zh"] == "中文摘要。"
    assert item.ai_score is None


def test_editorial_content_item_carries_full_manual_context() -> None:
    entry = EditorialEntry(
        type="editorial",
        url="https://example.com/pick",
        title_zh="交易所发布公告",
        summary_zh="公告确认了具体变更。",
        background_zh="该功能此前只面向机构用户。",
        market_impact_zh="变更扩大了零售用户的市场准入。",
        community_discussion_zh="执行时间仍需确认。",
        category="crypto-exchange",
        tags=["Exchange", " announcement "],
        sources=[
            {"title": "官方说明", "url": "https://example.com/reference"},
            {"title": "坏链接", "url": "javascript:alert(1)"},
        ],
        official=True,
    )

    item = editorial_content_item(entry, date(2026, 8, 9))

    assert item.metadata["background_zh"] == "该功能此前只面向机构用户。"
    assert item.metadata["market_impact_zh"] == "变更扩大了零售用户的市场准入。"
    assert item.metadata["community_discussion_zh"] == "执行时间仍需确认。"
    assert item.metadata["category"] == "crypto-exchange"
    assert item.metadata["official"] is True
    assert item.metadata["sources"] == [
        {"title": "官方说明", "url": "https://example.com/reference"}
    ]
    assert item.ai_tags == ["Exchange", "announcement"]
    markup = render_web_feed(
        [item],
        date="2026-08-09",
        total_fetched=1,
        language="zh",
        display_timezone="Asia/Shanghai",
    )
    assert "该功能此前只面向机构用户。" in markup
    assert "变更扩大了零售用户的市场准入。" in markup
    assert "执行时间仍需确认。" in markup
    assert "官方说明" in markup
    assert "#Exchange" in markup


def test_admin_config_uses_branded_action_specific_editor() -> None:
    config = Path("docs/admin/config.yml").read_text(encoding="utf-8")

    assert "app_title: BMTNews 发布台" in config
    assert "src: /assets/images/app-icon.svg" in config
    assert "types:" in config
    assert config.count("\n              - name: editorial\n") == 1
    assert config.count("\n              - name: sponsored\n") == 1
    assert config.count("\n              - name: suppress\n") == 1
    for field in ("background_zh", "market_impact_zh", "tags", "sources"):
        assert f"name: {field}" in config
    for field in ("starts", "expires", "position", "note"):
        assert f"name: {field}" in config


def test_render_web_feed_marks_editorial_and_sponsored() -> None:
    pick = editorial_content_item(
        EditorialEntry(
            type="editorial",
            url="https://example.com/pick",
            title_zh="编辑条目 <b>",
            summary_zh="摘要",
        ),
        date(2026, 8, 9),
    )
    ad = EditorialEntry(
        type="sponsored",
        url="https://example.com/promo",
        title_zh="广告标题",
        summary_zh="广告描述",
        position=2,
    )
    markup = render_web_feed(
        [pick, make_story("one"), make_story("two")],
        date="2026-08-09",
        total_fetched=10,
        language="zh",
        display_timezone="Asia/Shanghai",
        sponsored=[ad],
    )
    assert 'class="editorial-pill"' in markup
    assert "编辑精选" in markup
    assert "编辑条目 &lt;b&gt;" in markup
    assert 'class="sponsored-slot"' in markup
    assert 'rel="noopener noreferrer sponsored"' in markup
    # The ad slot sits in the story stream but never in the ranking rail.
    rail = markup.split('<aside class="headline-rail"')[1]
    assert "sponsored-slot" not in rail
    assert "广告标题" not in rail


def test_render_web_feed_shows_at_most_one_ad() -> None:
    ads = [
        EditorialEntry(
            type="sponsored",
            url=f"https://example.com/ad{i}",
            title_zh=f"广告{i}",
        )
        for i in range(3)
    ]
    markup = render_web_feed(
        [make_story("one")],
        date="2026-08-09",
        total_fetched=5,
        language="zh",
        display_timezone="Asia/Shanghai",
        sponsored=ads,
    )
    assert markup.count('class="sponsored-slot"') == 1
