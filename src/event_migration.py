"""Audited, deterministic migration from legacy threads to event timelines.

The migration is deliberately split into two operations:

``audit`` validates a reviewed plan against an immutable archive fingerprint
and renders a human-readable report without writing archive data. ``apply`` is
guarded by the plan's explicit approval bit and writes only deterministic
derived artifacts.  The production workflow is not wired to ``apply`` until
the report has been reviewed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date as date_type, datetime, time, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ._file_utils import _atomic_write_text
from .archive import ArchiveRecord, load_archive
from .events import (
    EventSource,
    EventStatus,
    EventTimePrecision,
    EventType,
    EventUpdate,
    EventUpdateType,
    StoryEvidence,
    TrackedEvent,
    signature_for_story,
)


DEFAULT_PLAN_PATH = Path("data/event-migration-v1.json")
DEFAULT_EVENT_CATALOG_PATH = Path("docs/_data/events.json")
DEFAULT_LEGACY_MAP_PATH = Path("docs/_data/event-legacy-urls.json")
DEFAULT_EVENT_PAGES_ROOT = Path("docs/events")
DEFAULT_LEGACY_PAGES_ROOT = Path("docs/threads")
DEFAULT_THREAD_INDEX_PATH = Path("docs/_data/threads.json")
EDITION_TZ = timezone(timedelta(hours=8))


class MigrationError(ValueError):
    """The archive and reviewed migration contract do not agree."""


class ReviewDisposition(str, Enum):
    PROGRESSION = "progression"
    COLLAPSE_DUPLICATES = "collapse_duplicates"
    SPLIT_ALL = "split_all"
    SPLIT_GROUPS = "split_groups"


class LegacyUrlAction(str, Enum):
    REDIRECT = "redirect"
    RETIRED_INDEX = "retired_index"


class PlannedUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    story_ids: list[str] = Field(min_length=1)
    update_type: EventUpdateType
    what_changed_zh: str
    what_changed_en: str
    current_state_zh: str = ""
    current_state_en: str = ""

    @model_validator(mode="after")
    def unique_story_ids(self) -> "PlannedUpdate":
        if len(set(self.story_ids)) != len(self.story_ids):
            raise ValueError("planned update story IDs must be unique")
        if not (self.what_changed_zh or self.what_changed_en):
            raise ValueError("planned update must explain what changed")
        return self


class PlannedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{5,79}$")
    title_zh: str
    title_en: str
    event_type: EventType
    status: EventStatus
    category: str = "crypto"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    updates: list[PlannedUpdate] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_membership(self) -> "PlannedEvent":
        story_ids = [story for update in self.updates for story in update.story_ids]
        if len(set(story_ids)) != len(story_ids):
            raise ValueError("a story cannot appear in two updates of one event")
        return self


class LegacyThreadReview(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    legacy_thread_id: str = Field(pattern=r"^t[a-f0-9]{10}$")
    disposition: ReviewDisposition
    legacy_url_action: LegacyUrlAction
    rationale_zh: str = Field(min_length=1)
    rationale_en: str = Field(min_length=1)
    events: list[PlannedEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> "LegacyThreadReview":
        if self.disposition is ReviewDisposition.SPLIT_ALL and self.events:
            raise ValueError("split_all review must not pre-group records")
        if self.disposition is not ReviewDisposition.SPLIT_ALL and not self.events:
            raise ValueError("non-split review requires at least one event")
        if (
            self.legacy_url_action is LegacyUrlAction.REDIRECT
            and len(self.events) != 1
        ):
            raise ValueError("redirect requires exactly one reviewed target event")
        return self


class EventMigrationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: int = 1
    reviewed_through_date: date_type
    source_archive_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_record_count: int = Field(gt=0)
    approved: bool = False
    reviews: list[LegacyThreadReview] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_review_contract(self) -> "EventMigrationPlan":
        legacy_ids = [review.legacy_thread_id for review in self.reviews]
        if len(set(legacy_ids)) != len(legacy_ids):
            raise ValueError("legacy thread reviews must be unique")
        event_keys = [
            event.key for review in self.reviews for event in review.events
        ]
        if len(set(event_keys)) != len(event_keys):
            raise ValueError("reviewed event keys must be globally unique")
        story_ids = [
            story
            for review in self.reviews
            for event in review.events
            for update in event.updates
            for story in update.story_ids
        ]
        duplicates = [key for key, count in Counter(story_ids).items() if count > 1]
        if duplicates:
            raise ValueError(
                "reviewed stories cannot belong to multiple events: "
                + ", ".join(sorted(duplicates))
            )
        return self


class LegacyUrlMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    redirects: dict[str, str] = Field(default_factory=dict)
    retired: dict[str, list[str]] = Field(default_factory=dict)


class MigrationResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    records: list[ArchiveRecord]
    events: list[TrackedEvent]
    legacy_urls: LegacyUrlMap
    reviewed_record_count: int
    default_singleton_count: int


def load_migration_plan(path: Path = DEFAULT_PLAN_PATH) -> EventMigrationPlan:
    try:
        return EventMigrationPlan.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MigrationError(f"cannot read migration plan {path}: {exc}") from exc
    except ValueError as exc:
        raise MigrationError(f"invalid migration plan {path}: {exc}") from exc


def _identity_payload(record: ArchiveRecord) -> dict[str, object]:
    """All reviewed input fields, excluding only migration annotations.

    Deriving this from the model makes newly added archive fields fail the
    fingerprint automatically instead of being silently omitted from review.
    """
    return record.model_dump(
        mode="json", exclude={"event_id", "event_update_id"}
    )


def archive_digest(
    records: Iterable[ArchiveRecord], *, through_date: date_type
) -> tuple[str, int]:
    reviewed = [
        record
        for record in records
        if record.date_value is not None and record.date_value <= through_date
    ]
    reviewed.sort(key=lambda record: (record.date, record.rank, record.item_id))
    payload = [_identity_payload(record) for record in reviewed]
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), len(reviewed)


def stable_event_id(key: str) -> str:
    digest = hashlib.sha256(f"bmtnews-event-v1\0{key}".encode()).hexdigest()[:16]
    return f"evt_{digest}"


def stable_update_id(event_id: str, story_ids: Sequence[str]) -> str:
    joined = "\0".join(sorted(story_ids))
    digest = hashlib.sha256(f"{event_id}\0{joined}".encode()).hexdigest()[:16]
    return f"upd_{digest}"


def _edition_time(date: str) -> datetime:
    parsed = date_type.fromisoformat(date)
    return datetime.combine(parsed, time(hour=8), tzinfo=EDITION_TZ)


def _source_for(record: ArchiveRecord) -> EventSource:
    label = record.source_label.strip()
    if not label:
        label = urlparse(record.url).hostname or record.source_type or "Source"
    return EventSource(
        url=record.url,
        label=label,
        source_type=record.source_type,
        official=False,
    )


def _category_for(records: Sequence[ArchiveRecord], fallback: str = "crypto") -> str:
    categories = [record.top_category or record.category for record in records]
    categories = [value for value in categories if value]
    return Counter(categories).most_common(1)[0][0] if categories else fallback


def _signature_for(record: ArchiveRecord):
    return signature_for_story(
        StoryEvidence(
            story_id=record.item_id,
            url=record.url,
            published_at=_edition_time(record.date),
            title_zh=record.title_zh,
            title_en=record.title_en,
            summary_zh=record.summary_zh,
            summary_en=record.summary_en,
            tags=record.tags,
            source_label=record.source_label,
        )
    )


def _build_reviewed_event(
    plan: PlannedEvent,
    *,
    records_by_id: dict[str, ArchiveRecord],
    legacy_thread_id: str,
) -> tuple[TrackedEvent, dict[str, str]]:
    event_id = stable_event_id(plan.key)
    updates: list[EventUpdate] = []
    assignments: dict[str, str] = {}
    all_records: list[ArchiveRecord] = []
    for planned_update in plan.updates:
        records = [records_by_id[story_id] for story_id in planned_update.story_ids]
        records.sort(key=lambda record: (record.date, record.rank, record.item_id))
        all_records.extend(records)
        update_id = stable_update_id(event_id, planned_update.story_ids)
        stamp = _edition_time(records[0].date)
        sources = []
        seen_urls: set[str] = set()
        for record in records:
            if record.url not in seen_urls:
                seen_urls.add(record.url)
                sources.append(_source_for(record))
            assignments[record.item_id] = update_id
        updates.append(
            EventUpdate(
                update_id=update_id,
                event_id=event_id,
                occurred_at=stamp,
                published_at=stamp,
                first_seen_at=stamp,
                time_precision=EventTimePrecision.EDITION,
                update_type=planned_update.update_type,
                material_change=True,
                title_zh=planned_update.what_changed_zh,
                title_en=planned_update.what_changed_en,
                what_changed_zh=planned_update.what_changed_zh,
                what_changed_en=planned_update.what_changed_en,
                current_state_zh=(
                    planned_update.current_state_zh or planned_update.what_changed_zh
                ),
                current_state_en=(
                    planned_update.current_state_en or planned_update.what_changed_en
                ),
                confidence=plan.confidence,
                story_ids=[record.item_id for record in records],
                sources=sources,
            )
        )
    updates.sort(key=lambda update: (update.occurred_at, update.update_id))
    all_records.sort(key=lambda record: (record.date, record.rank, record.item_id))
    signatures = [_signature_for(record) for record in all_records]
    last = updates[-1]
    return (
        TrackedEvent(
            event_id=event_id,
            event_type=plan.event_type,
            status=plan.status,
            category=plan.category or _category_for(all_records),
            title_zh=plan.title_zh,
            title_en=plan.title_en,
            current_state_zh=last.current_state_zh,
            current_state_en=last.current_state_en,
            entities=sorted({item for sig in signatures for item in sig.entities}),
            identifiers=sorted(
                {item for sig in signatures for item in sig.identifiers}
            ),
            topics=sorted({item for sig in signatures for item in sig.topics}),
            first_seen_at=updates[0].first_seen_at,
            last_updated_at=max(update.first_seen_at for update in updates),
            last_material_change_at=max(
                update.first_seen_at for update in updates if update.material_change
            ),
            confidence=plan.confidence,
            legacy_thread_ids=[legacy_thread_id],
            updates=updates,
        ),
        assignments,
    )


def _build_singleton_event(
    record: ArchiveRecord,
    *,
    legacy_thread_id: str | None = None,
) -> tuple[TrackedEvent, dict[str, str]]:
    key = f"singleton-{record.item_id}"
    event_id = stable_event_id(key)
    update_id = stable_update_id(event_id, [record.item_id])
    stamp = _edition_time(record.date)
    signature = _signature_for(record)
    title_zh = record.title_zh or record.title_en
    title_en = record.title_en or record.title_zh
    update = EventUpdate(
        update_id=update_id,
        event_id=event_id,
        occurred_at=stamp,
        published_at=stamp,
        first_seen_at=stamp,
        time_precision=EventTimePrecision.EDITION,
        update_type=EventUpdateType.INITIAL,
        material_change=True,
        title_zh=title_zh,
        title_en=title_en,
        what_changed_zh=title_zh,
        what_changed_en=title_en,
        current_state_zh=title_zh,
        current_state_en=title_en,
        confidence=0.75,
        story_ids=[record.item_id],
        sources=[_source_for(record)],
    )
    event = TrackedEvent(
        event_id=event_id,
        event_type=EventType.OTHER,
        status=EventStatus.MONITORING,
        category=_category_for([record]),
        title_zh=title_zh,
        title_en=title_en,
        current_state_zh=title_zh,
        current_state_en=title_en,
        entities=sorted(signature.entities),
        identifiers=sorted(signature.identifiers),
        topics=sorted(signature.topics),
        first_seen_at=stamp,
        last_updated_at=stamp,
        last_material_change_at=stamp,
        confidence=0.75,
        legacy_thread_ids=[legacy_thread_id] if legacy_thread_id else [],
        updates=[update],
    )
    return event, {record.item_id: update_id}


def _public_legacy_threads(
    records: Sequence[ArchiveRecord], *, through_date: date_type
) -> set[str]:
    dates: dict[str, set[str]] = {}
    for record in records:
        if (
            record.thread_id
            and record.date_value is not None
            and record.date_value <= through_date
        ):
            dates.setdefault(record.thread_id, set()).add(record.date)
    return {thread_id for thread_id, values in dates.items() if len(values) >= 2}


def build_migration(
    records: Sequence[ArchiveRecord], plan: EventMigrationPlan
) -> MigrationResult:
    """Validate the reviewed plan and build an in-memory deterministic result."""
    digest, count = archive_digest(records, through_date=plan.reviewed_through_date)
    if (digest, count) != (plan.source_archive_digest, plan.source_record_count):
        raise MigrationError(
            "reviewed archive fingerprint changed: "
            f"expected {plan.source_record_count}/{plan.source_archive_digest}, "
            f"got {count}/{digest}"
        )

    records_by_id: dict[str, ArchiveRecord] = {}
    for record in records:
        if record.item_id in records_by_id:
            raise MigrationError(f"duplicate archive item_id: {record.item_id}")
        records_by_id[record.item_id] = record

    reviewed_ids = {review.legacy_thread_id for review in plan.reviews}
    public_ids = _public_legacy_threads(
        records, through_date=plan.reviewed_through_date
    )
    if reviewed_ids != public_ids:
        missing = sorted(public_ids - reviewed_ids)
        extra = sorted(reviewed_ids - public_ids)
        raise MigrationError(
            f"review coverage mismatch; missing={missing}, extra={extra}"
        )

    events: list[TrackedEvent] = []
    event_for_story: dict[str, str] = {}
    update_for_story: dict[str, str] = {}
    redirects: dict[str, str] = {}
    retired: dict[str, list[str]] = {}
    reviewed_story_ids: set[str] = set()

    for review in sorted(plan.reviews, key=lambda item: item.legacy_thread_id):
        legacy_records = [
            record
            for record in records
            if record.thread_id == review.legacy_thread_id
            and record.date_value is not None
            and record.date_value <= plan.reviewed_through_date
        ]
        legacy_story_ids = {record.item_id for record in legacy_records}
        target_ids: list[str] = []
        grouped_legacy_ids: set[str] = set()

        for planned_event in review.events:
            story_ids = {
                story_id
                for update in planned_event.updates
                for story_id in update.story_ids
            }
            unknown = story_ids - records_by_id.keys()
            if unknown:
                raise MigrationError(
                    f"{review.legacy_thread_id} references unknown stories: "
                    + ", ".join(sorted(unknown))
                )
            grouped_legacy_ids.update(story_ids & legacy_story_ids)
            overlap = story_ids & event_for_story.keys()
            if overlap:
                raise MigrationError(
                    "story assigned twice during migration: "
                    + ", ".join(sorted(overlap))
                )
            event, assignments = _build_reviewed_event(
                planned_event,
                records_by_id=records_by_id,
                legacy_thread_id=review.legacy_thread_id,
            )
            events.append(event)
            target_ids.append(event.event_id)
            for story_id, update_id in assignments.items():
                event_for_story[story_id] = event.event_id
                update_for_story[story_id] = update_id
                reviewed_story_ids.add(story_id)

        ungrouped = legacy_story_ids - grouped_legacy_ids
        if review.disposition not in {
            ReviewDisposition.SPLIT_ALL,
            ReviewDisposition.SPLIT_GROUPS,
        } and ungrouped:
            raise MigrationError(
                f"{review.legacy_thread_id} leaves reviewed stories ungrouped: "
                + ", ".join(sorted(ungrouped))
            )
        for story_id in sorted(ungrouped):
            record = records_by_id[story_id]
            event, assignments = _build_singleton_event(
                record, legacy_thread_id=review.legacy_thread_id
            )
            events.append(event)
            target_ids.append(event.event_id)
            event_for_story[story_id] = event.event_id
            update_for_story.update(assignments)
            reviewed_story_ids.add(story_id)

        target_ids = sorted(set(target_ids))
        if review.legacy_url_action is LegacyUrlAction.REDIRECT:
            if len(target_ids) != 1:
                raise MigrationError(
                    f"{review.legacy_thread_id} redirect resolved to {len(target_ids)} targets"
                )
            redirects[review.legacy_thread_id] = target_ids[0]
        else:
            retired[review.legacy_thread_id] = target_ids

    default_singletons = 0
    for record in sorted(records, key=lambda item: (item.date, item.rank, item.item_id)):
        if record.item_id in event_for_story:
            continue
        event, assignments = _build_singleton_event(record)
        events.append(event)
        event_for_story[record.item_id] = event.event_id
        update_for_story.update(assignments)
        default_singletons += 1

    migrated_records = [
        record.model_copy(
            update={
                "event_id": event_for_story[record.item_id],
                "event_update_id": update_for_story[record.item_id],
            }
        )
        for record in records
    ]
    migrated_records.sort(key=lambda item: (item.date, item.rank, item.item_id))
    events.sort(key=lambda event: (event.first_seen_at, event.event_id))
    return MigrationResult(
        records=migrated_records,
        events=events,
        legacy_urls=LegacyUrlMap(redirects=redirects, retired=retired),
        reviewed_record_count=len(reviewed_story_ids),
        default_singleton_count=default_singletons,
    )


def render_audit_report(
    records: Sequence[ArchiveRecord],
    plan: EventMigrationPlan,
    result: MigrationResult,
    *,
    source_revision: str = "",
) -> str:
    by_id = {record.item_id: record for record in records}
    lines = [
        "# Event archive migration audit",
        "",
        "> This report is review-only. It does not modify `gh-pages` or production data.",
        "",
        "## Snapshot",
        "",
        f"- Source revision: `{source_revision or 'not recorded'}`",
        f"- Reviewed through: `{plan.reviewed_through_date.isoformat()}`",
        f"- Archive fingerprint: `{plan.source_archive_digest}`",
        f"- Reviewed archive records: {plan.source_record_count}",
        f"- Public legacy threads reviewed: {len(plan.reviews)}",
        f"- Plan approval: `{'approved' if plan.approved else 'pending'}`",
        f"- Resulting events: {len(result.events)}",
        f"- Records covered by explicit review: {result.reviewed_record_count}",
        f"- Conservative singleton defaults: {result.default_singleton_count}",
        "",
        "## Review summary",
        "",
        "| Legacy URL | Decision | New targets | URL handling | Reason |",
        "|---|---:|---:|---|---|",
    ]
    for review in sorted(plan.reviews, key=lambda item: item.legacy_thread_id):
        targets = (
            1
            if review.legacy_url_action is LegacyUrlAction.REDIRECT
            else len(result.legacy_urls.retired[review.legacy_thread_id])
        )
        lines.append(
            f"| `/threads/{review.legacy_thread_id}/` "
            f"| `{review.disposition.value}` | {targets} "
            f"| `{review.legacy_url_action.value}` | {review.rationale_zh} |"
        )

    lines.extend(["", "## Detailed decisions", ""])
    for review in sorted(plan.reviews, key=lambda item: item.legacy_thread_id):
        lines.extend(
            [
                f"### `{review.legacy_thread_id}` — `{review.disposition.value}`",
                "",
                review.rationale_zh,
                "",
            ]
        )
        legacy_records = [
            record
            for record in records
            if record.thread_id == review.legacy_thread_id
            and record.date_value is not None
            and record.date_value <= plan.reviewed_through_date
        ]
        planned_ids = {
            story_id
            for event in review.events
            for update in event.updates
            for story_id in update.story_ids
        }
        for event in review.events:
            lines.extend(
                [
                    f"- Event `{stable_event_id(event.key)}`: "
                    f"{event.title_zh} / {event.title_en}",
                ]
            )
            for index, update in enumerate(event.updates, start=1):
                labels = []
                for story_id in update.story_ids:
                    record = by_id[story_id]
                    labels.append(f"{record.date} · {record.title_en or record.title_zh}")
                lines.append(
                    f"  {index}. `{update.update_type.value}` — "
                    f"{update.what_changed_zh} Sources: " + " | ".join(labels)
                )
        for record in legacy_records:
            if record.item_id not in planned_ids:
                lines.append(
                    f"- Separate event: {record.date} · "
                    f"{record.title_en or record.title_zh}"
                )
        lines.append("")

    lines.extend(["", "## Approval gate", ""])
    if plan.approved:
        lines.extend(
            [
                "The owner approved this reviewed plan. Production writes still occur "
                "only through the guarded `apply` command in GitHub Actions; the "
                "archive fingerprint must match before any file is written.",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "`apply` must refuse this plan while `approved` is `false`. After "
                "review, the approval change, production workflow wiring, "
                "idempotence proof, and legacy-page rendering are completed in this "
                "same PR before merge.",
                "",
            ]
        )
    return "\n".join(lines)


def _catalog_payload(plan: EventMigrationPlan, result: MigrationResult) -> str:
    payload = {
        "schema_version": 1,
        "reviewed_through_date": plan.reviewed_through_date.isoformat(),
        "source_archive_digest": plan.source_archive_digest,
        "events": [event.model_dump(mode="json") for event in result.events],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def apply_migration(
    records: Sequence[ArchiveRecord],
    plan: EventMigrationPlan,
    *,
    archive_root: Path,
    catalog_path: Path = DEFAULT_EVENT_CATALOG_PATH,
    legacy_map_path: Path = DEFAULT_LEGACY_MAP_PATH,
    events_root: Path = DEFAULT_EVENT_PAGES_ROOT,
    legacy_pages_root: Path = DEFAULT_LEGACY_PAGES_ROOT,
    thread_index_path: Path = DEFAULT_THREAD_INDEX_PATH,
    languages: Sequence[str] = ("zh", "en"),
) -> MigrationResult:
    if not plan.approved:
        raise MigrationError("migration plan is not approved; refusing to write")
    result = build_migration(records, plan)
    by_month: dict[str, list[ArchiveRecord]] = {}
    for record in result.records:
        by_month.setdefault(record.date[:7], []).append(record)
    archive_root.mkdir(parents=True, exist_ok=True)
    for month, month_records in sorted(by_month.items()):
        payload = "\n".join(
            record.model_dump_json(exclude_none=False) for record in month_records
        )
        _atomic_write_text(archive_root / f"{month}.jsonl", payload + "\n")
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_map_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(catalog_path, _catalog_payload(plan, result))
    _atomic_write_text(
        legacy_map_path,
        json.dumps(
            result.legacy_urls.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
    )
    from .site_pages import publish_event_compatibility_pages

    publish_event_compatibility_pages(
        result.events,
        result.legacy_urls.redirects,
        result.legacy_urls.retired,
        languages,
        events_root=events_root,
        threads_root=legacy_pages_root,
        thread_index_path=thread_index_path,
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("audit", "apply"))
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN_PATH)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--source-revision", default="")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_EVENT_CATALOG_PATH)
    parser.add_argument("--legacy-map", type=Path, default=DEFAULT_LEGACY_MAP_PATH)
    parser.add_argument("--events-root", type=Path, default=DEFAULT_EVENT_PAGES_ROOT)
    parser.add_argument(
        "--legacy-pages-root", type=Path, default=DEFAULT_LEGACY_PAGES_ROOT
    )
    parser.add_argument(
        "--thread-index", type=Path, default=DEFAULT_THREAD_INDEX_PATH
    )
    args = parser.parse_args(argv)

    plan = load_migration_plan(args.plan)
    records = load_archive(root=args.archive_root, months=120)
    result = build_migration(records, plan)
    if args.report:
        report = render_audit_report(
            records, plan, result, source_revision=args.source_revision
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(args.report, report)
    if args.mode == "apply":
        apply_migration(
            records,
            plan,
            archive_root=args.archive_root,
            catalog_path=args.catalog,
            legacy_map_path=args.legacy_map,
            events_root=args.events_root,
            legacy_pages_root=args.legacy_pages_root,
            thread_index_path=args.thread_index,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
