"""Drip-posting state for spreading one edition across the day.

Drip mode posts the edition's highest-scoring stories one at a time at
peak reading hours instead of a single morning round-up. Sent ranks and their
ordered selection identities are kept in a small JSON file on the queue branch.
Reordered or legacy rank-only editions pause rather than guessing identities.

Ordering, not clock matching, drives the queue: each run posts the lowest
rank that has not been posted yet. A delayed or missed slot therefore
shifts a post later instead of dropping or duplicating it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Literal

from pydantic import BaseModel, Field, ValidationError

from ._file_utils import _atomic_write_text

DEFAULT_STATE_PATH = Path("data/x-queue.json")


class XQueueState(BaseModel):
    """Ranks already posted for one edition date, per language."""

    version: Literal[1] = 1
    date: str = ""
    posted: dict[str, List[int]] = Field(default_factory=dict)
    selection_keys: List[str] = Field(default_factory=list)

    def bind_selection(self, keys: List[str]) -> bool:
        """Pin ranks to identities; ambiguous legacy/reordered days pause."""
        started = any(self.posted.values())
        if started and self.selection_keys != keys:
            return False
        self.selection_keys = list(keys)
        return True

    def posted_ranks(self, language: str) -> List[int]:
        return list(self.posted.get(language, []))

    def mark_posted(self, language: str, rank: int) -> None:
        ranks = set(self.posted.get(language, []))
        ranks.add(rank)
        self.posted[language] = sorted(ranks)


def load_queue_state(path: Path = DEFAULT_STATE_PATH) -> XQueueState:
    """Missing means new; corruption must never erase delivery history."""
    if not path.exists():
        return XQueueState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not {"version", "date", "posted"} <= payload.keys():
            raise ValueError("missing queue fields")
        return XQueueState.model_validate(payload)
    except (OSError, ValidationError, ValueError) as exc:
        raise ValueError("Unreadable X queue state; refusing to reset sent history") from exc


def save_queue_state(
    state: XQueueState,
    path: Path = DEFAULT_STATE_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, state.model_dump_json(indent=2) + "\n")
    return path


def state_for_edition(
    state: XQueueState,
    edition_date: str,
) -> XQueueState:
    """Return state scoped to ``edition_date``, resetting on a new edition."""
    if state.date != edition_date:
        return XQueueState(date=edition_date)
    return state


def next_pending_rank(
    state: XQueueState,
    *,
    language: str,
    total_items: int,
    limit: int,
) -> Optional[int]:
    """Return the lowest 1-based rank still awaiting a post, if any."""
    countable = min(total_items, max(0, limit))
    posted = set(state.posted_ranks(language))
    for rank in range(1, countable + 1):
        if rank not in posted:
            return rank
    return None
