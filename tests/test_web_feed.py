"""Tests for static-first public feed rendering."""

from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from src.models import ContentItem, SourceType
from src.web_feed import render_web_feed


def make_item(
    item_id: str,
    category: str,
    *,
    score: float = 8.0,
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Title {item_id}",
        url=f"https://example.com/{item_id}",
        author="publisher",
        published_at=datetime(2026, 7, 30, 16, 30, tzinfo=timezone.utc),
        metadata={
            "category": category,
            "feed_name": "Example Feed",
            "detailed_summary_zh": f"摘要 {item_id}",
            "detailed_summary_en": f"Summary {item_id}",
        },
        ai_score=score,
        ai_summary=f"Fallback {item_id}",
        ai_tags=["News"],
    )


def test_render_web_feed_outputs_final_cards_and_top_level_filters() -> None:
    items = [
        make_item("market", "crypto-markets", score=9.4),
        make_item("ai", "ai-labs", score=8.8),
        make_item("policy", "macro-regulation", score=8.4),
        make_item("protocol", "crypto-protocols", score=8.0),
    ]

    markup = render_web_feed(
        items,
        date="2026-07-31",
        total_fetched=42,
        language="zh",
        display_timezone="Asia/Shanghai",
    )
    page = BeautifulSoup(markup, "html.parser")

    assert page.select_one(".feed-rendered-static[data-feed-render-version='2']")
    assert len(page.select(".digest-item")) == 4
    assert len(page.select(".digest-item.is-priority")) == 3
    assert [
        button["data-category"]
        for button in page.select("[data-static-filters] button")
    ] == ["all", "crypto", "technology", "policy"]
    assert [
        article["data-category"]
        for article in page.select(".digest-item")
    ] == ["crypto", "technology", "policy", "crypto"]
    assert page.select_one("#zh-2026-07-31-item-1")
    assert "7月31日 00:30" in page.select_one(".source-line").get_text(" ", strip=True)
    assert "本期从 42 条候选中展示 4 条" in markup
    assert len(page.select('.story-share-button[data-story-share="x"]')) == 4
    assert len(page.select('.story-share-button[data-story-share="card"]')) == 4
    controls = page.select_one(".digest-item-controls")
    assert controls.select_one(".score-badge")
    assert [
        button["data-story-share"]
        for button in controls.select(".story-share-button")
    ] == ["x", "card"]
    assert controls.select_one('[data-story-share="x"]')["aria-label"] == "分享到 X"
    assert controls.select_one('[data-story-share="card"]')["aria-label"] == "生成分享卡片"


def test_render_web_feed_escapes_text_and_rejects_unsafe_references() -> None:
    item = make_item("unsafe", "crypto-markets")
    item.title = '<script>alert("title")</script>'
    item.metadata.update(
        {
            "detailed_summary_en": '<img src=x onerror="alert(1)">',
            "background_en": '<iframe src="bad"></iframe>',
            "sources": [
                {
                    "title": '<svg onload="alert(1)">',
                    "url": "javascript:alert(1)",
                }
            ],
        }
    )

    markup = render_web_feed(
        [item],
        date="2026-07-31",
        total_fetched=1,
        language="en",
        display_timezone="UTC",
    )

    assert "<script>" not in markup
    assert "<img src=x" not in markup
    assert "<iframe" not in markup
    assert "<svg onload" not in markup
    assert 'href="javascript:' not in markup
    assert "&lt;script&gt;" in markup
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in markup


def test_story_share_controls_are_localized_in_english() -> None:
    markup = render_web_feed(
        [make_item("english", "ai-labs")],
        date="2026-07-31",
        total_fetched=1,
        language="en",
        display_timezone="UTC",
    )
    page = BeautifulSoup(markup, "html.parser")

    assert page.select_one('[data-story-share="x"]')["aria-label"] == "Share to X"
    assert (
        page.select_one('[data-story-share="card"]')["aria-label"]
        == "Generate share card"
    )


def test_render_web_feed_empty_state_is_static() -> None:
    markup = render_web_feed(
        [],
        date="2026-07-31",
        total_fetched=0,
        language="zh",
        display_timezone="Asia/Shanghai",
    )

    assert "feed-rendered-static" in markup
    assert "今日暂无达到展示阈值的重要资讯" in markup
    assert "digest-item" not in markup


def test_story_summaries_are_not_visually_truncated() -> None:
    root = Path(__file__).parents[1]
    stylesheet = (root / "docs" / "assets" / "css" / "bmtnews.css").read_text(
        encoding="utf-8"
    )

    assert ".story-summary-body:not(.expanded)" not in stylesheet


def test_story_card_renderer_is_loaded_only_after_a_card_click() -> None:
    root = Path(__file__).parents[1]
    main_script = (root / "docs" / "assets" / "js" / "bmtnews.js").read_text(
        encoding="utf-8"
    )
    card_script = root / "docs" / "assets" / "js" / "story-card.js"
    head = (root / "docs" / "_includes" / "head-custom.html").read_text(
        encoding="utf-8"
    )

    assert card_script.is_file()
    assert "import(storyCardModuleUrl())" in main_script
    assert "story-card.js" not in head


def test_story_card_matches_the_full_story_layout_without_a_page_url() -> None:
    root = Path(__file__).parents[1]
    main_script = (root / "docs" / "assets" / "js" / "bmtnews.js").read_text(
        encoding="utf-8"
    )
    card_script = (
        root / "docs" / "assets" / "js" / "story-card.js"
    ).read_text(encoding="utf-8")

    assert "PUBLIC_SITE_ORIGIN = 'https://bmt.news'" in main_script
    assert "references: references" in main_script
    assert "sourceParts:" in main_script
    assert "dateLabel:" in main_script
    assert "CARD_SCALE = 2" in card_script
    assert "context.fillText('bmt.news'" in card_script
    assert "context.fillText(story.rank" not in card_script
    assert "story.references" in card_script
    assert "story.tags" in card_script
    assert "story.url" not in card_script


def test_home_templates_keep_two_editions_and_split_languages() -> None:
    root = Path(__file__).parents[1]
    include = (root / "docs" / "_includes" / "feed-home.html").read_text(
        encoding="utf-8"
    )
    zh_home = (root / "docs" / "index.md").read_text(encoding="utf-8")
    en_home = (root / "docs" / "en" / "index.md").read_text(encoding="utf-8")
    layout = (root / "docs" / "_layouts" / "default.html").read_text(
        encoding="utf-8"
    )

    assert "for post in feed_posts limit:2" in include
    assert "data-today-edition-status" in include
    assert "Asia/Shanghai" in include
    assert "今日版准备中" in include
    assert "今日版延迟，正在恢复" in include
    assert "08:30" in include
    assert "post.fragment_url | default: post.url" in include
    assert 'feed-home.html language="zh"' in zh_home
    assert 'feed-home.html language="en"' in en_home
    assert "permalink: /en/" in en_home
    assert "zh_language_url" in layout
    assert "en_language_url" in layout
