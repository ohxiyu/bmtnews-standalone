"""Publish one compact daily edition to a Telegram channel."""

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable
from urllib.parse import urlsplit

import httpx
from rich.console import Console

from ..models import ContentItem, TelegramDeliveryConfig


class TelegramDeliveryStatus(str, Enum):
    """Outcome of one Telegram delivery attempt."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILURE = "failure"


@dataclass(frozen=True)
class TelegramDeliveryResult:
    """Sanitized delivery result safe for logs and public run reports."""

    status: TelegramDeliveryStatus
    detail: str = ""
    message_length: int = 0


_MARKDOWN_LINK = re.compile(r"\[([^]]+)]\([^)]*\)")
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


def _plain_text(value: object) -> str:
    """Flatten stored Markdown/HTML into a compact Telegram-safe sentence."""
    text = _MARKDOWN_LINK.sub(r"\1", str(value or ""))
    text = _HTML_TAG.sub(" ", text)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    return _WHITESPACE.sub(" ", text).strip()


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def _safe_http_url(value: object) -> str | None:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


def _redact(value: str, *sensitive_values: str) -> str:
    redacted = value
    for sensitive in sensitive_values:
        if sensitive:
            redacted = redacted.replace(sensitive, "<redacted>")
    return redacted


class TelegramEditionPublisher:
    """Render and send a single HTML-formatted Telegram channel message."""

    def __init__(
        self,
        config: TelegramDeliveryConfig,
        *,
        console: Console | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.console = console or Console()
        self.transport = transport

    def _credentials(self) -> tuple[str, str]:
        token = os.getenv(self.config.bot_token_env, "").strip()
        channel_id = os.getenv(self.config.channel_id_env, "").strip()
        return token, channel_id

    def build_message(
        self,
        items: Iterable[ContentItem],
        *,
        date: str,
        total_candidates: int,
        language: str,
    ) -> str:
        """Build one bounded message without cutting through HTML entities."""
        selected = list(items)
        is_zh = language == "zh"
        title = f"BMTNews 日报 · {date}" if is_zh else f"BMTNews Daily · {date}"
        overview = (
            f"从 {total_candidates} 条候选中筛选出 {len(selected)} 条重要资讯。"
            if is_zh
            else f"Selected {len(selected)} important items from {total_candidates} candidates."
        )
        header = f"<b>{html.escape(title)}</b>\n{html.escape(overview)}"
        site_url = self.config.site_url.rstrip("/") + (
            "/" if is_zh else "/en/"
        )
        footer = (
            f'\n\n<a href="{html.escape(site_url, quote=True)}">阅读完整日报</a>'
            if is_zh
            else f'\n\n<a href="{html.escape(site_url, quote=True)}">Read the full edition</a>'
        )
        empty = "\n\n今日暂无达到展示阈值的重要资讯。" if is_zh else (
            "\n\nNo items reached the display threshold today."
        )
        if not selected:
            return header + empty + footer

        blocks: list[str] = []
        omitted = 0
        for index, item in enumerate(selected, start=1):
            localized_title = item.metadata.get(f"title_{language}") or item.title
            item_title = _shorten(_plain_text(localized_title), 120)
            item_url = _safe_http_url(item.url)
            escaped_title = html.escape(item_title)
            title_markup = (
                f'<a href="{html.escape(item_url, quote=True)}">{escaped_title}</a>'
                if item_url
                else escaped_title
            )
            score = f"{item.ai_score:g}" if item.ai_score is not None else "?"
            headline = f"<b>{index}. {title_markup}</b> · ⭐ {score}/10"
            brief_value = (
                item.metadata.get(f"detailed_summary_{language}")
                or item.metadata.get("detailed_summary")
                or item.ai_summary
                or ""
            )
            brief = _shorten(_plain_text(brief_value), 180)
            block = headline + (f"\n{html.escape(brief)}" if brief else "")
            candidate = header + "\n\n" + "\n\n".join([*blocks, block]) + footer
            if len(candidate) > self.config.max_message_chars:
                title_only = header + "\n\n" + "\n\n".join(
                    [*blocks, headline]
                ) + footer
                if len(title_only) > self.config.max_message_chars:
                    omitted = len(selected) - index + 1
                    break
                block = headline
            blocks.append(block)

        if omitted:
            omission = (
                f"\n\n另有 {omitted} 条，请在网站查看。"
                if is_zh
                else f"\n\n{omitted} more item(s) are available on the website."
            )
            while blocks and len(
                header + "\n\n" + "\n\n".join(blocks) + omission + footer
            ) > self.config.max_message_chars:
                blocks.pop()
                omitted += 1
            body = header + "\n\n" + "\n\n".join(blocks) + omission
        else:
            body = header + "\n\n" + "\n\n".join(blocks)
        return body + footer

    async def send_daily_edition(
        self,
        items: Iterable[ContentItem],
        *,
        date: str,
        total_candidates: int,
        language: str,
    ) -> TelegramDeliveryResult:
        """Send one edition or safely report why it was skipped/failed."""
        if not self.config.enabled or language not in self.config.languages:
            return TelegramDeliveryResult(TelegramDeliveryStatus.SKIPPED)

        token, channel_id = self._credentials()
        if not token or not channel_id:
            missing = []
            if not token:
                missing.append(self.config.bot_token_env)
            if not channel_id:
                missing.append(self.config.channel_id_env)
            return TelegramDeliveryResult(
                TelegramDeliveryStatus.SKIPPED,
                "Missing environment variable(s): " + ", ".join(missing),
            )

        message = self.build_message(
            items,
            date=date,
            total_candidates=total_candidates,
            language=language,
        )
        endpoint = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": channel_id,
            "text": message,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                transport=self.transport,
            ) as client:
                response = await client.post(endpoint, json=payload)
            data = response.json()
            if not isinstance(data, dict):
                return TelegramDeliveryResult(
                    TelegramDeliveryStatus.FAILURE,
                    f"Telegram returned an invalid response (HTTP {response.status_code})",
                    message_length=len(message),
                )
            if response.is_success and data.get("ok") is True:
                self.console.print("[green]✈️ Telegram daily edition sent.[/green]")
                return TelegramDeliveryResult(
                    TelegramDeliveryStatus.SUCCESS,
                    message_length=len(message),
                )
            error_code = data.get("error_code", response.status_code)
            description = _redact(
                _shorten(_plain_text(data.get("description", "")), 160),
                token,
                channel_id,
            )
            return TelegramDeliveryResult(
                TelegramDeliveryStatus.FAILURE,
                f"Telegram API error {error_code}: {description or 'request rejected'}",
                message_length=len(message),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return TelegramDeliveryResult(
                TelegramDeliveryStatus.FAILURE,
                f"Telegram request failed: {type(exc).__name__}",
                message_length=len(message),
            )
        except Exception as exc:
            return TelegramDeliveryResult(
                TelegramDeliveryStatus.FAILURE,
                f"Telegram request failed unexpectedly: {type(exc).__name__}",
                message_length=len(message),
            )
