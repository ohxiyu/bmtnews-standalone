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
# Below this the model plainly did not explain the event. The compact brief
# targets 90-150 Chinese characters; this floor leaves some tolerance for
# concise posts while still rejecting headline-only generations.
MINIMUM_COMPOSED_WEIGHT = 150

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
_HARD_SENTENCE_END = "。！？…\n"
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
            sentence = cleaned[: index + 1].strip()
            return (
                sentence
                if len(sentence) <= limit
                else sentence[: limit - 1].rstrip() + _ELLIPSIS
            )
    return cleaned[:limit].rstrip() + ("…" if len(cleaned) > limit else "")


def _ensure_sentence_end(text: str) -> str:
    """Give a compact fallback fragment an explicit sentence ending."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    if cleaned.rstrip('”’"）)]').endswith(tuple("。！？….!?")):
        return cleaned
    return cleaned + ("。" if re.search(r"[\u3400-\u9fff]", cleaned) else ".")


def _is_single_sentence(paragraph: str) -> bool:
    """Require one complete summary sentence in the opening paragraph."""
    endings = [
        index
        for index in range(len(paragraph))
        if _is_sentence_end(paragraph, index)
    ]
    if len(endings) != 1:
        return False
    trailing = paragraph[endings[0] + 1 :].strip().strip('”’"）)]')
    return not trailing


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
    summary = str(
        item.metadata.get(f"detailed_summary_{language}")
        or item.ai_summary
        or title
    ).strip()
    link = ""
    if link_target == "source":
        link = _safe_http_url(item.url) or ""
    elif link_target == "site":
        link = site_url.rstrip("/") + ("/" if is_zh else "/en/")

    # Reserve the t.co token and the blank lines around it.
    budget = limit - (TCO_LENGTH + 2 if link else 0)
    lede_source = _ensure_sentence_end(_first_sentence(summary, limit=90))
    lede_budget = max(40, min(180, budget // 2))
    lede = truncate_weighted(lede_source, min(lede_budget, budget))

    body_source = ""
    for candidate in (
        item.metadata.get(f"market_impact_{language}"),
        item.metadata.get(f"background_{language}"),
        title,
    ):
        fragment = _ensure_sentence_end(_first_sentence(str(candidate or ""), limit=90))
        if fragment and fragment != lede_source:
            body_source = fragment
            break

    remaining = budget - _weighted_length(lede) - 2
    body_detail = truncate_weighted(body_source, remaining) if remaining > 24 else ""
    body = f"{lede}\n\n{body_detail}" if body_detail else lede
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
    sections = [part.strip() for part in re.split(r"\n\s*\n", cleaned) if part.strip()]
    if len(sections) != 2 or not _is_single_sentence(sections[0]):
        return None
    cleaned = f"{sections[0]}\n\n{sections[1]}"
    if _weighted_length(cleaned) > limit:
        return None
    # A post this short is a failed generation, not a terse one.
    if _character_weight(cleaned) < MINIMUM_COMPOSED_WEIGHT:
        return None
    return cleaned


def post_source_fields(item: ContentItem, language: str) -> dict[str, str]:
    """The published fields a post may draw on, and nothing else.

    These are exactly what the reader sees on the edition page. The raw
    article body is deliberately excluded: it is unedited source text, and a
    post built from it can carry claims the page itself left out.
    """
    metadata = item.metadata or {}

    def field(name: str) -> str:
        return str(metadata.get(f"{name}_{language}") or "").strip()

    return {
        "title": str(metadata.get(f"title_{language}") or item.title or "").strip(),
        "summary": field("detailed_summary") or str(item.ai_summary or "").strip(),
        "background": field("background"),
        "market_impact": field("market_impact"),
        "discussion": field("community_discussion"),
    }


# Figures a post might state. Group 1 is the number, group 2 an optional
# magnitude or percent. Dates are removed first: they are not amounts, and
# "9月26日" vs "September 26" would otherwise fail a check they should pass.
_DATE_PATTERNS = (
    re.compile(r"\d{4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?"),
    re.compile(r"\d{1,2}\s*月\s*\d{1,2}\s*日"),
    re.compile(r"\d{1,2}\s*月"),
    re.compile(r"\d{1,2}\s*日"),
    re.compile(r"\d{4}-\d{2}-\d{2}"),
    re.compile(
        r"(?i)\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,\s*\d{4})?"
    ),
)
_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(万亿|亿|万|千|trillion|billion|million|thousand|bn|tn|[kKmMbBtT](?![a-zA-Z])|%|％)?"
)
_MAGNITUDE = {
    "万亿": 1e12, "亿": 1e8, "万": 1e4, "千": 1e3,
    "trillion": 1e12, "tn": 1e12, "t": 1e12,
    "billion": 1e9, "bn": 1e9, "b": 1e9,
    "million": 1e6, "m": 1e6,
    "thousand": 1e3, "k": 1e3,
}


def _figures(text: str) -> list[tuple[float, float, bool, str]]:
    """(value, rounding tolerance, is_percent, original) for each figure."""
    cleaned = str(text or "")
    for pattern in _DATE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    found = []
    for match in _NUMBER.finditer(cleaned):
        digits, unit = match.group(1), (match.group(2) or "")
        percent = unit in {"%", "％"}
        scale = 1.0 if percent else _MAGNITUDE.get(unit.lower(), 1.0)
        number = float(digits.replace(",", ""))
        decimals = len(digits.split(".", 1)[1]) if "." in digits else 0
        # A figure written with d decimals may be a rounding of anything within
        # half a unit of its last digit.
        tolerance = 0.5 * (10 ** -decimals) * scale
        found.append((number * scale, tolerance, percent, match.group(0).strip()))
    return found


def unsupported_figures(post: str, sources: Iterable[str]) -> list[str]:
    """Figures in the post that no published field supports.

    A post figure is supported when some source figure of the same kind
    (percent or not) rounds to it. Single-digit plain numbers are ignored:
    they are usually counts written as words elsewhere ("两家", "3 家").
    """
    source_figures = [figure for text in sources for figure in _figures(text)]
    missing = []
    for value, tolerance, percent, original in _figures(post):
        if not percent and tolerance == 0.5 and value < 10:
            continue
        if not any(
            percent == source_percent and abs(value - source_value) <= tolerance
            for source_value, _, source_percent, _ in source_figures
        ):
            missing.append(original)
    return missing


async def compose_story_post(
    ai_client,
    item: ContentItem,
    *,
    language: str,
    limit: int = 400,
) -> Optional[str]:
    """Write one post for a story in the account's voice.

    Returns None on any failure or unusable output so the caller can fall
    back to the assembled post rather than skipping the slot.
    """
    from ..ai.prompts import X_POST_SYSTEM, X_POST_USER

    fields = post_source_fields(item, language)
    try:
        response = await ai_client.complete(
            system=X_POST_SYSTEM,
            user=X_POST_USER.format(
                title=fields["title"],
                summary=fields["summary"],
                background=fields["background"] or "（无）",
                market_impact=fields["market_impact"] or "（无）",
                discussion=fields["discussion"] or "（无）",
            ),
            response_format="text",
        )
    except Exception as exc:  # noqa: BLE001 - degrade to the fallback
        logger.warning("X post composition failed for %s: %s", item.id, exc)
        return None
    return sanitize_composed_post(response, limit=limit)


@dataclass(frozen=True)
class PostOutcome:
    """What one planned-post attempt proved about the post.

    ``kind`` is one of:

    - ``sent``: X accepted the post and returned its id.
    - ``not_sent``: the request provably never reached X (no connection), so
      trying again cannot produce a duplicate.
    - ``rate_limited``: X refused with HTTP 429 and created nothing.
    - ``failed``: X refused definitively (401, 403, other 4xx). Retrying the
      same request will not help; a person has to look.
    - ``unknown``: the request may have been accepted (timeout after sending,
      5xx, unreadable success body). Never retried automatically.

    ``detail`` is safe for public logs: it never contains a response body.
    """

    kind: str
    detail: str = ""
    tweet_id: str = ""


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

    def not_ready_reason(self) -> str:
        """Why a planned post cannot be attempted now, or "" when it can.

        Checked before a job is marked pending, so a missing credential leaves
        the plan untouched instead of producing an attempt that never ran.
        """
        if not self.config.enabled:
            return "X delivery is disabled in the configuration."
        if not all(self._credentials()):
            return "X credentials are not fully configured; nothing posted."
        return ""

    async def publish_post(self, text: str) -> PostOutcome:
        """Attempt one planned post and classify what the attempt proved."""
        reason = self.not_ready_reason()
        if reason:
            return PostOutcome("not_sent", reason)
        if not text.strip():
            return PostOutcome("not_sent", "Nothing to post.")
        consumer_key, consumer_secret, access_token, access_secret = (
            self._credentials()
        )
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
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # No connection was established, so X never saw the request.
            return PostOutcome("not_sent", f"X request not sent: {type(exc).__name__}")
        except httpx.HTTPError as exc:
            return PostOutcome("unknown", f"X request outcome unknown: {type(exc).__name__}")
        code = response.status_code
        if code == 429:
            return PostOutcome("rate_limited", "X API returned HTTP 429.")
        if code >= 500:
            return PostOutcome("unknown", f"X API returned HTTP {code}.")
        if code >= 400:
            return PostOutcome("failed", f"X API returned HTTP {code}.")
        try:
            tweet_id = str((response.json().get("data") or {}).get("id") or "")
        except (ValueError, AttributeError):
            tweet_id = ""
        if not tweet_id.isdigit():
            return PostOutcome(
                "unknown", f"X API returned HTTP {code} without a post id."
            )
        return PostOutcome("sent", f"X API returned HTTP {code}.", tweet_id)

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
