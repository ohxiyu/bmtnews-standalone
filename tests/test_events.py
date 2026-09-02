"""Contract and real-corpus regression tests for event timeline v2."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ai.event_relations import (
    EventRelationError,
    classify_event_relation,
    parse_event_relation,
)
from src.events import (
    EventRelation,
    EventRelationDecision,
    EventSource,
    EventStatus,
    EventType,
    EventUpdate,
    EventUpdateType,
    StoryEvidence,
    TrackedEvent,
    retrieve_event_candidates,
    select_event_attachment,
)


NOW = datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).parent / "fixtures" / "event_candidate_cases.json"


def make_update(
    event_id: str = "evt_example1",
    *,
    update_id: str = "upd_example1",
    occurred_at: datetime = NOW,
    first_seen_at: datetime = NOW,
) -> EventUpdate:
    return EventUpdate(
        update_id=update_id,
        event_id=event_id,
        occurred_at=occurred_at,
        published_at=first_seen_at - timedelta(minutes=5),
        first_seen_at=first_seen_at,
        update_type=EventUpdateType.INITIAL,
        material_change=True,
        what_changed_zh="事件首次被确认。",
        what_changed_en="The event was first confirmed.",
        current_state_zh="事件正在发展。",
        current_state_en="The event is developing.",
        confidence=0.96,
        story_ids=[update_id.replace("upd_", "story_")],
        sources=[
            EventSource(
                url=f"https://example.com/{update_id}",
                label="Example",
                official=False,
            )
        ],
    )


def make_event(
    *,
    event_id: str = "evt_example1",
    entities: list[str] | None = None,
    identifiers: list[str] | None = None,
    topics: list[str] | None = None,
) -> TrackedEvent:
    update = make_update(event_id)
    return TrackedEvent(
        event_id=event_id,
        event_type=EventType.SECURITY_INCIDENT,
        status=EventStatus.DEVELOPING,
        category="crypto",
        title_zh="示例事件",
        title_en="Example event",
        current_state_zh=update.current_state_zh,
        current_state_en=update.current_state_en,
        entities=entities or [],
        identifiers=identifiers or [],
        topics=topics or [],
        first_seen_at=NOW,
        last_updated_at=NOW,
        last_material_change_at=NOW,
        confidence=0.96,
        updates=[update],
    )


def make_story(case: dict) -> StoryEvidence:
    return StoryEvidence(
        story_id=f"story_{case['name'].replace(' ', '_')}",
        url="https://example.com/new-story",
        published_at=NOW + timedelta(hours=1),
        title_en=case["story_title"],
        tags=case["story_tags"],
        identifiers=case["story_identifiers"],
        source_label="Fixture",
    )


def test_event_requires_aware_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        StoryEvidence(
            story_id="story_naive",
            url="https://example.com/naive",
            published_at=datetime(2026, 9, 2, 3, 0),
        )


def test_story_rejects_non_http_source_url() -> None:
    with pytest.raises(ValidationError, match="http or https"):
        StoryEvidence(
            story_id="story_bad_url",
            url="javascript:alert(1)",
            published_at=NOW,
        )


def test_event_rejects_updates_out_of_order() -> None:
    later = make_update(
        update_id="upd_later01",
        occurred_at=NOW + timedelta(hours=2),
        first_seen_at=NOW + timedelta(hours=2),
    )
    earlier = make_update(
        update_id="upd_earlier1",
        occurred_at=NOW + timedelta(hours=1),
        first_seen_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(ValidationError, match="chronologically"):
        TrackedEvent(
            event_id="evt_example1",
            event_type=EventType.SECURITY_INCIDENT,
            status=EventStatus.DEVELOPING,
            category="crypto",
            first_seen_at=NOW,
            last_updated_at=NOW + timedelta(hours=2),
            last_material_change_at=NOW + timedelta(hours=2),
            confidence=0.9,
            updates=[later, earlier],
        )


def test_candidate_gate_uses_real_production_failure_cases() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for index, case in enumerate(payload["cases"], start=1):
        event = make_event(
            event_id=f"evt_case{index:02d}",
            entities=case["event_entities"],
            identifiers=case["event_identifiers"],
            topics=case["event_topics"],
        )
        candidates = retrieve_event_candidates(make_story(case), [event])
        assert bool(candidates) is case["expected_candidate"], case["name"]


def test_candidate_order_is_deterministic_and_limited() -> None:
    story = StoryEvidence(
        story_id="story_roll_back",
        url="https://example.com/rollback",
        published_at=NOW,
        title_en="Cronos rolls back Tectonic exploit",
        tags=["Cronos", "Tectonic", "security"],
    )
    weaker = make_event(event_id="evt_weaker01", entities=["Cronos"])
    stronger = make_event(
        event_id="evt_stronger1", entities=["Cronos", "Tectonic"]
    )
    candidates = retrieve_event_candidates(story, [weaker, stronger], limit=1)
    assert [candidate.event_id for candidate in candidates] == ["evt_stronger1"]
    assert candidates[0].shared_entities == ["cronos", "tectonic"]


def test_relation_contract_never_turns_duplicate_into_update() -> None:
    with pytest.raises(ValidationError, match="duplicate coverage"):
        EventRelationDecision(
            candidate_event_id="evt_example1",
            relation=EventRelation.DUPLICATE_COVERAGE,
            confidence=0.99,
            update_type=EventUpdateType.CONFIRMATION,
            material_change=True,
            what_changed_en="Nothing changed.",
            rationale="It repeats the same facts.",
        )


def test_relation_contract_rejects_existing_target_for_material_update() -> None:
    with pytest.raises(ValidationError, match="must create a new update"):
        EventRelationDecision(
            candidate_event_id="evt_example1",
            target_update_id="upd_existing1",
            relation=EventRelation.SAME_EVENT_UPDATE,
            confidence=0.99,
            update_type=EventUpdateType.CONFIRMATION,
            material_change=True,
            what_changed_en="The situation changed.",
            rationale="A material update needs its own timeline node.",
        )


def test_only_high_confidence_same_or_duplicate_relations_attach() -> None:
    accepted = EventRelationDecision(
        candidate_event_id="evt_example1",
        relation=EventRelation.SAME_EVENT_UPDATE,
        confidence=0.94,
        update_type=EventUpdateType.REMEDIATION,
        material_change=True,
        what_changed_en="Validators restored block production.",
        current_state_en="The network is producing blocks again.",
        rationale="The same exploit led directly to the rollback.",
    )
    uncertain = accepted.model_copy(update={"confidence": 0.72})
    distinct = accepted.model_copy(
        update={
            "relation": EventRelation.RELATED_BUT_DISTINCT,
            "confidence": 0.99,
            "update_type": None,
            "material_change": False,
        }
    )
    assert accepted.should_attach()
    assert not uncertain.should_attach()
    assert not distinct.should_attach()


def test_near_tied_events_are_left_unattached() -> None:
    first = EventRelationDecision(
        candidate_event_id="evt_candidate1",
        relation=EventRelation.SAME_EVENT_UPDATE,
        confidence=0.96,
        update_type=EventUpdateType.CONFIRMATION,
        material_change=True,
        what_changed_en="Loss estimates were confirmed.",
        rationale="The actor and incident details match.",
    )
    second = first.model_copy(
        update={"candidate_event_id": "evt_candidate2", "confidence": 0.94}
    )
    assert select_event_attachment([first, second]) is None
    assert select_event_attachment([first, second], ambiguity_margin=0.01) == first


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict] = []

    async def complete(self, **kwargs) -> str:
        self.calls.append(kwargs)
        return self.response


def test_classifier_uses_strict_json_contract() -> None:
    event = make_event(event_id="evt_tectonic")
    story = StoryEvidence(
        story_id="story_recovery",
        url="https://example.com/recovery",
        published_at=NOW + timedelta(hours=2),
        title_en="Cronos restores the chain after the Tectonic exploit",
        summary_en="Validators rolled the chain back and resumed production.",
        tags=["Cronos", "Tectonic"],
        source_label="Example",
    )
    client = FakeClient(
        json.dumps(
            {
                "candidate_event_id": "evt_tectonic",
                "relation": "same_event_update",
                "confidence": 0.97,
                "update_type": "remediation",
                "material_change": True,
                "what_changed_zh": "验证者完成回滚并恢复出块。",
                "what_changed_en": "Validators completed the rollback and resumed blocks.",
                "current_state_zh": "网络已经恢复出块。",
                "current_state_en": "The network is producing blocks again.",
                "shared_facts": ["Tectonic exploit", "Cronos rollback"],
                "rationale": "The rollback is a direct response to the same exploit.",
            }
        )
    )
    decision = asyncio.run(
        classify_event_relation(client, event=event, story=story)
    )
    assert decision.should_attach()
    assert client.calls[0]["temperature"] == 0.0
    assert client.calls[0]["response_format"] == "json"
    assert "evt_tectonic" in client.calls[0]["user"]


def test_classifier_rejects_changed_candidate_id() -> None:
    response = json.dumps(
        {
            "candidate_event_id": "evt_wrongid",
            "relation": "unrelated",
            "confidence": 0.99,
            "update_type": None,
            "material_change": False,
            "what_changed_zh": "",
            "what_changed_en": "",
            "current_state_zh": "",
            "current_state_en": "",
            "shared_facts": [],
            "rationale": "The stories are unrelated.",
        }
    )
    with pytest.raises(EventRelationError, match="changed the candidate ID"):
        parse_event_relation(response, event_id="evt_expected")
