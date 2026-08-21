"""Tests for the JSON API, category feeds, and archive-derived pages."""

import json
from pathlib import Path

from src.api_output import (
    build_edition_payload,
    render_category_feed,
    write_category_feeds,
    write_edition_api,
    write_editions_index,
)
from src.archive import ArchiveRecord
from src.market_snapshot import MarketSnapshot
from src.site_pages import (
    build_entity_index_data,
    build_thread_index_data,
    publish_archive_pages,
    render_entity_page,
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
    assert "<strong>3</strong><span>entries</span>" in body



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
