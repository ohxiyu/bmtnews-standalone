"""Tests for the JSON API, category feeds, and archive-derived pages."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.api_output import (
    build_edition_payload,
    render_category_feed,
    render_sitemap,
    write_category_feeds,
    write_edition_api,
    write_editions_index,
    write_sitemap,
)
from src.archive import ArchiveRecord
from src.market_snapshot import MarketSnapshot
from src.events import (
    EventReference,
    EventSource,
    EventStatus,
    EventTimePrecision,
    EventType,
    EventUpdate,
    EventUpdateType,
    TrackedEvent,
)
from src.site_pages import (
    build_event_index_data,
    build_entity_index_data,
    build_thread_index_data,
    publish_archive_pages,
    publish_entity_pages,
    publish_event_compatibility_pages,
    write_event_api,
    render_entity_page,
    render_event_page,
    render_legacy_event_redirect,
    render_retired_thread_page,
    render_thread_page,
    write_index_data,
)
from src.threads import EntitySummary


def make_record(
    date: str = "2026-08-09",
    *,
    rank: int = 1,
    title_en: str = "A story",
    title_zh: str = "一条新闻",
    top_category: str = "crypto",
    thread_id: str | None = None,
    event_id: str | None = None,
    url: str = "https://example.com/a",
) -> ArchiveRecord:
    return ArchiveRecord(
        date=date,
        rank=rank,
        item_id=f"{date}-{rank}",
        url=url,
        title_en=title_en,
        title_zh=title_zh,
        summary_en="Summary text",
        summary_zh="摘要文本",
        score=8.5,
        top_category=top_category,
        source_type="rss",
        source_label="CoinDesk",
        tags=["bybit"],
        sources_count=2,
        thread_id=thread_id,
        thread_day=2 if thread_id else None,
        event_id=event_id,
    )


def make_event(
    event_id: str = "evt_example1",
    *,
    updates: int = 2,
    title: str = "Example event",
) -> TrackedEvent:
    start = datetime(2026, 8, 8, 8, tzinfo=timezone(timedelta(hours=8)))
    timeline = []
    for index in range(updates):
        stamp = start + timedelta(days=index)
        timeline.append(
            EventUpdate(
                update_id=f"upd_example{index + 1}",
                event_id=event_id,
                occurred_at=stamp,
                published_at=stamp,
                first_seen_at=stamp,
                time_precision=EventTimePrecision.EDITION,
                update_type=(
                    EventUpdateType.INITIAL
                    if index == 0
                    else EventUpdateType.RESOLUTION
                ),
                what_changed_zh=f"第 {index + 1} 个变化",
                what_changed_en=f"Change {index + 1}",
                current_state_zh=f"状态 {index + 1}",
                current_state_en=f"State {index + 1}",
                detailed_summary_zh=f"第 {index + 1} 个变化的详细摘要",
                detailed_summary_en=f"Detailed summary for change {index + 1}",
                background_zh="事件的中文背景" if index == 0 else "",
                background_en="Event background" if index == 0 else "",
                community_discussion_zh=(
                    "最新社区讨论" if index == updates - 1 else ""
                ),
                community_discussion_en=(
                    "Latest community discussion" if index == updates - 1 else ""
                ),
                market_impact_zh="最新市场影响" if index == updates - 1 else "",
                market_impact_en=(
                    "Latest market impact" if index == updates - 1 else ""
                ),
                importance_score=8.0 + index / 2,
                references=[
                    EventReference(
                        url=f"https://reference.example.com/{event_id}/{index}",
                        title=f"Reference {index + 1}",
                    )
                ],
                confidence=1.0,
                story_ids=[f"story-{event_id}-{index}"],
                sources=[
                    EventSource(
                        url=f"https://example.com/{event_id}/{index}",
                        label=f"Source {index + 1}",
                    )
                ],
            )
        )
    return TrackedEvent(
        event_id=event_id,
        event_type=EventType.GOVERNANCE,
        status=EventStatus.RESOLVED,
        category="crypto",
        title_zh=f"{title} 中文",
        title_en=title,
        current_state_zh=timeline[-1].current_state_zh,
        current_state_en=timeline[-1].current_state_en,
        first_seen_at=timeline[0].first_seen_at,
        last_updated_at=timeline[-1].first_seen_at,
        last_material_change_at=timeline[-1].first_seen_at,
        confidence=1.0,
        updates=timeline,
    )


def test_edition_payload_shape_and_thread_links() -> None:
    payload = build_edition_payload(
        [make_record(thread_id="tabc")],
        date="2026-08-09",
        stats={"displayed": 1},
        market=MarketSnapshot(
            btc_price=100000.0,
            btc_change_24h=1.5,
            eth_price=4000.0,
            eth_change_24h=-1.0,
            fear_greed_value=60,
            fear_greed_label="Greed",
        ),
        overviews={"zh": "导语"},
    )
    assert payload["date"] == "2026-08-09"
    assert payload["market"]["btc_usd"] == 100000.0
    assert payload["overview"]["zh"] == "导语"
    item = payload["items"][0]
    assert item["title"]["zh"] == "一条新闻"
    assert item["sources_count"] == 2
    assert item["thread"]["url"].endswith("/threads/tabc/")


def test_edition_payload_links_exact_event_update() -> None:
    record = make_record().model_copy(
        update={
            "event_id": "evt_example1",
            "event_update_id": "upd_example1",
        }
    )
    payload = build_edition_payload(
        [record], date="2026-08-09", stats={"displayed": 1}
    )

    event = payload["items"][0]["event"]
    assert event["event_id"] == "evt_example1"
    assert event["update_id"] == "upd_example1"
    assert event["url"].endswith("/events/evt_example1/#upd_example1")
    assert event["json"].endswith("/api/events/evt_example1.json")


def test_write_edition_api_writes_dated_and_latest(tmp_path: Path) -> None:
    payload = build_edition_payload(
        [make_record()], date="2026-08-09", stats={"displayed": 1}
    )
    editions_root = tmp_path / "editions"
    api_root = tmp_path / "api"
    write_edition_api(
        payload, date="2026-08-09", editions_root=editions_root, api_root=api_root
    )
    dated = json.loads(
        (editions_root / "2026-08-09" / "edition.json").read_text(encoding="utf-8")
    )
    latest = json.loads((api_root / "latest.json").read_text(encoding="utf-8"))
    assert dated == latest
    assert dated["items"][0]["url"] == "https://example.com/a"


def test_write_editions_index_lists_dates_desc(tmp_path: Path) -> None:
    records = [
        make_record("2026-08-08", url="https://example.com/1"),
        make_record("2026-08-09", url="https://example.com/2"),
        make_record("2026-08-09", rank=2, url="https://example.com/3"),
    ]
    path = write_editions_index(records, api_root=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [entry["date"] for entry in payload["editions"]] == [
        "2026-08-09",
        "2026-08-08",
    ]
    assert payload["editions"][0]["items"] == 2


def test_sitemap_lists_static_editions_threads_and_entities(tmp_path: Path) -> None:
    records = [
        make_record("2026-08-23", thread_id="tabc"),
        make_record("2026-08-24", rank=2, thread_id="tabc"),
    ]
    entity = EntitySummary(slug="cftc", label="CFTC", count=2, records=records)
    sitemap = render_sitemap(
        records,
        threads=[("tabc", records)],
        entities=[entity],
        generated_date="2026-08-24",
    )
    assert sitemap.startswith('<?xml version="1.0" encoding="UTF-8"?>')
    assert "https://bmt.news/developers/" in sitemap
    assert "https://bmt.news/editions/2026-08-24/zh.html" in sitemap
    assert "https://bmt.news/en/threads/tabc/" in sitemap
    assert "https://bmt.news/entity/cftc/" in sitemap
    assert "<lastmod>2026-08-24</lastmod>" in sitemap

    path = write_sitemap(
        records,
        threads=[("tabc", records)],
        entities=[entity],
        path=tmp_path / "sitemap.xml",
    )
    assert path.read_text(encoding="utf-8") == sitemap


def test_category_feed_filters_and_escapes() -> None:
    records = [
        make_record(title_en="Crypto <story>", top_category="crypto"),
        make_record(rank=2, title_en="Tech story", top_category="technology"),
    ]
    feed = render_category_feed(records, category="crypto", language="en")
    assert "Crypto &lt;story&gt;" in feed
    assert "Tech story" not in feed
    assert "<feed xmlns=" in feed


def test_write_category_feeds_covers_languages(tmp_path: Path) -> None:
    written = write_category_feeds(
        [make_record()], ["zh", "en"], feeds_root=tmp_path
    )
    names = sorted(path.name for path in written)
    assert "crypto-zh.xml" in names
    assert "policy-en.xml" in names
    assert len(names) == 6


def test_thread_page_has_front_matter_and_timeline() -> None:
    records = [
        make_record("2026-08-08", title_zh="第一天"),
        make_record("2026-08-09", title_zh="第二天"),
    ]
    page = render_thread_page("tabc", records, "zh")
    assert page.startswith("---\n")
    assert "permalink: /threads/tabc/" in page
    assert "第二天" in page and "第一天" in page
    # The stat header answers "how long has this been running" up front.
    assert "<strong>2</strong><span>天</span>" in page
    assert "<strong>2026-08-09</strong><span>最近报道</span>" in page


def test_entity_page_escapes_labels_and_keeps_titles_plain() -> None:
    entity = EntitySummary(
        slug="bybit",
        label="Bybit <b>",
        count=3,
        records=[make_record(title_en="Bybit <script> halts")],
    )
    page = render_entity_page(entity, "en")
    front_matter, body = page.split("---\n\n", 1)
    assert "permalink: /en/entity/bybit/" in front_matter
    # Front matter feeds the raw <title>; markup characters are removed.
    assert "<" not in front_matter.split("title:")[1].split("\n")[0]
    # The body escapes rather than strips.
    assert "Bybit &lt;script&gt; halts" in body
    assert 'page_class: entity-detail-page' in front_matter
    assert "Entity overview" in body
    assert "Recent developments" in body
    assert "<dt>Coverage</dt><dd>3</dd>" in body
    assert "BMTNews has tracked 3 related reports" in body


def test_entity_page_links_reports_to_related_event_timelines() -> None:
    entity = EntitySummary(
        slug="bybit",
        label="Bybit",
        count=2,
        records=[
            make_record("2026-08-08", title_zh="事件出现", event_id="evt_bybit"),
            make_record("2026-08-09", title_zh="事件进展", event_id="evt_bybit"),
        ],
    )
    page = render_entity_page(entity, "zh")

    assert 'class="event-detail-layout entity-detail-layout"' in page
    assert "实体概览" in page
    assert "近期进展" in page
    assert "关联事件线" in page
    assert page.count('href="/events/evt_bybit/"') == 3


def test_entity_page_separates_background_from_current_focus() -> None:
    entity = EntitySummary(
        slug="coinbase",
        label="Coinbase",
        count=3,
        records=[make_record(title_zh="Coinbase 发布最新产品")],
    )

    page = render_entity_page(entity, "zh")

    assert "实体背景" in page
    assert "当前关注" in page
    assert "美国加密资产平台" in page
    assert "提供交易、托管、质押与链上基础设施" in page
    assert "<dt>实体类型</dt><dd>加密货币交易所</dd>" in page
    assert 'href="https://www.coinbase.com/about"' in page
    assert 'href="https://www.coinbase.com/blog"' in page


def test_entity_page_marks_unknown_background_as_pending() -> None:
    entity = EntitySummary(
        slug="unreviewed-name",
        label="Unreviewed Name",
        count=3,
        records=[make_record()],
    )

    page = render_entity_page(entity, "zh")

    assert "背景资料整理中" in page
    assert "官方网站" not in page
    assert "官方动态" not in page



def test_index_data_feeds_the_committed_pages(tmp_path) -> None:
    threads = [
        (
            "tabc",
            [
                make_record("2026-08-08", thread_id="tabc"),
                make_record("2026-08-09", thread_id="tabc"),
            ],
        )
    ]
    entities = [
        EntitySummary(slug="bybit", label="Bybit", count=3, records=[make_record()])
    ]
    thread_data = build_thread_index_data(threads)
    assert thread_data["threads"][0]["days"] == 2
    assert thread_data["threads"][0]["latest_date"] == "2026-08-09"
    assert thread_data["threads"][0]["first_date"] == "2026-08-08"
    assert build_entity_index_data(entities)["entities"][0]["mentions"] == 3


def test_entity_index_carries_what_a_reader_needs_to_choose() -> None:
    """A name and a count is a tag cloud; these fields make it scannable."""
    entities = [
        EntitySummary(
            slug="bybit",
            label="Bybit",
            count=2,
            records=[
                make_record("2026-08-08", title_zh="第一天", top_category="crypto"),
                make_record("2026-08-11", title_zh="最新一条", top_category="crypto"),
            ],
        )
    ]
    row = build_entity_index_data(entities)["entities"][0]
    assert row["latest_date"] == "2026-08-11"
    assert row["first_date"] == "2026-08-08"
    assert row["days"] == 2
    assert row["title_zh"] == "最新一条"
    assert row["category"] == "crypto"
    assert row["summary_zh"] == "摘要文本"
    assert len(row["recent_items"]) == 2
    assert row["recent_items"][0]["date"] == "2026-08-11"
    assert row["events_count"] == 0


def test_entity_index_includes_stable_identity_without_reusing_news_summary() -> None:
    entity = EntitySummary(
        slug="coinbase",
        label="Coinbase",
        count=3,
        records=[make_record()],
    )

    row = build_entity_index_data([entity])["entities"][0]

    assert row["profile_status"] == "verified"
    assert row["entity_type_zh"] == "加密货币交易所"
    assert row["identity_zh"] == "提供交易、托管、质押与链上基础设施的美国加密平台。"
    assert row["identity_zh"] != row["summary_zh"]


def test_entity_index_puts_still_active_names_first() -> None:
    stale = EntitySummary(
        slug="stale",
        label="Stale",
        count=5,
        records=[make_record("2026-07-01") for _ in range(5)],
    )
    active = EntitySummary(
        slug="active",
        label="Active",
        count=2,
        records=[make_record("2026-08-10"), make_record("2026-08-11")],
    )
    rows = build_entity_index_data([stale, active])["entities"]
    assert [row["slug"] for row in rows] == ["active", "stale"]
    assert rows[0]["recent"] == 2
    assert rows[1]["recent"] == 0


def test_write_index_data_writes_both_data_files(tmp_path) -> None:
    threads = [
        (
            "tabc",
            [
                make_record("2026-08-08", thread_id="tabc"),
                make_record("2026-08-09", thread_id="tabc"),
            ],
        )
    ]
    entities = [
        EntitySummary(slug="bybit", label="Bybit", count=3, records=[make_record()])
    ]
    written = write_index_data(threads, entities, data_root=tmp_path)
    assert sorted(path.name for path in written) == [
        "entities.json",
        "threads.json",
    ]
    payload = json.loads((tmp_path / "threads.json").read_text(encoding="utf-8"))
    assert payload["threads"][0]["thread_id"] == "tabc"


def test_publish_archive_pages_writes_both_languages(tmp_path: Path) -> None:
    threads = [("tabc", [make_record(thread_id="tabc")])]
    entities = [EntitySummary(slug="bybit", label="Bybit", count=3, records=[make_record()])]
    counts = publish_archive_pages(
        threads,
        entities,
        ["zh", "en"],
        threads_root=tmp_path / "threads",
        entity_root=tmp_path / "entity",
        data_root=tmp_path / "_data",
    )
    assert counts == {"threads": 2, "entities": 2}
    assert (tmp_path / "threads" / "tabc.html").exists()
    assert (tmp_path / "threads" / "en-tabc.html").exists()
    assert (tmp_path / "entity" / "en-bybit.html").exists()
    assert (tmp_path / "_data" / "threads.json").exists()


def test_publish_entity_pages_does_not_replace_thread_index(tmp_path: Path) -> None:
    data_root = tmp_path / "_data"
    data_root.mkdir()
    thread_index = data_root / "threads.json"
    thread_index.write_text('{"threads":[{"thread_id":"keep"}]}\n', encoding="utf-8")
    entities = [
        EntitySummary(slug="bybit", label="Bybit", count=3, records=[make_record()])
    ]

    pages = publish_entity_pages(
        entities,
        ["zh", "en"],
        entity_root=tmp_path / "entity",
        data_root=data_root,
    )

    assert pages == 2
    assert json.loads(thread_index.read_text(encoding="utf-8"))["threads"][0][
        "thread_id"
    ] == "keep"
    assert json.loads((data_root / "entities.json").read_text(encoding="utf-8"))[
        "entities"
    ][0]["label"] == "Bybit"
    assert (tmp_path / "entity" / "bybit.html").exists()
    assert (tmp_path / "entity" / "en-bybit.html").exists()


def test_event_page_renders_material_updates_in_chronological_order() -> None:
    event = make_event()
    page = render_event_page(event, "zh")

    assert "permalink: /events/evt_example1/" in page
    assert "time_precision" not in page
    assert "历史刊期" in page
    assert page.index("第 1 个变化") < page.index("第 2 个变化")
    assert "https://example.com/evt_example1/0" in page
    assert "目前结论" in page
    assert 'id="upd_example1"' in page
    assert "/api/events/evt_example1.json" in page
    assert "alternate_url: /en/events/evt_example1/" in page
    assert "page_class: event-detail-page" in page
    assert 'class="event-detail-layout"' in page
    assert 'class="headline-rail event-detail-rail"' in page
    assert "#01" in page and "#02" in page
    assert "治理事件" in page
    # When the update title falls back to what_changed, do not print the same
    # sentence twice in the main timeline body.
    assert 'class="event-update-change"' not in page


def test_event_api_writes_index_and_full_timeline(tmp_path: Path) -> None:
    singleton = make_event("evt_single001", updates=1)
    progression = make_event("evt_progress1", updates=2)
    paths = write_event_api(
        [singleton, progression],
        api_root=tmp_path / "api" / "events",
        index_path=tmp_path / "api" / "events.json",
    )

    index = json.loads((tmp_path / "api" / "events.json").read_text())
    detail = json.loads(
        (tmp_path / "api" / "events" / "evt_progress1.json").read_text()
    )
    assert len(paths) == 3
    assert [row["event_id"] for row in index["events"]] == ["evt_progress1"]
    assert detail["event_id"] == "evt_progress1"
    assert len(detail["updates"]) == 2


def test_legacy_redirect_has_noindex_canonical_target() -> None:
    page = render_legacy_event_redirect("taaaaaaaaaa", make_event(), "en")

    assert "permalink: /en/threads/taaaaaaaaaa/" in page
    assert "redirect_to: /en/events/evt_example1/" in page
    assert "noindex: true" in page
    assert 'href="/en/events/evt_example1/"' in page


def test_retired_thread_lists_every_corrected_target() -> None:
    first = make_event("evt_example1", title="First")
    second = make_event("evt_example2", title="Second")
    page = render_retired_thread_page(
        "tbbbbbbbbbb", [first, second], "zh"
    )

    assert "permalink: /threads/tbbbbbbbbbb/" in page
    assert "/events/evt_example1/" in page
    assert "/events/evt_example2/" in page
    assert "现已拆分" in page


def test_event_index_contains_progressions_not_single_updates() -> None:
    progression = make_event("evt_progress1", updates=2)
    duplicate_only = make_event("evt_duplicate1", updates=1)

    payload = build_event_index_data([duplicate_only, progression])
    rows = payload["threads"]

    assert [row["event_id"] for row in rows] == ["evt_progress1"]
    assert rows[0]["entries"] == 2
    assert rows[0]["days"] == 2
    assert rows[0]["latest_update_zh"] == "第 2 个变化"
    assert rows[0]["latest_update_en"] == "Change 2"
    assert rows[0]["event_type_zh"] == "治理事件"
    assert rows[0]["background_zh"] == "事件的中文背景"
    assert rows[0]["latest_summary_zh"] == "第 2 个变化的详细摘要"
    assert rows[0]["discussion_zh"] == "最新社区讨论"
    assert rows[0]["market_impact_zh"] == "最新市场影响"
    assert rows[0]["score"] == 8.5
    assert len(rows[0]["source_links"]) == 2
    assert len(rows[0]["reference_links"]) == 2
    assert [row["event_id"] for row in payload["ranking"]] == ["evt_progress1"]


def test_event_ranking_prioritizes_importance_before_recency() -> None:
    higher_score = make_event("evt_higher01", updates=2)
    newer = make_event("evt_newer001", updates=2)
    higher_score.updates[-1].importance_score = 9.5
    for update in newer.updates:
        update.occurred_at += timedelta(days=10)
        update.published_at += timedelta(days=10)
        update.first_seen_at += timedelta(days=10)
    newer.last_updated_at += timedelta(days=10)
    newer.last_material_change_at += timedelta(days=10)

    payload = build_event_index_data([newer, higher_score])

    assert [row["event_id"] for row in payload["threads"]] == [
        "evt_newer001",
        "evt_higher01",
    ]
    assert [row["event_id"] for row in payload["ranking"]] == [
        "evt_higher01",
        "evt_newer001",
    ]


def test_event_index_uses_local_material_timestamp_not_late_discovery() -> None:
    from zoneinfo import ZoneInfo

    event = make_event("evt_local001", updates=2)
    event.last_material_change_at = datetime(2026, 9, 4, 18, tzinfo=timezone.utc)
    event.updates[0].first_seen_at = datetime(2026, 9, 9, tzinfo=timezone.utc)
    row = build_event_index_data([event])["threads"][0]
    assert row["latest_date"] == "2026-09-05"
    assert row["latest_at"] == event.last_material_change_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()


def test_context_is_recent_and_latest_precedes_background() -> None:
    template = Path("docs/_includes/archive-index.html").read_text()
    context = template.split('<div class="event-index-layout">')[0]
    assert "for row in rows limit: 3" in context
    assert "for row in ranking limit: 3" not in context
    assert template.index('event-brief-latest') < template.index('event-brief-background')
    for section in ("threads", "entity"):
        assert f"alternate_url: /en/{section}/" in Path(f"docs/{section}.html").read_text()
        assert f"alternate_url: /{section}/" in Path(f"docs/en/{section}.html").read_text()


def test_weekly_fallback_does_not_repeat_leading_story_as_judgment() -> None:
    template = Path("docs/_includes/weekly-edition.html").read_text()
    assert "unless edition.throughline.title == edition.items.first.title" in template


def test_event_index_template_reuses_feed_layout_and_filters() -> None:
    template = (
        Path("docs/_includes/archive-index.html").read_text(encoding="utf-8")
    )
    layout = Path("docs/_layouts/default.html").read_text(encoding="utf-8")

    assert 'class="event-index-layout"' in template
    assert 'class="digest-item event-feed-item"' in template
    assert "data-event-filters" in template
    assert 'class="headline-rail event-overview-rail"' in template
    assert 'class="event-context"' in template
    assert 'class="event-brief-grid"' in template
    assert 'class="headline-index event-ranking"' in template
    assert "事件背景" in template
    assert "最新进展" in template
    assert "讨论焦点" in template
    assert "参考资料" in template
    assert 'class="event-feed-summary"' not in template
    assert "当前状态" not in template
    assert "page.page_class" in layout


def test_event_index_styles_match_the_daily_feed_without_docs_heading_leaks() -> None:
    stylesheet = Path("docs/assets/css/bmtnews-ui.css").read_text(encoding="utf-8")
    event_layout = stylesheet.split(".event-index-layout {", 1)[1].split("}", 1)[0]
    latest_update = stylesheet.split(".event-brief-latest p {", 1)[1].split(
        "}", 1
    )[0]

    assert (
        ".docs-page:not(.event-index-page):not(.event-detail-page)"
        ":not(.entity-index-page):not(.entity-detail-page)"
        ":not(.weekly-index-page):not(.weekly-detail-page) "
        ".main-content h2"
    ) in stylesheet
    assert "grid-template-columns: minmax(0, 1fr) 264px;" in event_layout
    assert "gap: 0 32px;" in event_layout
    assert "font-size: var(--fs-m);" in latest_update


def test_secondary_layout_keeps_content_first_and_separates_bilingual_copy() -> None:
    stylesheet = Path("docs/assets/css/bmtnews-ui.css").read_text(encoding="utf-8")
    tablet_rules = stylesheet.split("@media (max-width: 1100px)", 1)[1].split(
        "@media (max-width: 760px)", 1
    )[0]
    about = Path("docs/about/index.md").read_text(encoding="utf-8")
    contact = Path("docs/contact/index.md").read_text(encoding="utf-8")

    assert 'grid-template-areas:\n      "stream"\n      "rail";' in tablet_rules
    assert ".main-content > h2:first-child" in stylesheet
    assert "\n## English\n" in about
    assert "\n## English\n" in contact


def test_publish_event_compatibility_pages_writes_real_redirect_targets(
    tmp_path: Path,
) -> None:
    progression = make_event("evt_progress1", updates=2)
    split_first = make_event("evt_split0001", updates=1, title="Split first")
    split_second = make_event("evt_split0002", updates=1, title="Split second")
    counts = publish_event_compatibility_pages(
        [progression, split_first, split_second],
        {"taaaaaaaaaa": "evt_progress1"},
        {"tbbbbbbbbbb": ["evt_split0001", "evt_split0002"]},
        ["zh", "en"],
        events_root=tmp_path / "events",
        threads_root=tmp_path / "threads",
        thread_index_path=tmp_path / "_data" / "threads.json",
    )

    assert counts == {"events": 6, "redirects": 2, "retired": 2}
    assert (tmp_path / "events" / "evt_progress1.html").exists()
    assert (tmp_path / "events" / "en-evt_progress1.html").exists()
    redirect = (tmp_path / "threads" / "taaaaaaaaaa.html").read_text()
    assert "redirect_to: /events/evt_progress1/" in redirect
    retired = (tmp_path / "threads" / "en-tbbbbbbbbbb.html").read_text()
    assert "/en/events/evt_split0001/" in retired
    index = json.loads((tmp_path / "_data" / "threads.json").read_text())
    assert [row["event_id"] for row in index["threads"]] == ["evt_progress1"]
