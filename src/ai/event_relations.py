"""AI boundary for deciding how a new story relates to an event candidate."""

from __future__ import annotations

import json

from pydantic import ValidationError

from ..events import EventRelation, EventRelationDecision, StoryEvidence, TrackedEvent
from .client import AIClient
from .prompts import EVENT_RELATION_SYSTEM, EVENT_RELATION_USER
from .utils import parse_json_response


class EventRelationError(ValueError):
    """Raised when a semantic event decision is missing or invalid."""


def _event_context(event: TrackedEvent) -> dict:
    recent_updates = event.updates[-5:]
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "status": event.status.value,
        "title_zh": event.title_zh,
        "title_en": event.title_en,
        "current_state_zh": event.current_state_zh,
        "current_state_en": event.current_state_en,
        "entities": event.entities,
        "identifiers": event.identifiers,
        "recent_updates": [
            {
                "update_id": update.update_id,
                "occurred_at": update.occurred_at.isoformat(),
                "update_type": update.update_type.value,
                "what_changed_zh": update.what_changed_zh,
                "what_changed_en": update.what_changed_en,
            }
            for update in recent_updates
        ],
    }


def _story_context(story: StoryEvidence) -> dict:
    return {
        "story_id": story.story_id,
        "url": story.url,
        "published_at": story.published_at.isoformat(),
        "title_zh": story.title_zh,
        "title_en": story.title_en,
        "summary_zh": story.summary_zh,
        "summary_en": story.summary_en,
        "tags": story.tags,
        "source_label": story.source_label,
        "source_excerpt": story.source_excerpt,
        "evidence_quality": story.evidence_quality,
    }


def parse_event_relation(response: str, *, event_id: str) -> EventRelationDecision:
    payload = parse_json_response(response)
    if not isinstance(payload, dict):
        raise EventRelationError("event relation response was not a JSON object")
    try:
        decision = EventRelationDecision.model_validate(payload)
    except ValidationError as exc:
        raise EventRelationError("event relation response failed validation") from exc
    if decision.candidate_event_id != event_id:
        raise EventRelationError("event relation response changed the candidate ID")
    return decision


async def classify_event_relation(
    client: AIClient,
    *,
    event: TrackedEvent,
    story: StoryEvidence,
) -> EventRelationDecision:
    """Classify one prefiltered pair with a strict, auditable JSON contract."""
    response = await client.complete(
        system=EVENT_RELATION_SYSTEM,
        user=EVENT_RELATION_USER.format(
            event=json.dumps(_event_context(event), ensure_ascii=False, indent=2),
            story=json.dumps(_story_context(story), ensure_ascii=False, indent=2),
        ),
        temperature=0.0,
        max_tokens=4096,
        response_format="json",
    )
    decision = parse_event_relation(response, event_id=event.event_id)
    if (
        decision.relation is EventRelation.SAME_EVENT_UPDATE
        and story.evidence_quality == "headline_only"
    ):
        raise EventRelationError("headline-only evidence cannot confirm a material change")
    return decision
