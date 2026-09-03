"""Incremental event timeline updates for scheduled collection runs.

The published event catalog is the durable state.  A story already present in
any update is never classified again.  New, qualified stories first pass the
hard candidate gate from :mod:`src.events`; only those candidate pairs reach
the semantic classifier.  Ambiguous or low-confidence relations remain
separate events, which is safer than silently corrupting an existing history.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Mapping, Sequence

from ._file_utils import _atomic_write_text
from .ai.client import AIClient
from .ai.event_relations import classify_event_relation
from .events import (
    EventReference,
    EventRelation,
    EventRelationDecision,
    EventSource,
    EventStatus,
    EventTimePrecision,
    EventType,
    EventUpdate,
    EventUpdateType,
    StoryEvidence,
    TrackedEvent,
    retrieve_event_candidates,
    select_event_attachment,
    signature_for_story,
)
from .models import ContentItem


EVENT_CATALOG_PATH = Path("docs/_data/events.json")
EVENT_LEGACY_URLS_PATH = Path("docs/_data/event-legacy-urls.json")
ATTACHMENT_THRESHOLD = 0.90
MAX_RELATION_CANDIDATES = 3

RelationClassifier = Callable[
    [AIClient, TrackedEvent, StoryEvidence],
    Awaitable[EventRelationDecision],
]


@dataclass(frozen=True)
class IncrementalEventResult:
    considered: int = 0
    already_known: int = 0
    candidates_classified: int = 0
    material_updates: int = 0
    duplicate_sources: int = 0
    new_events: int = 0
    classifier_errors: int = 0
    briefs_enriched: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.material_updates
            or self.duplicate_sources
            or self.new_events
            or self.briefs_enriched
        )


def load_event_catalog(
    path: Path = EVENT_CATALOG_PATH,
) -> tuple[dict[str, object], list[TrackedEvent]]:
    """Load and validate the public catalog while preserving its audit fields."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("events")
    if not isinstance(rows, list):
        raise ValueError(f"event catalog has no events array: {path}")
    events = [TrackedEvent.model_validate(row) for row in rows]
    metadata = {key: value for key, value in payload.items() if key != "events"}
    _story_assignment_index(events)  # Reject duplicate membership on read.
    return metadata, events


def save_event_catalog(
    metadata: dict[str, object],
    events: Sequence[TrackedEvent],
    path: Path = EVENT_CATALOG_PATH,
) -> Path:
    """Atomically write a deterministic catalog without changing review proof."""
    _story_assignment_index(events)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(events, key=lambda event: (event.first_seen_at, event.event_id))
    payload = {
        **metadata,
        "schema_version": int(metadata.get("schema_version") or 1),
        "events": [event.model_dump(mode="json") for event in ordered],
    }
    _atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
    )
    return path


