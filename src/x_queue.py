"""Planned X delivery: each edition is planned once, then sent from storage.

Why this shape
--------------
Posting used to compose and send in the same step and only record a post
after X confirmed it. A response lost to a timeout therefore looked like a
failure, and the next slot composed a *different* text and posted again.
The queue now separates the two concerns:

* **Planning** happens once per edition (and again only when a republish
  changes a story that has not been attempted yet). It picks the stories,
  writes their exact text, and fixes the schedule. Everything is persisted
  before anything is sent.
* **Sending** only ever posts text that is already in the queue, and writes a
  ``pending`` checkpoint *before* the request. A run that dies after the
  checkpoint leaves ``pending`` behind, which the next run turns into
  ``unknown``. Unknown outcomes are never retried automatically; a human
  checks the account and resolves them.

Stories are identified by a hash of their canonical URL, never by rank, so a
republished edition cannot shift a slot onto a story that was already sent.

This module is deliberately stdlib-only: the workflow runs :func:`main` as a
cheap gate with the runner's system Python before installing dependencies.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import random
import subprocess
from dataclasses import dataclass
from datetime import date as date_type, datetime, time, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from ._file_utils import _atomic_write_text

DEFAULT_STATE_PATH = Path("data/x-queue.json")
QUEUE_RELATIVE_PATH = Path("data/x-queue.json")
QUEUE_BRANCH = "x-queue"
VERSION = 2

# planned  - scheduled, not attempted
# pending  - checkpointed immediately before the request; outcome not yet known
# sent     - X confirmed the post and returned its id
# unknown  - the request may or may not have landed; never retried automatically
# failed   - X definitively rejected it (auth, permission, validation)
# expired  - never attempted, deadline passed
# skipped  - never attempted, story left the edition
# void     - set by a human who confirmed the post does not exist and dropped it
STATUSES = frozenset(
    {"planned", "pending", "sent", "unknown", "failed", "expired", "skipped", "void"}
)
# A story in any of these states is never selected again: it was attempted, or
# a human decided about it. Re-arming any of them risks a duplicate post.
USED_STATUSES = frozenset({"pending", "sent", "unknown", "failed", "void"})
# States that need a person to look at the account.
ATTENTION_STATUSES = frozenset({"pending", "unknown", "failed"})


class QueueError(ValueError):
    """The persisted queue cannot be trusted; refuse to act on it."""


@dataclass(frozen=True)
class Settings:
    """Scheduling rules, taken from ``x_delivery`` in the config."""

    timezone: str = "Asia/Shanghai"
    languages: tuple[str, ...] = ("zh",)
    items: int = 2
    gap_min_minutes: int = 180
    gap_max_minutes: int = 360
    expected_publish: time = time(7, 26)
    max_publish_delay_minutes: int = 360
    expire_after_minutes: int = 360
    window_end: time = time(23, 30)
    history_days: int = 7

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @classmethod
    def from_mapping(cls, x_delivery: dict, timezone: str) -> "Settings":
        def clock(value: object, default: time) -> time:
            if not value:
                return default
            hour, minute = str(value).split(":")
            return time(int(hour), int(minute))

        defaults = cls()
        return cls(
            timezone=timezone or defaults.timezone,
            languages=tuple(x_delivery.get("languages") or defaults.languages),
            items=int(x_delivery.get("drip_items", defaults.items)),
            gap_min_minutes=int(
                x_delivery.get("drip_gap_min_minutes", defaults.gap_min_minutes)
            ),
            gap_max_minutes=int(
                x_delivery.get("drip_gap_max_minutes", defaults.gap_max_minutes)
            ),
            expected_publish=clock(
                x_delivery.get("expected_publish_time"), defaults.expected_publish
            ),
            max_publish_delay_minutes=int(
                x_delivery.get(
                    "max_publish_delay_minutes", defaults.max_publish_delay_minutes
                )
            ),
            expire_after_minutes=int(
                x_delivery.get("expire_after_minutes", defaults.expire_after_minutes)
            ),
            window_end=clock(x_delivery.get("window_end"), defaults.window_end),
            history_days=int(x_delivery.get("history_days", defaults.history_days)),
        )


@dataclass
class Candidate:
    """One published story that could be posted, in edition rank order."""

    key: str
    rank: int
    title: str
    source_sha256: str
    item: object = None


# (text, compose kind "ai"/"template", fallback reason or "")
ComposeResult = tuple[str, str, str]
Compose = Callable[[object, str], Awaitable[ComposeResult]]


def story_key_for_identity(identity: str) -> str:
    """Stable story id: the hash of the canonical URL, never the rank."""
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(value: object, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise QueueError(f"invalid timestamp in {field}") from exc
    if parsed.tzinfo is None:
        raise QueueError(f"timestamp without timezone in {field}")
    return parsed


def normalize_stamp(value: object) -> str:
    """One canonical text form for a feed timestamp.

    The gate reads the raw JSON (``...Z``) while the pipeline sees a parsed
    datetime (``...+00:00``). Comparing them as-is would make every poll look
    like a republish.
    """
    if value in (None, ""):
        return ""
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if moment.tzinfo is None:
        return moment.isoformat()
    return moment.astimezone(ZoneInfo("UTC")).isoformat()


def empty_state() -> dict:
    return {"version": VERSION, "editions": {}}


# ---------------------------------------------------------------------------
# Loading, validation and migration
# ---------------------------------------------------------------------------


def _blank_job(language: str, slot: int, story_key: str) -> dict:
    return {
        "language": language,
        "slot": slot,
        "story_key": story_key,
        "rank": None,
        "title": "",
        "text": "",
        "text_sha256": "",
        "source_sha256": "",
        "compose": "",
        "fallback_reason": "",
        "gap_minutes": None,
        "due_at": None,
        "deadline": None,
        "status": "planned",
        "tweet_id": "",
        "attempted_at": None,
        "detail": "",
        "planned_at": None,
    }


def _migrate_v1(payload: dict, now: datetime) -> dict:
    """Carry v1 rank receipts forward as story-keyed jobs.

    v1 recorded posted ranks per language plus the canonical URLs of the
    selection those ranks referred to. A rank with a known identity becomes a
    ``sent`` job. A rank without one cannot be tied to a story, so it becomes
    ``unknown`` for a person to settle instead of being guessed.
    """
    day = str(payload.get("date") or "")
    posted = payload.get("posted") or {}
    keys = payload.get("selection_keys") or []
    if not isinstance(posted, dict) or not isinstance(keys, list):
        raise QueueError("unreadable v1 queue")
    state = empty_state()
    if not day or not any(posted.values()):
        return state
    jobs = []
    for language, ranks in posted.items():
        if not isinstance(ranks, list):
            raise QueueError("unreadable v1 queue")
        for slot, rank in enumerate(sorted(ranks), start=1):
            if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
                raise QueueError("unreadable v1 queue")
            known = rank <= len(keys) and isinstance(keys[rank - 1], str)
            job = _blank_job(
                str(language),
                slot,
                story_key_for_identity(keys[rank - 1])
                if known
                else f"v1-unidentified-{language}-{rank}",
            )
            job.update(
                rank=rank,
                status="sent" if known else "unknown",
                detail="migrated_v1" if known else "migrated_v1_unidentified",
            )
            jobs.append(job)
    state["editions"][day] = {
        "status": "active",
        "published_at": None,
        "state_updated_at": None,
        "planned_at": _iso(now),
        "jobs": jobs,
    }
    return state


def validate(state: object) -> dict:
    """Refuse anything that could erase or misstate delivery history."""
    if not isinstance(state, dict) or state.get("version") != VERSION:
        raise QueueError("unsupported X queue version")
    editions = state.get("editions")
    if not isinstance(editions, dict):
        raise QueueError("invalid X queue editions")
    for day, edition in editions.items():
        try:
            date_type.fromisoformat(day)
        except (TypeError, ValueError) as exc:
            raise QueueError("invalid edition date") from exc
        if not isinstance(edition, dict) or edition.get("status") not in {
            "active",
            "skipped_late",
        }:
            raise QueueError("invalid edition record")
        for field in ("published_at", "planned_at"):
            if edition.get(field):
                _parse(edition[field], field)
        jobs = edition.get("jobs")
        if not isinstance(jobs, list):
            raise QueueError("invalid edition jobs")
        seen: set[tuple[object, object]] = set()
        for job in jobs:
            if not isinstance(job, dict) or job.get("status") not in STATUSES:
                raise QueueError("invalid job status")
            ident = (job.get("language"), job.get("slot"))
            if not isinstance(ident[0], str) or not isinstance(ident[1], int):
                raise QueueError("invalid job identity")
            if ident in seen:
                raise QueueError("duplicate job slot")
            seen.add(ident)
            if not isinstance(job.get("story_key"), str) or not job["story_key"]:
                raise QueueError("job without story key")
            if not isinstance(job.get("text"), str) or len(job["text"]) > 10000:
                raise QueueError("invalid job text")
            if job["status"] == "planned" and not job["text"]:
                raise QueueError("planned job without text")
            for field in ("due_at", "deadline", "attempted_at"):
                if job.get(field):
                    _parse(job[field], field)
    return state


def load(path: Path, now: Optional[datetime] = None) -> dict:
    """Missing means new. Anything unreadable stops delivery."""
    if not path.exists():
        return empty_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise QueueError("unreadable X queue; refusing to reset sent history") from exc
    if isinstance(payload, dict) and payload.get("version") == 1:
        return validate(_migrate_v1(payload, now or datetime.now().astimezone()))
    return validate(payload)


def dumps(state: dict) -> str:
    return json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def save(state: dict, path: Path) -> Path:
    """Local persistence; production uses :func:`git_checkpoint`."""
    validate(state)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, dumps(state))
    return path


def git_checkpoint(directory: Path, state: dict) -> None:
    """Persist to the queue branch. A rejected push must stop the caller.

    No force push: if the branch moved underneath this run, the push fails
    loudly instead of overwriting receipts, and because every POST is preceded
    by a checkpoint, a failed checkpoint means nothing is sent.
    """
    save(state, directory / QUEUE_RELATIVE_PATH)

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(directory), *args], check=True, capture_output=True
        )

    git("add", str(QUEUE_RELATIVE_PATH))
    staged = subprocess.run(
        ["git", "-C", str(directory), "diff", "--cached", "--quiet"],
        capture_output=True,
    )
    if staged.returncode == 0:
        return
    git("commit", "-m", "chore: checkpoint X delivery")
    git("push", "origin", f"HEAD:refs/heads/{QUEUE_BRANCH}")


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _at(day: str, clock: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(date_type.fromisoformat(day), clock, tzinfo=tz)


def _deadline(due: datetime, day: str, settings: Settings) -> datetime:
    return min(
        due + timedelta(minutes=settings.expire_after_minutes),
        _at(day, settings.window_end, settings.tz),
    )


def _gap_minutes(day: str, language: str, slot: int, settings: Settings) -> int:
    # Seeded so re-planning the same edition reproduces the same schedule.
    low = min(settings.gap_min_minutes, settings.gap_max_minutes)
    high = max(settings.gap_min_minutes, settings.gap_max_minutes)
    return random.Random(f"bmtnews-x:{day}:{language}:{slot}").randint(low, high)


def _prune(state: dict, today: str, settings: Settings) -> None:
    cutoff = date_type.fromisoformat(today) - timedelta(days=settings.history_days)
    for day in list(state["editions"]):
        if date_type.fromisoformat(day) < cutoff:
            del state["editions"][day]


def used_keys(state: dict, language: str) -> set[str]:
    return {
        job["story_key"]
        for edition in state["editions"].values()
        for job in edition["jobs"]
        if job["language"] == language and job["status"] in USED_STATUSES
    }


def _find(edition: dict, language: str, slot: int) -> Optional[dict]:
    return next(
        (
            job
            for job in edition["jobs"]
            if job["language"] == language and job["slot"] == slot
        ),
        None,
    )


async def plan_edition(
    state: dict,
    *,
    day: str,
    now: datetime,
    published_at: datetime,
    state_updated_at: str,
    candidates: dict[str, list[Candidate]],
    compose: Compose,
    settings: Settings,
) -> dict:
    """Plan (or re-plan after a republish) one edition's posts.

    Only jobs that were never attempted can change. Attempted, expired,
    skipped and voided jobs are history and stay exactly as they are.
    """
    summary: dict = {"changed": False, "composed": 0, "fallbacks": [], "late": False}
    _prune(state, day, settings)
    tz = settings.tz
    edition = state["editions"].get(day)
    if edition is None:
        published_local = published_at.astimezone(tz)
        latest_on_time = _at(day, settings.expected_publish, tz) + timedelta(
            minutes=settings.max_publish_delay_minutes
        )
        edition = {
            "status": "active",
            "published_at": _iso(published_local),
            "state_updated_at": state_updated_at,
            "planned_at": _iso(now),
            "jobs": [],
        }
        if published_local > latest_on_time:
            # Stale on X by the time it exists; the site still carries it.
            edition["status"] = "skipped_late"
            summary["late"] = True
        state["editions"][day] = edition
        summary["changed"] = True
    if edition["status"] == "skipped_late":
        if edition.get("state_updated_at") != state_updated_at:
            edition["state_updated_at"] = state_updated_at
            summary["changed"] = True
        return summary
    if edition.get("published_at") is None:
        # Migrated from v1 without a publication time: anchor on the migration.
        edition["published_at"] = _iso(now.astimezone(tz))
        summary["changed"] = True

    for language in settings.languages:
        used = used_keys(state, language)
        pool = [c for c in candidates.get(language, []) if c.key not in used]
        taken: set[str] = set()
        for slot in range(1, settings.items + 1):
            job = _find(edition, language, slot)
            if job is not None and job["status"] != "planned":
                taken.add(job["story_key"])
                continue
            choice = next((c for c in pool if c.key not in taken), None)
            if choice is None:
                if job is not None:
                    job["status"] = "skipped"
                    job["detail"] = "removed_from_edition"
                    summary["changed"] = True
                continue
            taken.add(choice.key)
            if (
                job is not None
                and job["story_key"] == choice.key
                and job["source_sha256"] == choice.source_sha256
            ):
                if job["rank"] != choice.rank:
                    job["rank"] = choice.rank
                    summary["changed"] = True
                continue

            due = deadline = None
            if job is None and slot == 1:
                due = datetime.fromisoformat(edition["published_at"])
                deadline = _deadline(due, day, settings)
                if now > deadline:
                    # Missed before it was ever written; do not pay for text.
                    missed = _blank_job(language, slot, choice.key)
                    missed.update(
                        rank=choice.rank,
                        title=choice.title,
                        status="expired",
                        detail="missed_deadline",
                        due_at=_iso(due),
                        deadline=_iso(deadline),
                        planned_at=_iso(now),
                    )
                    edition["jobs"].append(missed)
                    summary["changed"] = True
                    continue

            text, kind, reason = await compose(choice.item, language)
            summary["composed"] += 1
            if reason:
                summary["fallbacks"].append(reason)
            content = {
                "story_key": choice.key,
                "rank": choice.rank,
                "title": choice.title,
                "text": text,
                "text_sha256": text_digest(text),
                "source_sha256": choice.source_sha256,
                "compose": kind,
                "fallback_reason": reason,
                "planned_at": _iso(now),
            }
            if job is None:
                job = _blank_job(language, slot, choice.key)
                job.update(content)
                if slot == 1:
                    job["due_at"] = _iso(due)
                    job["deadline"] = _iso(deadline)
                else:
                    job["gap_minutes"] = _gap_minutes(day, language, slot, settings)
                edition["jobs"].append(job)
            else:
                # Republished story or new wording: keep the schedule, swap content.
                job.update(content)
                job["detail"] = "replanned"
            summary["changed"] = True
        edition["jobs"].sort(key=lambda entry: (entry["language"], entry["slot"]))

    if edition.get("state_updated_at") != state_updated_at:
        edition["state_updated_at"] = state_updated_at
        summary["changed"] = True
    return summary


# ---------------------------------------------------------------------------
# Time-driven transitions (no network, no model)
# ---------------------------------------------------------------------------


def recover_pending(state: dict) -> int:
    """A pending job means a run died mid-send. Never guess: mark unknown."""
    count = 0
    for edition in state["editions"].values():
        for job in edition["jobs"]:
            if job["status"] == "pending":
                job["status"] = "unknown"
                job["detail"] = "interrupted_before_result"
                count += 1
    return count


def advance(state: dict, now: datetime, settings: Settings) -> bool:
    """Anchor later slots on the previous post, and expire missed jobs."""
    changed = False
    for day, edition in state["editions"].items():
        for job in edition["jobs"]:
            if job["status"] != "planned" or job["due_at"] is not None:
                continue
            anchor = _find(edition, job["language"], job["slot"] - 1)
            if anchor is None or anchor["status"] == "planned":
                continue  # Wait for the previous slot to resolve.
            if anchor.get("attempted_at"):
                base = datetime.fromisoformat(anchor["attempted_at"])
            elif anchor.get("due_at"):
                base = datetime.fromisoformat(anchor["due_at"])
            else:
                base = now  # Migrated receipt with no recorded time.
            due = base + timedelta(minutes=int(job["gap_minutes"] or 0))
            job["due_at"] = _iso(due)
            job["deadline"] = _iso(_deadline(due, day, settings))
            changed = True
        for job in edition["jobs"]:
            if (
                job["status"] == "planned"
                and job["deadline"]
                and now > datetime.fromisoformat(job["deadline"])
            ):
                job["status"] = "expired"
                job["detail"] = "missed_deadline"
                changed = True
    return changed


def halted(edition: dict, language: str) -> bool:
    """A definitive rejection (auth, permission) stops the rest of the day."""
    return any(
        job["language"] == language and job["status"] == "failed"
        for job in edition["jobs"]
    )


def next_due(state: dict, now: datetime, today: str) -> Optional[dict]:
    """At most one post per run, so a delayed runner never bursts a batch."""
    edition = state["editions"].get(today)
    if edition is None or edition["status"] != "active":
        return None
    due = [
        job
        for job in edition["jobs"]
        if job["status"] == "planned"
        and job["due_at"]
        and datetime.fromisoformat(job["due_at"]) <= now
        and not halted(edition, job["language"])
    ]
    due.sort(key=lambda job: (job["due_at"], job["language"], job["slot"]))
    return due[0] if due else None


def counts(state: dict, day: str) -> dict[str, int]:
    edition = state["editions"].get(day) or {"jobs": []}
    result = {status: 0 for status in sorted(STATUSES)}
    for job in edition["jobs"]:
        result[job["status"]] += 1
    return result


def attention(state: dict) -> int:
    return sum(
        job["status"] in ATTENTION_STATUSES
        for edition in state["editions"].values()
        for job in edition["jobs"]
    )


def has_work(
    state: dict,
    now: datetime,
    settings: Settings,
    *,
    feed_date: str,
    feed_updated_at: str,
) -> bool:
    """Whether a run needs dependencies at all (the cheap workflow gate)."""
    today = now.astimezone(settings.tz).date().isoformat()
    if feed_date == today:
        edition = state["editions"].get(today)
        if edition is None or edition.get("state_updated_at") != feed_updated_at:
            return True
    probe = copy.deepcopy(state)
    if recover_pending(probe):
        return True
    if advance(probe, now, settings):
        return True
    return next_due(probe, now, today) is not None


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Cheap X queue gate")
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--feed-state", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--now", default="")
    args = parser.parse_args(argv)

    config = json.loads(args.config.read_text(encoding="utf-8"))
    x_delivery = config.get("x_delivery") or {}
    timezone = (config.get("filtering") or {}).get("daily_timezone") or "UTC"
    settings = Settings.from_mapping(x_delivery, timezone)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(settings.tz)
    enabled = bool(x_delivery.get("enabled")) and x_delivery.get("mode") == "drip"
    feed_date = feed_updated_at = ""
    if args.feed_state.exists():
        feed = json.loads(args.feed_state.read_text(encoding="utf-8"))
        if feed.get("timezone") == timezone:
            feed_date = str(feed.get("date") or "")
            feed_updated_at = normalize_stamp(feed.get("updated_at"))
    state = load(args.queue, now)
    work = enabled and has_work(
        state, now, settings, feed_date=feed_date, feed_updated_at=feed_updated_at
    )
    print(f"work={str(work).lower()}")
    print(f"attention={attention(state)}")


if __name__ == "__main__":
    main()
