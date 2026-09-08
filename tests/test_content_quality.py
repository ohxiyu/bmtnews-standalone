import asyncio
import json
from datetime import datetime, timedelta, timezone, date
from types import SimpleNamespace

import pytest

from src.ai.topic_dedup import duplicate_groups
from src.ai.summarizer import generate_edition_overviews
from src.ai.enricher import ContentEnricher
from src.editorial import load_editorial_plan
from src.models import ContentItem, SourceType
from src.orchestrator import BMTNewsOrchestrator


def item(index):
    return ContentItem(id=str(index), title=f"Story {index}", url=f"https://example.com/{index}",
                       source_type=SourceType.RSS, published_at=datetime(2026, 9, 8, tzinfo=timezone.utc) + timedelta(minutes=index))


def test_bounded_batches_cover_cross_block_pairs():
    seen = set()
    class Client:
        async def complete(self, **kwargs):
            import re
            ids = [int(value) for value in re.findall(r"\[\d+\] Story (\d+)", kwargs["user"])]
            assert len(ids) <= 12
            from itertools import combinations
            seen.update(combinations(ids, 2))
            return json.dumps({"duplicates": [[0, len(ids)-1]]})
    groups = asyncio.run(duplicate_groups(Client(), [item(i) for i in range(19)], [list(range(19))]))
    assert len(seen) == 19 * 18 // 2
    assert any(0 in group and 18 in group for group in groups)


@pytest.mark.parametrize("bad", ['{"duplicates":', '{"duplicates": [[true, 1]]}', '{"duplicates": [[0, 9]]}', '{}'])
def test_invalid_response_retries_then_stops_publication(bad):
    calls = []
    class Client:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return bad
    with pytest.raises(RuntimeError, match="refusing to publish"):
        asyncio.run(duplicate_groups(Client(), [item(0), item(1)], [[0, 1]]))
    assert len(calls) == 2


def test_retry_recovers_and_preserves_stable_priority():
    responses = iter(['broken', '{"duplicates": [[1, 0]]}'])
    class Client:
        async def complete(self, **kwargs):
            return next(responses)
    assert asyncio.run(duplicate_groups(Client(), [item(0), item(1)], [[0, 1]])) == [[0, 1]]


def test_daily_event_cap_uses_latest_without_false_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr("src.orchestrator.EVENT_CATALOG_PATH", tmp_path / "absent")
    orchestrator = BMTNewsOrchestrator.__new__(BMTNewsOrchestrator)
    old, new, other = item(0), item(1), item(2)
    old.metadata.update(event_id="same", event_update_id="old")
    new.metadata.update(event_id="same", event_update_id="new")
    assert orchestrator._distinct_daily_events([old, other, new]) == [new, other]
    assert "merged_sources" not in new.metadata
    old.source_type = SourceType.EDITORIAL
    assert orchestrator._distinct_daily_events([old, other, new]) == [old, other, new]


def test_overview_receives_enriched_numeric_scope():
    captured = {}
    story = item(0)
    story.ai_summary = "45% moved"
    story.metadata["detailed_summary_zh"] = "第三波资金的45%，不是全部损失。"
    story.metadata["detailed_summary_en"] = "45% of Wave 3, not aggregate losses."
    class Client:
        async def complete(self, **kwargs):
            captured.update(kwargs)
            return '{}'
    asyncio.run(generate_edition_overviews(Client(), [story], date="2026-09-08", languages=["zh", "en"]))
    assert "第三波资金的45%" in captured["user"]
    assert "45% of Wave 3" in captured["user"]
    assert "subset" in captured["system"]


def test_enrichment_degradation_is_visible(monkeypatch):
    enricher = ContentEnricher(SimpleNamespace())
    async def fail(story):
        raise ValueError("invalid model output")
    async def translate(story):
        story.metadata["title_zh"] = "翻译"
    monkeypatch.setattr(enricher, "_enrich_item", fail)
    monkeypatch.setattr(enricher, "_translate_item", translate)
    story = item(0)
    asyncio.run(enricher.enrich_batch([story]))
    assert story.metadata["enrichment_status"] == "translation_only"


def test_corrections_only_apply_to_affected_edition():
    plan = load_editorial_plan(date(2026, 9, 8))
    assert len(plan.suppressed_urls) == 7
    assert len(plan.editorial) == 1
    assert "第三波" in plan.editorial[0].summary_zh
    assert load_editorial_plan(date(2026, 9, 9)).is_empty
