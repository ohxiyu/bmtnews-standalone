"""Low-cost batched relevance prefilter for large candidate sets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ..models import ContentItem
from .client import AIClient
from .utils import parse_json_response


PREFILTER_SYSTEM = """You are the fast first-pass editor for BMTNews.
Rank candidates for a crypto-first daily briefing that may include a small
number of consequential AI/technology and public-policy stories. Penalize
promotions, generic market commentary, duplicates, and low-substance updates.
Return JSON only. Never rewrite or summarize the stories."""

PREFILTER_USER = """Score each candidate from 0 to 10 for whether it deserves
the slower full analysis pass. Preserve the supplied integer index.

{items}

Return exactly: {{"items":[{{"index":0,"score":7.5}}, ...]}}"""


@dataclass(frozen=True)
class PrefilterResult:
    items: list[ContentItem]
    evaluated: int
    removed: int
    failed_batches: int


class ContentPrefilter:
    """Score titles in batches, with fail-open behavior per failed batch."""

    def __init__(self, client: AIClient, *, batch_size: int = 20) -> None:
        self.client = client
        self.batch_size = max(5, min(50, batch_size))

    def _concurrency(self) -> int:
        config = getattr(self.client, "config", None)
        return max(1, min(8, int(getattr(config, "analysis_concurrency", 1))))

    async def select(
        self,
        items: list[ContentItem],
        *,
        maximum: int,
        reserve_per_category: int = 4,
    ) -> PrefilterResult:
        if len(items) <= maximum:
            return PrefilterResult(list(items), 0, 0, 0)

        indexed = list(enumerate(items))
        batches = [
            indexed[offset : offset + self.batch_size]
            for offset in range(0, len(indexed), self.batch_size)
        ]
        semaphore = asyncio.Semaphore(self._concurrency())

        async def score_batch(
            batch: list[tuple[int, ContentItem]],
        ) -> tuple[dict[int, float] | None, set[int]]:
            lines = []
            batch_indices = {index for index, _ in batch}
            for index, item in batch:
                excerpt = " ".join((item.content or "").split())[:360]
                lines.append(
                    f"[{index}] category={item.metadata.get('category', 'other')} "
                    f"source={item.source_type.value} title={item.title} excerpt={excerpt}"
                )
            try:
                async with semaphore:
                    response = await self.client.complete(
                        system=PREFILTER_SYSTEM,
                        user=PREFILTER_USER.format(items="\n".join(lines)),
                        response_format="json",
                    )
                payload = parse_json_response(response)
                rows = payload.get("items") if isinstance(payload, dict) else None
                if not isinstance(rows, list):
                    return None, batch_indices
                scores: dict[int, float] = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    index = row.get("index")
                    score = row.get("score")
                    if (
                        isinstance(index, int)
                        and index in batch_indices
                        and isinstance(score, (int, float))
                        and not isinstance(score, bool)
                    ):
                        scores[index] = max(0.0, min(10.0, float(score)))
                if len(scores) < max(1, len(batch) // 2):
                    return None, batch_indices
                return scores, batch_indices
            except Exception:
                return None, batch_indices

        results = await asyncio.gather(*(score_batch(batch) for batch in batches))
        scores: dict[int, float] = {}
        fail_open: set[int] = set()
        failed_batches = 0
        for result, indices in results:
            if result is None:
                failed_batches += 1
                fail_open.update(indices)
            else:
                scores.update(result)

        # Reserve a few candidates from every configured source category so a
        # broad crypto batch cannot erase scarce policy or AI coverage.
        reserved: set[int] = set(fail_open)
        by_category: dict[str, list[int]] = {}
        for index, item in indexed:
            category = str(item.metadata.get("category") or "other")
            by_category.setdefault(category, []).append(index)
        for category_indices in by_category.values():
            category_indices.sort(key=lambda index: scores.get(index, -1), reverse=True)
            reserved.update(category_indices[: max(1, reserve_per_category)])

        ranked = sorted(
            (index for index in scores if index not in reserved),
            key=lambda index: (scores[index], -index),
            reverse=True,
        )
        target = max(maximum, len(reserved))
        selected = set(reserved)
        selected.update(ranked[: max(0, target - len(selected))])
        chosen = [item for index, item in indexed if index in selected]
        return PrefilterResult(
            chosen,
            evaluated=len(scores),
            removed=len(items) - len(chosen),
            failed_batches=failed_batches,
        )
