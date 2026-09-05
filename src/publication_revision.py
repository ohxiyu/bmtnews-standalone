"""Stable content markers shared by rendered cards and the edition API."""

import hashlib
import json


def story_revision(url: str, title: str, summary: str) -> str:
    """Track core story text, not generated-at times or HTML formatting."""
    body = json.dumps(
        [str(value).strip() for value in (url, title, summary)],
        ensure_ascii=False, separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