def load_legacy_event_urls(
    path: Path = EVENT_LEGACY_URLS_PATH,
) -> tuple[dict[str, str], dict[str, list[str]]]:
    if not path.exists():
        return {}, {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    redirects = payload.get("redirects") or {}
    retired = payload.get("retired") or {}
    if not isinstance(redirects, dict) or not isinstance(retired, dict):
        raise ValueError(f"invalid legacy event URL map: {path}")
    return (
        {str(key): str(value) for key, value in redirects.items()},
        {
            str(key): [str(value) for value in values]
            for key, values in retired.items()
            if isinstance(values, list)
        },
    )


def _story_assignment_index(
    events: Sequence[TrackedEvent],
) -> dict[str, tuple[str, str]]:
    assignments: dict[str, tuple[str, str]] = {}
    for event in events:
        for update in event.updates:
            for story_id in update.story_ids:
                previous = assignments.get(story_id)
                current = (event.event_id, update.update_id)
                if previous is not None and previous != current:
                    raise ValueError(
                        f"story {story_id!r} belongs to multiple event updates"
                    )
                assignments[story_id] = current
    return assignments


def known_story_assignments(
    events: Sequence[TrackedEvent],
) -> dict[str, tuple[str, str]]:
    """Public helper used to avoid sending old stories back through AI."""
    return _story_assignment_index(events)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _localized(item: ContentItem, key: str, language: str) -> str:
    return str(
        item.metadata.get(f"{key}_{language}")
        or item.metadata.get(key)
        or ""
    ).strip()


def story_evidence(item: ContentItem) -> StoryEvidence:
    title_zh = _localized(item, "title", "zh")
    title_en = _localized(item, "title", "en")
    summary_zh = _localized(item, "detailed_summary", "zh")
    summary_en = _localized(item, "detailed_summary", "en")
    fallback_summary = str(item.ai_summary or "").strip()
    return StoryEvidence(
        story_id=item.id,
        url=str(item.url),
        published_at=_aware(item.published_at),
        title_zh=title_zh or item.title,
        title_en=title_en or item.title,
        summary_zh=summary_zh or fallback_summary,
        summary_en=summary_en or fallback_summary,
        tags=list(item.ai_tags or []),
        source_label=_source_label(item),
        entities=[str(value) for value in item.metadata.get("entities", [])],
        identifiers=[
            str(value) for value in item.metadata.get("identifiers", [])
        ],
    )


def _source_label(item: ContentItem) -> str:
    for key in ("feed_name", "channel", "subreddit", "repo", "source_name"):
        value = item.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return (item.author or item.source_type.value).strip()


def _event_source(item: ContentItem) -> EventSource:
    return EventSource(
        url=str(item.url),
        label=_source_label(item) or item.source_type.value,
        source_type=item.source_type.value,
        official=bool(item.metadata.get("official")),
    )


_BRIEF_TEXT_FIELDS = (
    "detailed_summary",
    "background",
    "community_discussion",
    "market_impact",
)


def _event_references(item: ContentItem) -> list[EventReference]:
    """Retain only public, deduplicated links returned by enrichment."""
    references: list[EventReference] = []
    seen: set[str] = set()
    raw_sources = item.metadata.get("sources")
    if isinstance(raw_sources, list):
        for raw in raw_sources:
            if not isinstance(raw, Mapping):
                continue
            url = str(raw.get("url") or "").strip()
            if not url.startswith(("https://", "http://")) or url in seen:
                continue
            references.append(
                EventReference(url=url, title=str(raw.get("title") or "").strip())
            )
            seen.add(url)
    discussion_url = str(item.metadata.get("discussion_url") or "").strip()
    if (
        discussion_url.startswith(("https://", "http://"))
        and discussion_url not in seen
    ):
        references.append(
            EventReference(url=discussion_url, title="Community discussion")
        )
    return references


def _brief_context_from_item(item: ContentItem) -> dict[str, object]:
    context: dict[str, object] = {
        "importance_score": item.ai_score,
        "references": _event_references(item),
    }
    for field in _BRIEF_TEXT_FIELDS:
        for language in ("zh", "en"):
            value = _localized(item, field, language)
            if field == "detailed_summary" and not value:
                value = str(item.ai_summary or "").strip()
            context[f"{field}_{language}"] = value
    return context


def _brief_context_from_archive(record: object) -> dict[str, object]:
    """Build the subset that historical archive rows can prove."""
    score = getattr(record, "score", None)
    return {
        "detailed_summary_zh": str(getattr(record, "summary_zh", "") or ""),
        "detailed_summary_en": str(getattr(record, "summary_en", "") or ""),
        "importance_score": score,
        "references": [],
    }


def _merge_update_brief(
    update: EventUpdate,
    context: Mapping[str, object],
) -> tuple[EventUpdate, bool]:
    changes: dict[str, object] = {}
    for field in _BRIEF_TEXT_FIELDS:
        for language in ("zh", "en"):
            key = f"{field}_{language}"
            incoming = str(context.get(key) or "").strip()
            if incoming and not getattr(update, key):
                changes[key] = incoming

    incoming_score = context.get("importance_score")
    if isinstance(incoming_score, (int, float)) and (
        update.importance_score is None
        or float(incoming_score) > update.importance_score
    ):
        changes["importance_score"] = float(incoming_score)

    references = [reference.model_copy(deep=True) for reference in update.references]
    seen = {reference.url for reference in references}
    incoming_references = context.get("references")
    if isinstance(incoming_references, list):
        for reference in incoming_references:
            if not isinstance(reference, EventReference) or reference.url in seen:
                continue
            references.append(reference.model_copy(deep=True))
            seen.add(reference.url)
    if len(references) != len(update.references):
        changes["references"] = references

    if not changes:
        return update, False
    return update.model_copy(update=changes, deep=True), True


def backfill_event_briefs(
    events: Sequence[TrackedEvent],
    *,
    items: Iterable[ContentItem] = (),
    archive_records: Iterable[object] = (),
) -> tuple[list[TrackedEvent], int]:
    """Hydrate event nodes from existing analyzed items and public archives.

    Text fields are fill-only so a later duplicate source cannot silently
    rewrite an already-published event narrative. Scores and references may
    accumulate because they are independently auditable facts.
    """
    item_by_id = {item.id: item for item in items}
    archive_by_id: dict[str, list[object]] = {}
    for record in archive_records:
        story_id = str(getattr(record, "item_id", "") or "")
        if story_id:
            archive_by_id.setdefault(story_id, []).append(record)

    hydrated: list[TrackedEvent] = []
    changed_updates = 0
    for event in events:
        updates: list[EventUpdate] = []
        event_changed = False
        for update in event.updates:
            current = update.model_copy(deep=True)
            update_changed = False
            for story_id in update.story_ids:
                item = item_by_id.get(story_id)
                if item is not None:
                    current, changed = _merge_update_brief(
                        current, _brief_context_from_item(item)
                    )
                    update_changed = update_changed or changed
                for record in archive_by_id.get(story_id, []):
                    current, changed = _merge_update_brief(
                        current, _brief_context_from_archive(record)
                    )
                    update_changed = update_changed or changed
            updates.append(current)
            if update_changed:
                changed_updates += 1
                event_changed = True
        hydrated.append(
            event.model_copy(update={"updates": updates}, deep=True)
            if event_changed
            else event.model_copy(deep=True)
        )
    return hydrated, changed_updates


def _stable_event_id(story_id: str) -> str:
    digest = hashlib.sha256(
        f"bmtnews-live-event-v1\0{story_id}".encode()
    ).hexdigest()[:16]
    return f"evt_{digest}"


def _stable_update_id(event_id: str, story_id: str) -> str:
    digest = hashlib.sha256(
        f"{event_id}\0{story_id}".encode()
    ).hexdigest()[:16]
    return f"upd_{digest}"


def _event_type(story: StoryEvidence, category: str) -> EventType:
    text = " ".join(
        [category, story.title_zh, story.title_en, *story.tags]
    ).lower()
    if any(key in text for key in ("hack", "exploit", "漏洞", "攻击", "security")):
        return EventType.SECURITY_INCIDENT
    if any(key in text for key in ("lawsuit", "court", "诉讼", "法院", "legal")):
        return EventType.LEGAL_CASE
    if any(key in text for key in ("regulat", "监管", "policy", "sec ")):
        return EventType.REGULATORY_ACTION
    if any(key in text for key in ("governance", "proposal", "vote", "治理", "投票")):
        return EventType.GOVERNANCE
    if any(key in text for key in ("listing", "delist", "exchange", "上币", "下架")):
        return EventType.EXCHANGE_OPERATION
    if any(key in text for key in ("upgrade", "fork", "protocol", "升级", "主网")):
        return EventType.PROTOCOL_CHANGE
    if any(key in text for key in ("launch", "release", "发布", "上线")):
        return EventType.PRODUCT_RELEASE
    if any(key in text for key in ("market", "liquidity", "etf", "市场", "流动性")):
        return EventType.MARKET_STRUCTURE
    return EventType.OTHER


def _category(item: ContentItem) -> str:
    category = str(item.metadata.get("category") or "").lower()
    if "regulation" in category or category.startswith(("macro-", "policy")):
        return "policy"
    if category.startswith(("ai-", "tech-")) or category in {"ai", "technology"}:
        return "technology"
    return "crypto"


def _first_seen(item: ContentItem) -> datetime:
    published = _aware(item.published_at)
    fetched = _aware(item.fetched_at)
    return max(published, fetched)


def _new_event(item: ContentItem, story: StoryEvidence) -> TrackedEvent:
    event_id = _stable_event_id(story.story_id)
    update_id = _stable_update_id(event_id, story.story_id)
    stamp = story.published_at
    first_seen = _first_seen(item)
    title_zh = story.title_zh or story.title_en
    title_en = story.title_en or story.title_zh
    state_zh = story.summary_zh or title_zh
    state_en = story.summary_en or title_en
    signature = signature_for_story(story)
    update = EventUpdate(
        update_id=update_id,
        event_id=event_id,
        occurred_at=stamp,
        published_at=stamp,
        first_seen_at=first_seen,
        time_precision=EventTimePrecision.PUBLISHED,
        update_type=EventUpdateType.INITIAL,
        material_change=True,
        title_zh=title_zh,
        title_en=title_en,
        what_changed_zh=state_zh,
        what_changed_en=state_en,
        current_state_zh=state_zh,
        current_state_en=state_en,
        confidence=0.75,
        story_ids=[story.story_id],
        sources=[_event_source(item)],
    )
    update, _ = _merge_update_brief(update, _brief_context_from_item(item))
    category = _category(item)
    return TrackedEvent(
        event_id=event_id,
        event_type=_event_type(story, category),
        status=EventStatus.MONITORING,
        category=category,
        title_zh=title_zh,
        title_en=title_en,
        current_state_zh=state_zh,
        current_state_en=state_en,
        entities=sorted(signature.entities),
        identifiers=sorted(signature.identifiers),
        topics=sorted(signature.topics),
        first_seen_at=first_seen,
        last_updated_at=first_seen,
        last_material_change_at=first_seen,
        confidence=0.75,
        updates=[update],
    )


def _status_after_update(
    current: EventStatus, update_type: EventUpdateType
) -> EventStatus:
    if update_type is EventUpdateType.RESOLUTION:
        return EventStatus.RESOLVED
    if update_type is EventUpdateType.AFTERMATH:
        return EventStatus.CLOSED
    if update_type is EventUpdateType.CORRECTION:
        return EventStatus.DISPUTED
    if update_type in {EventUpdateType.ESCALATION, EventUpdateType.RESPONSE}:
        return EventStatus.DEVELOPING
    if current in {EventStatus.RESOLVED, EventStatus.CLOSED}:
        return current
    return EventStatus.MONITORING


def _append_material_update(
    event: TrackedEvent,
    item: ContentItem,
    story: StoryEvidence,
    decision: EventRelationDecision,
) -> tuple[TrackedEvent, str]:
    update_id = _stable_update_id(event.event_id, story.story_id)
    first_seen = _first_seen(item)
    update_type = decision.update_type or EventUpdateType.CONFIRMATION
    changed_zh = decision.what_changed_zh or decision.what_changed_en
    changed_en = decision.what_changed_en or decision.what_changed_zh
    state_zh = decision.current_state_zh or changed_zh
    state_en = decision.current_state_en or changed_en
    update = EventUpdate(
        update_id=update_id,
        event_id=event.event_id,
        occurred_at=story.published_at,
        published_at=story.published_at,
        first_seen_at=first_seen,
        time_precision=EventTimePrecision.PUBLISHED,
        update_type=update_type,
        material_change=True,
        title_zh=story.title_zh,
        title_en=story.title_en,
        what_changed_zh=changed_zh,
        what_changed_en=changed_en,
        current_state_zh=state_zh,
        current_state_en=state_en,
        confidence=decision.confidence,
        story_ids=[story.story_id],
        sources=[_event_source(item)],
    )
    update, _ = _merge_update_brief(update, _brief_context_from_item(item))
    signature = signature_for_story(story)
    updates = sorted(
        [*event.updates, update],
        key=lambda row: (row.occurred_at, row.first_seen_at, row.update_id),
    )
    return (
        event.model_copy(
            update={
                "status": _status_after_update(event.status, update_type),
                "current_state_zh": state_zh or event.current_state_zh,
                "current_state_en": state_en or event.current_state_en,
                "entities": sorted({*event.entities, *signature.entities}),
                "identifiers": sorted(
                    {*event.identifiers, *signature.identifiers}
                ),
                "topics": sorted({*event.topics, *signature.topics}),
                "last_updated_at": max(event.last_updated_at, first_seen),
                "last_material_change_at": max(
                    event.last_material_change_at, first_seen
                ),
                "confidence": min(event.confidence, decision.confidence),
                "updates": updates,
            },
            deep=True,
        ),
        update_id,
    )


def _attach_duplicate(
    event: TrackedEvent,
    item: ContentItem,
    story: StoryEvidence,
    decision: EventRelationDecision,
) -> tuple[TrackedEvent, str, bool, bool]:
    updates = [update.model_copy(deep=True) for update in event.updates]
    target_id = decision.target_update_id
    target = next(
        (update for update in updates if update.update_id == target_id),
        None,
    )
    if target is None:
        raise ValueError(
            f"duplicate decision references unknown update {target_id!r}"
        )
    changed = False
    if story.story_id not in target.story_ids:
        target.story_ids.append(story.story_id)
        changed = True
    source = _event_source(item)
    if source.url not in {existing.url for existing in target.sources}:
        target.sources.append(source)
        changed = True
    enriched_target, brief_changed = _merge_update_brief(
        target, _brief_context_from_item(item)
    )
    updates[updates.index(target)] = enriched_target
    first_seen = _first_seen(item)
    return (
        event.model_copy(
            update={
                "last_updated_at": max(event.last_updated_at, first_seen),
                "confidence": min(event.confidence, decision.confidence),
                "updates": updates,
            },
            deep=True,
        ),
        target.update_id,
        changed,
        brief_changed,
    )


async def _default_classifier(
    client: AIClient, event: TrackedEvent, story: StoryEvidence
) -> EventRelationDecision:
    return await classify_event_relation(client, event=event, story=story)


async def update_events(
    items: Iterable[ContentItem],
    events: Sequence[TrackedEvent],
    *,
    client: AIClient | None,
    classifier: RelationClassifier = _default_classifier,
) -> tuple[list[TrackedEvent], IncrementalEventResult]:
    """Attach only unseen stories and return an updated, validated catalog."""
    working = [event.model_copy(deep=True) for event in events]
    assignments = _story_assignment_index(working)
    considered = already_known = classified = material = duplicates = created = errors = 0
    briefs_enriched = 0

    ordered_items = sorted(
        items,
        key=lambda item: (_aware(item.published_at), item.id),
    )
    for item in ordered_items:
        considered += 1
        known = assignments.get(item.id)
        if known is not None:
            event_id, update_id = known
            item.metadata["event_id"], item.metadata["event_update_id"] = known
            event_index = next(
                index for index, event in enumerate(working) if event.event_id == event_id
            )
            event = working[event_index]
            updates = [update.model_copy(deep=True) for update in event.updates]
            update_index = next(
                index for index, update in enumerate(updates) if update.update_id == update_id
            )
            updates[update_index], changed = _merge_update_brief(
                updates[update_index], _brief_context_from_item(item)
            )
            if changed:
                working[event_index] = event.model_copy(
                    update={"updates": updates}, deep=True
                )
                briefs_enriched += 1
            already_known += 1
            continue

        story = story_evidence(item)
        by_id = {event.event_id: event for event in working}
        candidates = retrieve_event_candidates(
            story, working, limit=MAX_RELATION_CANDIDATES
        )
        decisions: list[EventRelationDecision] = []
        if candidates and client is None:
            raise ValueError("an AI client is required for unseen event candidates")
        for candidate in candidates:
            try:
                decisions.append(
                    await classifier(client, by_id[candidate.event_id], story)  # type: ignore[arg-type]
                )
                classified += 1
            except Exception:
                errors += 1
        attachment = select_event_attachment(
            decisions, threshold=ATTACHMENT_THRESHOLD
        )

        if attachment is None:
            event = _new_event(item, story)
            working.append(event)
            update_id = event.updates[0].update_id
            created += 1
        else:
            index = next(
                idx
                for idx, event in enumerate(working)
                if event.event_id == attachment.candidate_event_id
            )
            event = working[index]
            if attachment.relation is EventRelation.DUPLICATE_COVERAGE:
                try:
                    event, update_id, changed, brief_changed = _attach_duplicate(
                        event, item, story, attachment
                    )
                    duplicates += int(changed)
                    briefs_enriched += int(brief_changed)
                except ValueError:
                    # An invalid update target is not allowed to corrupt or
                    # stop the catalog. Keep the story separate and auditable.
                    event = _new_event(item, story)
                    working.append(event)
                    update_id = event.updates[0].update_id
                    created += 1
                    errors += 1
                    item.metadata["event_id"] = event.event_id
                    item.metadata["event_update_id"] = update_id
                    assignments[item.id] = (event.event_id, update_id)
                    continue
            else:
                event, update_id = _append_material_update(
                    event, item, story, attachment
                )
                material += 1
            working[index] = event

        item.metadata["event_id"] = event.event_id
        item.metadata["event_update_id"] = update_id
        assignments[item.id] = (event.event_id, update_id)

    _story_assignment_index(working)
    return working, IncrementalEventResult(
        considered=considered,
        already_known=already_known,
        candidates_classified=classified,
        material_updates=material,
        duplicate_sources=duplicates,
        new_events=created,
        classifier_errors=errors,
        briefs_enriched=briefs_enriched,
    )
