"""Unit tests for Telegram channel edition delivery."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from pydantic import ValidationError

from src.models import (
    ContentItem,
    SourceType,
    TelegramDeliveryConfig,
)
from src.services.telegram_delivery import (
    TelegramDeliveryStatus,
    TelegramEditionPublisher,
)


def _item(
    item_id: str,
    *,
    title: str = "Market update",
    summary: str = "Important context for readers.",
    score: float = 8.0,
) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=title,
        url=f"https://example.com/{item_id}",
        published_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
        ai_score=score,
        ai_summary=summary,
        metadata={"title_zh": title},
    )


def test_build_message_is_html_safe_and_bounded() -> None:
    config = TelegramDeliveryConfig(max_message_chars=700)
    publisher = TelegramEditionPublisher(config)
    items = [
        _item(
            str(index),
            title=f"BTC & AI > market {index}",
            summary="A long summary with **Markdown** and <details>HTML</details>. " * 4,
        )
        for index in range(12)
    ]

    message = publisher.build_message(
        items,
        date="2026-08-04",
        total_candidates=30,
        language="zh",
    )

    assert len(message) <= 700
    assert "BTC &amp; AI &gt; market" in message
    assert "阅读完整日报" in message
    assert "请在网站查看" in message


def test_missing_credentials_skips_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    publisher = TelegramEditionPublisher(TelegramDeliveryConfig(enabled=True))

    result = asyncio.run(
        publisher.send_daily_edition(
            [_item("one")],
            date="2026-08-04",
            total_candidates=10,
            language="zh",
        )
    )

    assert result.status == TelegramDeliveryStatus.SKIPPED
    assert "TELEGRAM_BOT_TOKEN" in result.detail
    assert "TELEGRAM_CHANNEL_ID" in result.detail


def test_send_daily_edition_posts_expected_bot_api_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@bmtnews_test")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    publisher = TelegramEditionPublisher(
        TelegramDeliveryConfig(enabled=True),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        publisher.send_daily_edition(
            [_item("one", title="BTC rises")],
            date="2026-08-04",
            total_candidates=10,
            language="zh",
        )
    )

    assert result.status == TelegramDeliveryStatus.SUCCESS
    assert captured["url"] == (
        "https://api.telegram.org/bottest-token/sendMessage"
    )
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["chat_id"] == "@bmtnews_test"
    assert payload["parse_mode"] == "HTML"
    assert payload["link_preview_options"] == {"is_disabled": True}
    assert "BTC rises" in payload["text"]


def test_api_failure_does_not_expose_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "super-secret-token"
    channel_id = "@private-channel"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", channel_id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "ok": False,
                "error_code": 400,
                "description": f"Bad Request for {channel_id} using {token}",
            },
        )

    publisher = TelegramEditionPublisher(
        TelegramDeliveryConfig(enabled=True),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(
        publisher.send_daily_edition(
            [_item("one")],
            date="2026-08-04",
            total_candidates=10,
            language="zh",
        )
    )

    assert result.status == TelegramDeliveryStatus.FAILURE
    assert "Telegram API error 400" in result.detail
    assert token not in result.detail
    assert channel_id not in result.detail


@pytest.mark.parametrize(
    "kwargs",
    [
        {"site_url": "file:///tmp/report"},
        {"max_message_chars": 500},
        {"max_message_chars": 4097},
    ],
)
def test_telegram_delivery_config_rejects_unsafe_values(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        TelegramDeliveryConfig(**kwargs)
