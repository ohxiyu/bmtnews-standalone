"""Publish the day's top stories to X (Twitter).

Disabled by default and doubly gated: the config block must set
``enabled: true`` **and** all four OAuth 1.0a credentials must be present in
the environment. Without both, the publisher reports SKIPPED and posts
nothing, so merging this code cannot by itself cause an outward-facing post.

Requests are signed with OAuth 1.0a user context, which is what the X API
v2 ``POST /2/tweets`` endpoint requires for posting on behalf of an account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from enum import Enum
import logging
from typing import Iterable, List, Optional
from urllib.parse import quote, urlsplit

import httpx
from rich.console import Console

from ..ai.utils import unwrap_prose_response
from ..models import ContentItem, XDeliveryConfig

logger = logging.getLogger(__name__)

X_TWEETS_ENDPOINT = "https://api.x.com/2/tweets"
# Standard accounts are capped at 280 weighted characters; Premium accounts
# post much longer, so the effective cap comes from the config.
TWEET_LIMIT = 280
# X counts every URL as a fixed-width t.co link regardless of real length.
TCO_LENGTH = 23
# How much of the source article the composer is shown. Long enough to carry
# a timeline and the concrete numbers, short enough to stay cheap per post.
ARTICLE_EXCERPT_CHARS = 6000
# Below this the model plainly did not explain the event. The compact brief
# targets 180-300 Chinese characters; this floor leaves some tolerance for
# concise posts while still rejecting headline-only generations.
MINIMUM_COMPOSED_WEIGHT = 300

# twitter-text v3 weighting: code points in these ranges count as one
# character, everything else — including CJK — counts as two. Counting CJK
# as one would understate a Chinese post by nearly half and let an
# over-length post reach the API.
_SINGLE_WEIGHT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200D),
    (0x2010, 0x201F),
    (0x2032, 0x2037),
)
_URL_PATTERN = re.compile(r"https?://\S+")
# U+2026 falls outside the single-weight ranges, so it costs two units.
_ELLIPSIS = "…"


class XDeliveryStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILURE = "failure"


@dataclass(frozen=True)
class XDeliveryResult:
    """Sanitized result safe for logs and public run reports."""

    status: XDeliveryStatus
    detail: str = ""
    posted: int = 0


def _percent_encode(value: str) -> str:
    return quote(str(value), safe="-._~")


def _oauth_header(
    method: str,
    url: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_secret: str,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Build an OAuth 1.0a Authorization header for a JSON-body request.

    A JSON body is not part of the signature base string; only the request
    method, URL, and OAuth parameters are signed.
    """
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": access_token,
        "oauth_version": "1.0",
    }
    parameter_string = "&".join(
        f"{_percent_encode(key)}={_percent_encode(oauth_params[key])}"
        for key in sorted(oauth_params)
    )
    split = urlsplit(url)
    base_url = f"{split.scheme}://{split.netloc}{split.path}"
    base_string = "&".join(
        [
            method.upper(),
            _percent_encode(base_url),
            _percent_encode(parameter_string),
        ]
    )
    signing_key = (
        f"{_percent_encode(consumer_secret)}&{_percent_encode(access_secret)}"
    )
    signature = base64.b64encode(
        hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("ascii")
    header_params = {**oauth_params, "oauth_signature": signature}
    joined = ", ".join(
        f'{_percent_encode(key)}="{_percent_encode(header_params[key])}"'
        for key in sorted(header_params)
    )
    return f"OAuth {joined}"


def _character_weight(text: str) -> int:
    """Weighted length of text containing no URLs."""
    total = 0
    for char in text:
        code = ord(char)
        if any(start <= code <= end for start, end in _SINGLE_WEIGHT_RANGES):
            total += 1
        else:
            total += 2
    return total


def _weighted_length(text: str) -> int:
    """Count a post the way X does, collapsing every URL to a t.co token."""
    total = 0
    position = 0
    for match in _URL_PATTERN.finditer(text):
        total += _character_weight(text[position : match.start()])
        total += TCO_LENGTH
        position = match.end()
    return total + _character_weight(text[position:])


def truncate_weighted(text: str, limit: int) -> str:
    """Cut text to ``limit`` weighted characters, ellipsis included.

    Slicing by character count would overshoot for CJK, where one character
    costs two weighted units.
    """
    ellipsis_cost = _character_weight(_ELLIPSIS)
    if limit <= ellipsis_cost:
        return ""
    if _weighted_length(text) <= limit:
        return text
    budget = limit - ellipsis_cost
    kept: List[str] = []
    used = 0
    for char in text:
        cost = _character_weight(char)
        if used + cost > budget:
            break
        kept.append(char)
        used += cost
    return "".join(kept).rstrip() + _ELLIPSIS if kept else ""


def _truncate_to_fit(headline: str, fixed_cost: int, limit: int = TWEET_LIMIT) -> str:
    """Shorten a headline so the whole post fits the character limit."""
    return truncate_weighted(headline, limit - fixed_cost)


def build_post(
    items: Iterable[ContentItem],
    *,
    date: str,
    language: str,
    site_url: str,
    max_items: int = 3,
) -> str:
    """Compose one post linking back to the full edition."""
    selected = list(items)[:max_items]
    is_zh = language == "zh"
    header = f"BMTNews {date}" if is_zh else f"BMTNews {date}"
    link = site_url.rstrip("/") + ("/" if is_zh else "/en/")
    lines: List[str] = []
    # Reserve room for the header, the trailing link, and the newlines.
    fixed = _weighted_length(header) + TCO_LENGTH + 4
    for index, item in enumerate(selected, start=1):
        title = (
            item.metadata.get(f"title_{language}")
            or item.metadata.get("title_zh")
            or item.title
        )
        prefix = f"{index}. "
        remaining = TWEET_LIMIT - fixed - _weighted_length("\n".join(lines)) - len(prefix) - 2
        headline = _truncate_to_fit(str(title).strip(), TWEET_LIMIT - remaining)
        if not headline:
            break
        lines.append(f"{prefix}{headline}")
    body = "\n".join(lines)
    return f"{header}\n{body}\n{link}".strip()


def _safe_http_url(value: object) -> str | None:
    """Return the value only when it is a usable HTTP(S) link."""
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return raw


# Full-width terminators are unambiguous; the ASCII period is not, so it
# needs the guards in _is_sentence_end below.
_HARD_SENTENCE_END = "。！？\n"
_ABBREVIATION_TAIL = re.compile(r"(?:^|[\s.])[A-Za-z]$")


def _is_sentence_end(text: str, index: int) -> bool:
    """Decide whether the character at ``index`` really ends a sentence."""
    char = text[index]
    if char in _HARD_SENTENCE_END:
        return True
    if char not in ".!?":
        return False
    following = text[index + 1] if index + 1 < len(text) else " "
    if not following.isspace():
        # "H.R." or "3.5" — an inner dot, not a terminator.
        return False
    # A single letter before the dot means an initialism such as "H.R.".
    return not _ABBREVIATION_TAIL.search(text[max(0, index - 3) : index])


def _first_sentence(text: str, limit: int = 110) -> str:
    """Take the opening sentence of a summary, bounded for a post."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for index in range(len(cleaned)):
        if index >= 12 and _is_sentence_end(cleaned, index):
            return cleaned[: index + 1].strip()
    return cleaned[:limit].rstrip() + ("…" if len(cleaned) > limit else "")


def build_story_post(
    item: ContentItem,
    *,
    language: str,
    site_url: str,
    link_target: str = "none",
    limit: int = TWEET_LIMIT,
    edition_date: str | None = None,
) -> str:
    """Assemble a single-story post from the fields already on the item.

    This is the deterministic fallback used when AI composition is off or
    fails; ``compose_story_post`` produces the normal, better-written post.
    """
    is_zh = language == "zh"
    title = str(
        item.metadata.get(f"title_{language}")
        or item.metadata.get("title_zh")
        or item.title
    ).strip()
    takeaway = _first_sentence(
        item.metadata.get(f"market_impact_{language}")
        or item.metadata.get(f"detailed_summary_{language}")
        or item.ai_summary
        or ""
    )
    link = ""
    if link_target == "source":
        link = _safe_http_url(item.url) or ""
    elif link_target == "site":
        link = site_url.rstrip("/") + ("/" if is_zh else "/en/")

    # Reserve the t.co token and the blank lines around it.
    budget = limit - (TCO_LENGTH + 2 if link else 0)
    headline = truncate_weighted(title, budget)
    remaining = budget - _weighted_length(headline) - 2
    body = headline
    if takeaway and remaining > 24:
        takeaway = truncate_weighted(takeaway, remaining)
        if takeaway:
            body = f"{headline}\n\n{takeaway}"
    return f"{body}\n\n{link}".rstrip() if link else body


# Model output must never carry links, tags, or wrapping quotes into a post.
_HASHTAG_PATTERN = re.compile(r"(?:^|\s)#\S+")
_MARKDOWN_NOISE = re.compile(r"[*_`>]+")


def sanitize_composed_post(text: str, *, limit: int) -> Optional[str]:
    """Clean and validate an AI-composed post; None means unusable.

    Rejecting is safe: the caller falls back to the assembled post.
    """
    # Most prompts in this pipeline ask for JSON, so a prose prompt is
    # occasionally answered with a JSON wrapper; unwrap before cleaning.
    cleaned = unwrap_prose_response(
        text, keys=("post", "tweet", "content", "text", "body")
    )
    cleaned = cleaned.strip().strip('"').strip("“”").strip()
    if not cleaned:
        return None
    cleaned = _URL_PATTERN.sub("", cleaned)
    cleaned = _HASHTAG_PATTERN.sub("", cleaned)
    cleaned = _MARKDOWN_NOISE.sub("", cleaned)
    # Collapse runs of blank lines but keep paragraph separation. Lines are
    # fully stripped because removing a leading tag or link leaves gaps.
    lines = [re.sub(r"[ \t]{2,}", " ", line).strip() for line in cleaned.splitlines()]
    paragraphs: List[str] = []
    for line in lines:
        if line:
            paragraphs.append(line)
        elif paragraphs and paragraphs[-1] != "":
            paragraphs.append("")
    cleaned = "\n".join(paragraphs).strip()
    if not cleaned:
        return None
    if _weighted_length(cleaned) > limit:
        return None
    # A post this short is a failed generation, not a terse one.
    if _character_weight(cleaned) < MINIMUM_COMPOSED_WEIGHT:
        return None
    return cleaned


async def compose_story_post(
    ai_client,
    item: ContentItem,
    *,
    language: str,
    limit: int = 800,
) -> Optional[str]:
    """Write one post for a story in the account's voice.

    Returns None on any failure or unusable output so the caller can fall
    back to the assembled post rather than skipping the slot.
    """
    from ..ai.prompts import X_POST_SYSTEM, X_POST_USER

    metadata = item.metadata or {}

    def field(name: str) -> str:
        return str(metadata.get(f"{name}_{language}") or "").strip()

    # A narrative post needs more raw material than the summaries carry: the
    # timeline and the concrete numbers usually only exist in the article body.
    article = " ".join(str(item.content or "").split())[:ARTICLE_EXCERPT_CHARS]

    try:
        response = await ai_client.complete(
            system=X_POST_SYSTEM,
            user=X_POST_USER.format(
                title=metadata.get(f"title_{language}") or item.title,
                summary=field("detailed_summary") or (item.ai_summary or ""),
                background=field("background") or "（无）",
                market_impact=field("market_impact") or "（无）",
                discussion=field("community_discussion") or "（无）",
                article=article or "（无）",
            ),
            response_format="text",
        )
    except Exception as exc:  # noqa: BLE001 - degrade to the fallback
        logger.warning("X post composition failed for %s: %s", item.id, exc)
        return None
    return sanitize_composed_post(response, limit=limit)


class XEditionPublisher:
    """Post one compact edition summary to X."""

    def __init__(
        self,
        config: XDeliveryConfig,
        *,
        console: Console | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self.console = console or Console()
        self.transport = transport

    def _credentials(self) -> tuple[str, str, str, str]:
        return (
            os.getenv(self.config.consumer_key_env, "").strip(),
            os.getenv(self.config.consumer_secret_env, "").strip(),
            os.getenv(self.config.access_token_env, "").strip(),
            os.getenv(self.config.access_secret_env, "").strip(),
        )

    async def send_text(self, text: str) -> XDeliveryResult:
        """Post one already-composed message, applying the same gating."""
        if not self.config.enabled:
            return XDeliveryResult(
                status=XDeliveryStatus.SKIPPED,
                detail="X delivery is disabled in the configuration.",
            )
        consumer_key, consumer_secret, access_token, access_secret = (
            self._credentials()
        )
        if not all((consumer_key, consumer_secret, access_token, access_secret)):
            return XDeliveryResult(
                status=XDeliveryStatus.SKIPPED,
                detail="X credentials are not fully configured; nothing posted.",
            )
        if not text.strip():
            return XDeliveryResult(
                status=XDeliveryStatus.SKIPPED,
                detail="Nothing to post.",
            )
        return await self._post(
            text,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_secret=access_secret,
        )

    async def _post(
        self,
        text: str,
        *,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_secret: str,
    ) -> XDeliveryResult:
        authorization = _oauth_header(
            "POST",
            X_TWEETS_ENDPOINT,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_secret=access_secret,
        )
        try:
            async with httpx.AsyncClient(
                timeout=20.0, transport=self.transport
            ) as client:
                response = await client.post(
                    X_TWEETS_ENDPOINT,
                    headers={
                        "Authorization": authorization,
                        "Content-Type": "application/json",
                    },
                    json={"text": text},
                )
        except httpx.HTTPError as exc:
            return XDeliveryResult(
                status=XDeliveryStatus.FAILURE,
                detail=f"X request failed: {type(exc).__name__}",
            )
        if response.status_code >= 400:
            # Response bodies can echo request content; report only the code.
            return XDeliveryResult(
                status=XDeliveryStatus.FAILURE,
                detail=f"X API returned HTTP {response.status_code}.",
            )
        return XDeliveryResult(status=XDeliveryStatus.SUCCESS, posted=1)

    async def send_daily_edition(
        self,
        items: Iterable[ContentItem],
        *,
        date: str,
        language: str,
    ) -> XDeliveryResult:
        if not self.config.enabled:
            return XDeliveryResult(
                status=XDeliveryStatus.SKIPPED,
                detail="X delivery is disabled in the configuration.",
            )
        consumer_key, consumer_secret, access_token, access_secret = (
            self._credentials()
        )
        if not all((consumer_key, consumer_secret, access_token, access_secret)):
            return XDeliveryResult(
                status=XDeliveryStatus.SKIPPED,
                detail="X credentials are not fully configured; nothing posted.",
            )

        selected = list(items)
        if not selected:
            return XDeliveryResult(
                status=XDeliveryStatus.SKIPPED,
                detail="No stories to post.",
            )

        text = build_post(
            selected,
            date=date,
            language=language,
            site_url=self.config.site_url,
            max_items=self.config.max_items,
        )
        result = await self._post(
            text,
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_secret=access_secret,
        )
        if result.status == XDeliveryStatus.SUCCESS:
            self.console.print(f"🐦 Posted the {language.upper()} edition to X")
        return result
