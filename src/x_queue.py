"""Drip-posting state for spreading one edition across the day.

Drip mode posts the edition's highest-scoring stories one at a time at
peak reading hours instead of a single morning round-up. The only state
needed is "which ranks of which edition already went out", kept in a small
JSON file that the distribution workflow persists on its own branch.

Ordering, not clock matching, drives the queue: each run posts the lowest
rank that has not been posted yet. A delayed or missed slot therefore
shifts a post later instead of dropping or duplicating it.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field, ValidationError

from ._file_utils import _atomic_write_text

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("data/x-queue.json")


class XQueueState(BaseModel):
    """Ranks already posted for one edition date, per language."""

    version: int = 1
    date: str = ""
    posted: dict[str, List[int]] = Field(default_factory=dict)

    def posted_ranks(self, language: str) -> List[int]:
        return list(self.posted.get(language, []))

    def mark_posted(self, language: str, rank: int) -> None:
        ranks = set(self.posted.get(language, []))
        ranks.add(rank)
        self.posted[language] = sorted(ranks)


def load_queue_state(path: Path = DEFAULT_STATE_PATH) -> XQueueState:
    """Read the queue state; a missing or corrupt file starts fresh."""
    if not path.exists():
        return XQueueState()
    try:
        return XQueueState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        logger.warning("Ignoring unreadable X queue state %s: %s", path, exc)
        return XQueueState()


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
