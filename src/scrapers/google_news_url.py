"""Best-effort resolution of Google News RSS redirect links.

Google News RSS entries link to ``news.google.com/rss/articles/<token>``
redirect pages instead of the publisher's article. Publishing those links
hurts readers (opaque URLs) and defeats cross-source URL deduplication,
because the same article fetched from the publisher's own feed never matches
the Google News redirect form.

For the common ``CBMi…`` token format, the token is a URL-safe base64
protobuf whose first field is the article URL, so it can be decoded locally
without any network round trip. Newer ``AU_yqL…`` tokens are opaque and
cannot be decoded offline; for those the original link is kept unchanged.
"""

from __future__ import annotations

import base64
import logging
import re
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

_ARTICLE_PATH = re.compile(r"^/(?:rss/)?articles/([A-Za-z0-9_-]+)")

# Decoded CBMi… tokens start with these protobuf bytes: field 1 (varint) = 19,
# then field 4 (length-delimited string) holding the article URL.
_TOKEN_PREFIX = b"\x08\x13\x22"


def _read_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    """Read one protobuf varint; returns (value, next_offset) or None."""
    value = 0
    shift = 0
    while offset < len(data) and shift <= 35:
        byte = data[offset]
        value |= (byte & 0x7F) << shift
        offset += 1
        if not byte & 0x80:
            return value, offset
        shift += 7
    return None


def resolve_google_news_url(url: str) -> str | None:
    """Return the publisher URL embedded in a Google News redirect link.

    Returns None when the link is not a decodable Google News article
    redirect, so callers can keep the original URL.
    """
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() != "news.google.com":
        return None
    match = _ARTICLE_PATH.match(parsed.path)
    if not match:
        return None

    token = match.group(1)
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (ValueError, TypeError):
        return None
    if not raw.startswith(_TOKEN_PREFIX):
        return None

    varint = _read_varint(raw, len(_TOKEN_PREFIX))
    if varint is None:
        return None
    length, offset = varint
    if length <= 0 or offset + length > len(raw):
        return None
    try:
        candidate = raw[offset : offset + length].decode("utf-8")
    except UnicodeDecodeError:
        return None

    try:
        candidate_parts = urlsplit(candidate)
    except ValueError:
        return None
    if candidate_parts.scheme not in {"http", "https"}:
        return None
    host = (candidate_parts.hostname or "").lower()
    if not host or host == "news.google.com":
        return None
    return candidate


def canonicalize_entry_link(link: str) -> str:
    """Replace a Google News redirect link with the publisher URL if possible."""
    resolved = resolve_google_news_url(link)
    if resolved:
        logger.debug("Resolved Google News link %s -> %s", link, resolved)
        return resolved
    return link
