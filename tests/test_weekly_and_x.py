"""Tests for the weekly review and the opt-in X distribution."""

import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.archive import ArchiveRecord
from src.models import ContentItem, SourceType, XDeliveryConfig
from src.services.x_delivery import (
    TWEET_LIMIT,
    XDeliveryStatus,
    XEditionPublisher,
    _oauth_header,
    _weighted_length,
    build_post,
)
from src.weekly import (
    build_weeks_index_data,
    build_weekly_context,
    generate_weekly_digest,
    render_weekly_page,
    save_weekly_page,
    save_weeks_index_data,
)


def make_record(date_str: str, *, rank: int = 1, score: float = 8.0) -> ArchiveRecord:
    return ArchiveRecord(
        date=date_str,
        rank=rank,
        item_id=f"{date_str}-{rank}",
        url=f"https://example.com/{date_str}-{rank}",
        title_zh=f"标题 {date_str}",
        title_en=f"Story {date_str}",
        summary_zh="摘要",
        summary_en="Summary",
        score=score,
        thread_id="tabc" if rank == 1 else None,
    )


class StubClient:
    def __init__(self, response: str = "## 本周主线\n\n内容") -> None:
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


def test_build_weekly_context_windows_records() -> None:
    records = [
        make_record("2026-08-01"),
        make_record("2026-08-05"),
        make_record("2026-08-09"),
    ]
    context = build_weekly_context(records, end=date(2026, 8, 9), days=7)
    assert context.start == date(2026, 8, 3)
    assert [record.date for record in context.records] == [
        "2026-08-05",
        "2026-08-09",
    ]
    assert context.stats["days"] == 2


async def _test_generate_weekly_digest_returns_body() -> None:
    context = build_weekly_context([make_record("2026-08-09")], end=date(2026, 8, 9))
    client = StubClient()
    body = await generate_weekly_digest(client, context, language="zh")
    assert body == "## 本周主线\n\n内容"
    assert "Simplified Chinese" in client.calls[0]["user"]


async def _test_weekly_digest_asks_for_prose_not_json() -> None:
    """A JSON-mode request is rejected outright by providers that offer one."""
    context = build_weekly_context([make_record("2026-08-09")], end=date(2026, 8, 9))
    client = StubClient()
    await generate_weekly_digest(client, context, language="zh")
    assert client.calls[0]["response_format"] == "text"


