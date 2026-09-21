"""Authenticated Jev contract check, three calls, no publishing or source changes."""
import asyncio
from datetime import datetime, timezone

from src.ai.evaluator import JevEvaluator
from src.ai.tokens import task_usage_snapshot
from src.edition import edition_window_for
from src.models import ContentItem, EvaluationConfig, SourceType
from src.ai.prompts import TOPIC_DEDUP_SYSTEM


async def main():
    evaluator = JevEvaluator(EvaluationConfig(enabled=True))
    item = ContentItem(id="jev-contract", source_type=SourceType.RSS,
        title="Protocol A pauses withdrawals after confirmed exploit",
        content="On September 21, 2026, Protocol A confirmed an exploit and paused withdrawals. "
                "The team is investigating; recovery of funds has not been confirmed.",
        url="https://example.com/jev-contract", published_at=datetime(2026, 9, 21, tzinfo=timezone.utc),
        ai_score=8, ai_summary="Protocol A paused withdrawals after confirming an exploit.")
    await evaluator.analyze(item, ["crypto-security", "ai"], edition_window_for(datetime(2026, 9, 22, tzinfo=timezone.utc), "Asia/Shanghai"))
    assert item.metadata["evaluation"]["model"] == "typesafe-ai/jev"
    other = item.model_copy(update={"id": "other", "title": "Protocol B releases developer documentation",
        "content": "Protocol B published a documentation update. No exploit or withdrawal change occurred.",
        "ai_summary": "Protocol B documentation update."})
    assert await evaluator.duplicates([item, other], TOPIC_DEDUP_SYSTEM) == {"duplicates": []}
    assert await evaluator.verify({"source": item.content,
        "generated": "Protocol A paused withdrawals following a confirmed exploit. Recovery remains unconfirmed."})
    print("Jev authenticated scoring, distinct-event comparison and grounding checks passed.")
    print("Scoring result:", item.ai_score)
    print("Usage:", task_usage_snapshot())


if __name__ == "__main__":
    asyncio.run(main())
