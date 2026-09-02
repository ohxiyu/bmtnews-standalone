"""Domain models and conservative candidate retrieval for event timelines.

The legacy ``threads`` module groups stories directly.  This module separates
the durable event from the evidence updates that describe how it changed.
It is intentionally not wired into publishing yet: PR 2 migrates the archive
only after the candidate and relation decisions have been reviewed.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventType(str, Enum):
    SECURITY_INCIDENT = "security_incident"
    REGULATORY_ACTION = "regulatory_action"
    LEGAL_CASE = "legal_case"
    GOVERNANCE = "governance"
    PRODUCT_RELEASE = "product_release"
    EXCHANGE_OPERATION = "exchange_operation"
    PROTOCOL_CHANGE = "protocol_change"
    MARKET_STRUCTURE = "market_structure"
    OTHER = "other"


class EventStatus(str, Enum):
    DEVELOPING = "developing"
    MONITORING = "monitoring"
    RESOLVED = "resolved"
    CLOSED = "closed"
    DISPUTED = "disputed"


class EventUpdateType(str, Enum):
    INITIAL = "initial"
    CONFIRMATION = "confirmation"
    ESCALATION = "escalation"
    RESPONSE = "response"
    REMEDIATION = "remediation"
    RESOLUTION = "resolution"
    AFTERMATH = "aftermath"
    CORRECTION = "correction"


class EventRelation(str, Enum):
    SAME_EVENT_UPDATE = "same_event_update"
    DUPLICATE_COVERAGE = "duplicate_coverage"
    RELATED_BUT_DISTINCT = "related_but_distinct"
    UNRELATED = "unrelated"


class EventSource(BaseModel):
    """One public source supporting an event update."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str
    label: str
    source_type: str = ""
    official: bool = False

    @field_validator("url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("event source URL must use http or https")
        return value


class EventUpdate(BaseModel):
    """A material change or confirmation within one durable event."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    update_id: str = Field(pattern=r"^upd_[a-z0-9_-]{6,80}$")
    event_id: str = Field(pattern=r"^evt_[a-z0-9_-]{6,80}$")
    occurred_at: datetime
    published_at: datetime
    first_seen_at: datetime
    update_type: EventUpdateType
    material_change: bool = True
    title_zh: str = ""
    title_en: str = ""
    what_changed_zh: str = ""
    what_changed_en: str = ""
    current_state_zh: str = ""
    current_state_en: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    story_ids: list[str] = Field(min_length=1)
    sources: list[EventSource] = Field(min_length=1)

    @field_validator("occurred_at", "published_at", "first_seen_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_timeline_order(self) -> "EventUpdate":
        if self.published_at > self.first_seen_at:
            raise ValueError("first_seen_at cannot precede publication")
        if self.material_change and not (
            self.what_changed_zh or self.what_changed_en
        ):
            raise ValueError("material updates must explain what changed")
        return self


class TrackedEvent(BaseModel):
    """Stable event identity plus its chronologically ordered updates."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: int = 1
    event_id: str = Field(pattern=r"^evt_[a-z0-9_-]{6,80}$")
    event_type: EventType
    status: EventStatus
    category: str
    title_zh: str = ""
    title_en: str = ""
    current_state_zh: str = ""
    current_state_en: str = ""
    entities: list[str] = Field(default_factory=list)
    identifiers: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    last_updated_at: datetime
    last_material_change_at: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    legacy_thread_ids: list[str] = Field(default_factory=list)
    updates: list[EventUpdate] = Field(min_length=1)

    @field_validator(
        "first_seen_at", "last_updated_at", "last_material_change_at"
    )
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_event_history(self) -> "TrackedEvent":
        if self.first_seen_at > self.last_material_change_at:
            raise ValueError("last material change cannot precede first seen")
        if self.last_material_change_at > self.last_updated_at:
            raise ValueError("last material change cannot follow last update")

        update_ids: set[str] = set()
        order: list[tuple[datetime, datetime, str]] = []
        for update in self.updates:
            if update.event_id != self.event_id:
                raise ValueError("every update must reference its parent event")
            if update.update_id in update_ids:
                raise ValueError("event update IDs must be unique")
            update_ids.add(update.update_id)
            order.append(
                (update.occurred_at, update.first_seen_at, update.update_id)
            )
        if order != sorted(order):
            raise ValueError("event updates must be stored chronologically")
        if max(update.first_seen_at for update in self.updates) > self.last_updated_at:
            raise ValueError("last_updated_at must include every stored update")
        return self


class StoryEvidence(BaseModel):
    """The bounded story fields sent to candidate retrieval and classification."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    story_id: str
    url: str
    published_at: datetime
    title_zh: str = ""
    title_en: str = ""
    summary_zh: str = ""
    summary_en: str = ""
    tags: list[str] = Field(default_factory=list)
    source_label: str = ""
    entities: list[str] = Field(default_factory=list)
    identifiers: list[str] = Field(default_factory=list)

    @field_validator("url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("story URL must use http or https")
        return value

    @field_validator("published_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("story timestamps must be timezone-aware")
        return value


class EventSignature(BaseModel):
    """Comparable hard facts used only to retrieve plausible events."""

    model_config = ConfigDict(frozen=True)

    entities: frozenset[str] = frozenset()
    identifiers: frozenset[str] = frozenset()
    topics: frozenset[str] = frozenset()


class EventMatchCandidate(BaseModel):
    """Auditable reason an existing event should reach semantic review."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    score: float = Field(ge=0.0)
    shared_entities: list[str] = Field(default_factory=list)
    shared_identifiers: list[str] = Field(default_factory=list)
    shared_topics: list[str] = Field(default_factory=list)


class EventRelationDecision(BaseModel):
    """Structured semantic decision for one story/event candidate pair."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    candidate_event_id: str = Field(pattern=r"^evt_[a-z0-9_-]{6,80}$")
    relation: EventRelation
    confidence: float = Field(ge=0.0, le=1.0)
    update_type: EventUpdateType | None = None
    material_change: bool = False
    what_changed_zh: str = ""
    what_changed_en: str = ""
    current_state_zh: str = ""
    current_state_en: str = ""
    shared_facts: list[str] = Field(default_factory=list)
    rationale: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_relation_contract(self) -> "EventRelationDecision":
        if self.relation is EventRelation.SAME_EVENT_UPDATE:
            if not self.material_change or self.update_type is None:
                raise ValueError(
                    "same_event_update requires a material change and update type"
                )
            if not (self.what_changed_zh or self.what_changed_en):
                raise ValueError("same_event_update must explain what changed")
        elif self.relation is EventRelation.DUPLICATE_COVERAGE:
            if self.material_change or self.update_type is not None:
                raise ValueError("duplicate coverage cannot create an update")
        elif self.material_change or self.update_type is not None:
            raise ValueError("distinct or unrelated stories cannot update the event")
        return self

    def should_attach(self, *, threshold: float = 0.90) -> bool:
        """Whether unattended publishing may attach this story to the event."""
        return self.confidence >= threshold and self.relation in {
            EventRelation.SAME_EVENT_UPDATE,
            EventRelation.DUPLICATE_COVERAGE,
        }


_GENERIC_TOPICS = {
    "ai",
    "ai-agents",
    "banking",
    "bitcoin",
    "blockchain",
    "crypto",
    "crypto-exchange",
    "crypto-markets",
    "defi",
    "digital-assets",
    "engineering",
    "ethereum",
    "exchange",
    "exploit",
    "financial-services",
    "governance",
    "hardware-wallet",
    "institutional-adoption",
    "lending",
    "market-structure",
    "on-chain-security",
    "onchain",
    "payments",
    "policy",
    "price-manipulation",
    "protocol",
    "regulation",
    "security",
    "security-vulnerability",
    "stablecoin",
    "technology",
    "tokenization",
    "trading",
    "traditional-finance",
}

_GENERIC_NAMES = {
    "ai",
    "act",
    "bank",
    "bitcoin",
    "blockchain",
    "btc",
    "crypto",
    "defi",
    "eth",
    "ethereum",
    "finance",
    "mainnet",
    "network",
    "protocol",
    "security",
    "the",
    "usd",
}

_LATIN_NAME = re.compile(
    r"(?<![A-Za-z0-9])[A-Z][A-Za-z0-9]{2,}(?![A-Za-z0-9])"
)
_CVE = re.compile(r"\bCVE-\d{4}-\d{4,8}\b", re.IGNORECASE)
_PROPOSAL = re.compile(r"\b[A-Z]{2,12}-\d{1,8}\b")
_TRANSACTION = re.compile(r"\b0x[a-fA-F0-9]{16,64}\b")


def normalize_event_key(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    text = re.sub(r"[\s_/]+", "-", text)
    text = re.sub(r"[^a-z0-9一-鿿-]", "", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(r"[^a-z0-9一-鿿]", "", normalized)


def _specific_topics(tags: Iterable[str]) -> set[str]:
    return {
        key
        for key in (normalize_event_key(tag) for tag in tags)
        if key and key not in _GENERIC_TOPICS
    }


def _title_entities(titles: str, tags: Iterable[str]) -> set[str]:
    names = {
        normalize_event_key(match.group(0))
        for match in _LATIN_NAME.finditer(titles)
    }
    names -= _GENERIC_NAMES

    compact_title = _compact(titles)
    for tag in _specific_topics(tags):
        compact_tag = _compact(tag)
        if len(compact_tag) >= 3 and compact_tag in compact_title:
            names.add(tag)
    return names


def _hard_identifiers(text: str) -> set[str]:
    values = {
        match.group(0).lower()
        for pattern in (_CVE, _PROPOSAL, _TRANSACTION)
        for match in pattern.finditer(text)
    }
    return values


def signature_for_story(story: StoryEvidence) -> EventSignature:
    titles = " ".join(filter(None, (story.title_zh, story.title_en)))
    all_text = " ".join(
        filter(None, (titles, story.summary_zh, story.summary_en))
    )
    entities = _title_entities(titles, story.tags)
    entities.update(
        key for key in map(normalize_event_key, story.entities) if key
    )
    identifiers = _hard_identifiers(all_text)
    identifiers.update(
        key for key in map(normalize_event_key, story.identifiers) if key
    )
    return EventSignature(
        entities=frozenset(entities),
        identifiers=frozenset(identifiers),
        topics=frozenset(_specific_topics(story.tags)),
    )


def signature_for_event(event: TrackedEvent) -> EventSignature:
    return EventSignature(
        entities=frozenset(
            key for key in map(normalize_event_key, event.entities) if key
        ),
        identifiers=frozenset(
            key for key in map(normalize_event_key, event.identifiers) if key
        ),
        topics=frozenset(_specific_topics(event.topics)),
    )


def retrieve_event_candidates(
    story: StoryEvidence,
    events: Sequence[TrackedEvent],
    *,
    limit: int = 5,
) -> list[EventMatchCandidate]:
    """Return plausible events for semantic review, never final membership.

    A hard shared identifier or named entity opens the gate.  Two specific
    shared topics also open it for cases where a product name is absent from
    one headline.  Generic industry labels never create a candidate alone.
    """
    story_signature = signature_for_story(story)
    candidates: list[EventMatchCandidate] = []
    for event in events:
        event_signature = signature_for_event(event)
        shared_entities = sorted(
            story_signature.entities & event_signature.entities
        )
        shared_identifiers = sorted(
            story_signature.identifiers & event_signature.identifiers
        )
        shared_topics = sorted(story_signature.topics & event_signature.topics)
        if not shared_identifiers and not shared_entities and len(shared_topics) < 2:
            continue
        score = (
            5.0 * len(shared_identifiers)
            + 3.0 * len(shared_entities)
            + 0.5 * len(shared_topics)
        )
        candidates.append(
            EventMatchCandidate(
                event_id=event.event_id,
                score=score,
                shared_entities=shared_entities,
                shared_identifiers=shared_identifiers,
                shared_topics=shared_topics,
            )
        )
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.event_id))
    return candidates[: max(0, limit)]


def select_event_attachment(
    decisions: Sequence[EventRelationDecision],
    *,
    threshold: float = 0.90,
    ambiguity_margin: float = 0.05,
) -> EventRelationDecision | None:
    """Select one safe attachment or leave an ambiguous story unattached.

    A high score is not enough when two different events are nearly tied.
    Leaving the story separate is recoverable; silently merging two event
    histories is not.
    """
    eligible = [
        decision
        for decision in decisions
        if decision.should_attach(threshold=threshold)
    ]
    eligible.sort(
        key=lambda decision: (-decision.confidence, decision.candidate_event_id)
    )
    if not eligible:
        return None
    if len(eligible) > 1:
        top, runner_up = eligible[:2]
        if (
            top.candidate_event_id != runner_up.candidate_event_id
            and top.confidence - runner_up.confidence < ambiguity_margin
        ):
            return None
    return eligible[0]