async def _test_generate_weekly_digest_surfaces_provider_errors() -> None:
    """Swallowing these is what hid a 400 for two weeks; the caller reports."""
    context = build_weekly_context([make_record("2026-08-09")], end=date(2026, 8, 9))
    client = StubClient(response=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await generate_weekly_digest(client, context, language="zh")

    # Nothing to write about is still a quiet None, not an error.
    empty = build_weekly_context([], end=date(2026, 8, 9))
    assert await generate_weekly_digest(StubClient(), empty, language="zh") is None


def test_render_and_save_weekly_page(tmp_path: Path) -> None:
    context = build_weekly_context([make_record("2026-08-09")], end=date(2026, 8, 9))
    page = render_weekly_page("## 本周主线\n\n内容", context, language="zh")
    assert "permalink: /weekly/2026-08-09/" in page
    assert "1 条" in page or "发布 1" in page
    path = save_weekly_page(page, end=date(2026, 8, 9), language="zh", root=tmp_path)
    assert path.name == "2026-08-09.md"

    data = build_weeks_index_data(["2026-08-02", "2026-08-09", "2026-08-02"])
    assert data["weeks"] == ["2026-08-09", "2026-08-02"]
    assert save_weeks_index_data(["2026-08-09"], data_root=tmp_path).name == "weeks.json"


def make_item(title: str) -> ContentItem:
    return ContentItem(
        id=title,
        source_type=SourceType.RSS,
        title=title,
        url=f"https://example.com/{abs(hash(title))}",
        published_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        ai_score=8.0,
        metadata={"title_zh": title},
    )


def test_build_post_fits_the_character_limit() -> None:
    items = [make_item("很长的标题 " * 20) for _ in range(3)]
    text = build_post(
        items,
        date="2026-08-09",
        language="zh",
        site_url="https://bmt.news/",
    )
    assert _weighted_length(text) <= TWEET_LIMIT
    assert "https://bmt.news/" in text
    assert text.startswith("BMTNews 2026-08-09")


def test_build_post_respects_max_items() -> None:
    items = [make_item(f"标题{i}") for i in range(5)]
    text = build_post(
        items,
        date="2026-08-09",
        language="zh",
        site_url="https://bmt.news/",
        max_items=2,
    )
    assert "1. 标题0" in text
    assert "3. " not in text


def test_oauth_header_is_deterministic_and_signed() -> None:
    header = _oauth_header(
        "POST",
        "https://api.x.com/2/tweets",
        consumer_key="ck",
        consumer_secret="cs",
        access_token="at",
        access_secret="as",
        nonce="fixednonce",
        timestamp="1700000000",
    )
    again = _oauth_header(
        "POST",
        "https://api.x.com/2/tweets",
        consumer_key="ck",
        consumer_secret="cs",
        access_token="at",
        access_secret="as",
        nonce="fixednonce",
        timestamp="1700000000",
    )
    assert header == again
    assert header.startswith("OAuth ")
    assert 'oauth_signature_method="HMAC-SHA1"' in header
    assert "cs" not in header  # the secret is never echoed


async def _test_x_publisher_skips_without_credentials(monkeypatch) -> None:
    for name in (
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    publisher = XEditionPublisher(XDeliveryConfig(enabled=True))
    result = await publisher.send_daily_edition(
        [make_item("标题")], date="2026-08-09", language="zh"
    )
    assert result.status == XDeliveryStatus.SKIPPED
    assert result.posted == 0


async def _test_x_publisher_skips_when_disabled() -> None:
    publisher = XEditionPublisher(XDeliveryConfig())
    result = await publisher.send_daily_edition(
        [make_item("标题")], date="2026-08-09", language="zh"
    )
    assert result.status == XDeliveryStatus.SKIPPED


async def _test_x_publisher_posts_with_credentials(monkeypatch) -> None:
    import httpx

    sent: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        sent["auth"] = request.headers.get("Authorization", "")
        sent["body"] = request.content.decode("utf-8")
        return httpx.Response(201, json={"data": {"id": "1"}})

    for name, value in (
        ("X_CONSUMER_KEY", "ck"),
        ("X_CONSUMER_SECRET", "cs"),
        ("X_ACCESS_TOKEN", "at"),
        ("X_ACCESS_SECRET", "as"),
    ):
        monkeypatch.setenv(name, value)

    publisher = XEditionPublisher(
        XDeliveryConfig(enabled=True),
        transport=httpx.MockTransport(handler),
    )
    result = await publisher.send_daily_edition(
        [make_item("重要新闻")], date="2026-08-09", language="zh"
    )
    assert result.status == XDeliveryStatus.SUCCESS
    assert result.posted == 1
    assert sent["auth"].startswith("OAuth ")
    assert "重要新闻" in sent["body"]


async def _test_x_publisher_reports_api_failure(monkeypatch) -> None:
    import httpx

    for name, value in (
        ("X_CONSUMER_KEY", "ck"),
        ("X_CONSUMER_SECRET", "cs"),
        ("X_ACCESS_TOKEN", "at"),
        ("X_ACCESS_SECRET", "as"),
    ):
        monkeypatch.setenv(name, value)

    publisher = XEditionPublisher(
        XDeliveryConfig(enabled=True),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(403, json={"detail": "secret detail"})
        ),
    )
    result = await publisher.send_daily_edition(
        [make_item("标题")], date="2026-08-09", language="zh"
    )
    assert result.status == XDeliveryStatus.FAILURE
    assert "403" in result.detail
    assert "secret detail" not in result.detail


def test_generate_weekly_digest_returns_body() -> None:
    asyncio.run(_test_generate_weekly_digest_returns_body())


def test_generate_weekly_digest_surfaces_provider_errors() -> None:
    asyncio.run(_test_generate_weekly_digest_surfaces_provider_errors())


def test_weekly_digest_asks_for_prose_not_json() -> None:
    asyncio.run(_test_weekly_digest_asks_for_prose_not_json())


def test_x_publisher_skips_without_credentials(monkeypatch) -> None:
    asyncio.run(_test_x_publisher_skips_without_credentials(monkeypatch))


def test_x_publisher_skips_when_disabled() -> None:
    asyncio.run(_test_x_publisher_skips_when_disabled())


def test_x_publisher_posts_with_credentials(monkeypatch) -> None:
    asyncio.run(_test_x_publisher_posts_with_credentials(monkeypatch))


def test_x_publisher_reports_api_failure(monkeypatch) -> None:
    asyncio.run(_test_x_publisher_reports_api_failure(monkeypatch))


async def _test_x_delivery_skips_languages_already_posted() -> None:
    """Republishing an edition must not post to X twice."""
    from types import SimpleNamespace
    from rich.console import Console
    from src.orchestrator import BMTNewsOrchestrator
    from src.run_report import RunReport

    class RecordingPublisher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def send_daily_edition(self, items, *, date, language):
            self.calls.append(language)
            from src.services.x_delivery import XDeliveryResult

            return XDeliveryResult(status=XDeliveryStatus.SUCCESS, posted=1)

    orchestrator = BMTNewsOrchestrator.__new__(BMTNewsOrchestrator)
    orchestrator.console = Console(record=True)
    orchestrator.config = SimpleNamespace(
        x_delivery=XDeliveryConfig(enabled=True, languages=["zh", "en"])
    )
    publisher = RecordingPublisher()
    orchestrator.x_publisher = publisher

    report = RunReport.start(date="2026-08-09", timezone_name="Asia/Shanghai")
    posted: list[str] = []
    await orchestrator._deliver_x_editions(
        [make_item("标题")],
        date="2026-08-09",
        run_report=report,
        already_posted=["zh"],
        on_posted=posted.append,
    )
    assert publisher.calls == ["en"]
    assert posted == ["en"]
    assert any(
        alert.code == "x_delivery_already_posted" for alert in report.alerts
    )


def test_x_delivery_skips_languages_already_posted() -> None:
    asyncio.run(_test_x_delivery_skips_languages_already_posted())


def test_prose_prompts_never_request_json_mode() -> None:
    """The defect that broke the weekly review, the lede, and X composition.

    A provider JSON mode fails two ways on a prose prompt: it is rejected
    outright when the prompt never says "json" (weekly review, calibration,
    X posts), and when the prompt happens to contain the word it succeeds and
    wraps the prose in JSON that then reaches the page (the edition lede).
    Neither is visible from the prompt text, so it is asserted here.
    """
    import inspect
    import re

    from src.ai import prompts as prompt_module

    prose_prompts = (
        "WEEKLY_DIGEST",
        "SCORE_CALIBRATION",
        "X_POST",
        "EDITION_OVERVIEW",
    )
    sources = {
        "WEEKLY_DIGEST": inspect.getsource(generate_weekly_digest),
        "SCORE_CALIBRATION": inspect.getsource(
            __import__("src.weekly", fromlist=["x"]).generate_calibration_review
        ),
        "X_POST": inspect.getsource(
            __import__("src.services.x_delivery", fromlist=["x"]).compose_story_post
        ),
        "EDITION_OVERVIEW": inspect.getsource(
            __import__("src.ai.summarizer", fromlist=["x"]).generate_edition_overview
        ),
    }
    for name in prose_prompts:
        # The prompt exists and is prose, not a JSON schema request.
        assert hasattr(prompt_module, f"{name}_SYSTEM")
        assert 'response_format="text"' in sources[name], (
            f"{name} composes prose but does not ask for text mode"
        )

    # And the JSON callers still get JSON mode by default.
    analyzer_source = inspect.getsource(
        __import__("src.ai.analyzer", fromlist=["x"]).ContentAnalyzer._analyze_item
    )
    assert "response_format" not in analyzer_source
    assert re.search(r"json", prompt_module.CONTENT_ANALYSIS_USER, re.I)
