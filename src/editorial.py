"""Manual editorial layer for the daily edition.

The file ``data/editorial.json`` is the whole "backend": edit it (GitHub
web UI, mobile app, or any editor), push to main, and the rebuild workflow
republishes today's edition with the changes. Three entry types are
supported:

- ``editorial``  — a story you add yourself. It becomes a normal item in
  the edition (and therefore also reaches Telegram/email/webhook), pinned
  to the top and labeled as an editor's pick.
- ``sponsored``  — a clearly-labeled ad slot rendered on the web edition
  only, outside the ranking. At most one is shown per edition.
- ``suppress``   — hide a story by URL from the edition being built.

Every entry only applies to editions whose local date falls inside the
entry's optional ``date`` / ``starts`` / ``expires`` fields, so ads expire
automatically. Loading is fail-soft: a malformed file or entry is skipped
with a warning and never blocks publishing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, time, timezone
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from .models import ContentItem, SourceType

logger = logging.getLogger(__name__)

DEFAULT_EDITORIAL_PATH = Path("data/editorial.json")


class EditorialEntry(BaseModel):
    """One row of data/editorial.json."""

    type: str
    url: Optional[str] = None
    title_zh: Optional[str] = None
    title_en: Optional[str] = None
    summary_zh: Optional[str] = None
    summary_en: Optional[str] = None
    background_zh: Optional[str] = None
    background_en: Optional[str] = None
    market_impact_zh: Optional[str] = None
    market_impact_en: Optional[str] = None
    community_discussion_zh: Optional[str] = None
    community_discussion_en: Optional[str] = None
    category: str = "crypto-markets"
    tags: List[str] = Field(default_factory=list)
    sources: List[dict[str, str]] = Field(default_factory=list)
    official: bool = False
    note: Optional[str] = None
    label: Optional[str] = None
    date: Optional[date_type] = None
    starts: Optional[date_type] = None
    expires: Optional[date_type] = None
    position: Optional[int] = None
    enabled: bool = True

    def active_on(self, edition_date: date_type) -> bool:
        if not self.enabled:
            return False
        if self.date is not None and self.date != edition_date:
            return False
        if self.starts is not None and edition_date < self.starts:
            return False
        if self.expires is not None and edition_date > self.expires:
            return False
        return True

    def best_title(self, language: str) -> str:
        preferred = self.title_zh if language == "zh" else self.title_en
        return (preferred or self.title_zh or self.title_en or "").strip()

    def best_summary(self, language: str) -> str:
        preferred = self.summary_zh if language == "zh" else self.summary_en
        return (preferred or self.summary_zh or self.summary_en or "").strip()


@dataclass
class EditorialPlan:
    """Entries that apply to one edition date."""

    editorial: List[EditorialEntry] = field(default_factory=list)
    sponsored: List[EditorialEntry] = field(default_factory=list)
    suppressed_urls: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.editorial or self.sponsored or self.suppressed_urls)


def load_editorial_plan(
    edition_date: date_type,
    path: Path = DEFAULT_EDITORIAL_PATH,
) -> EditorialPlan:
    """Load the entries that apply to ``edition_date``; always fail-soft."""
    plan = EditorialPlan()
    if not path.exists():
        return plan
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring unreadable editorial file %s: %s", path, exc)
        return plan

    rows = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return plan

    for index, row in enumerate(rows):
        try:
            entry = EditorialEntry.model_validate(row)
        except ValidationError as exc:
            logger.warning("Skipping invalid editorial entry #%d: %s", index, exc)
            continue
        if not entry.active_on(edition_date):
            continue
        if entry.type == "suppress":
            if entry.url:
                plan.suppressed_urls.append(entry.url)
            continue
        if not entry.url or not entry.best_title("zh"):
            logger.warning(
                "Skipping editorial entry #%d: url and a title are required",
                index,
            )
            continue
        if entry.type == "sponsored":
            plan.sponsored.append(entry)
        elif entry.type == "editorial":
            plan.editorial.append(entry)
        else:
            logger.warning(
                "Skipping editorial entry #%d with unknown type %r",
                index,
                entry.type,
            )
    return plan


def editorial_content_item(
    entry: EditorialEntry,
    edition_date: date_type,
) -> ContentItem:
    """Build the pipeline item for one editor's-pick entry."""
    digest = hashlib.sha256(str(entry.url).encode("utf-8")).hexdigest()[:16]
    published_at = datetime.combine(
        edition_date, time(hour=0), tzinfo=timezone.utc
    )
    metadata = {
        "editorial": True,
        "source_name": entry.label or "Editorial",
        "category": entry.category or "crypto-markets",
        "official": entry.official,
    }
    for language in ("zh", "en"):
        title = entry.best_title(language)
        summary = entry.best_summary(language)
        if title:
            metadata[f"title_{language}"] = title
        if summary:
            metadata[f"detailed_summary_{language}"] = summary
        for field_name in (
            "background",
            "market_impact",
            "community_discussion",
        ):
            value = str(getattr(entry, f"{field_name}_{language}") or "").strip()
            if value:
                metadata[f"{field_name}_{language}"] = value
    references = []
    for source in entry.sources:
        url = str(source.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            continue
        references.append(
            {
                "title": str(source.get("title") or url).strip(),
                "url": url,
            }
        )
    if references:
        metadata["sources"] = references
    return ContentItem(
        id=f"editorial:pick:{digest}",
        source_type=SourceType.EDITORIAL,
        title=entry.best_title("zh") or entry.best_title("en"),
        url=entry.url,
        content=entry.best_summary("zh") or entry.best_summary("en") or None,
        author=entry.label or "Editorial",
        published_at=published_at,
        metadata=metadata,
        ai_summary=entry.best_summary("zh") or entry.best_summary("en") or None,
        ai_tags=[tag.strip() for tag in entry.tags if tag.strip()],
    )
