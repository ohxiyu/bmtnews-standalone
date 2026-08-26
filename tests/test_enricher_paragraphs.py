import asyncio
from datetime import datetime, timezone

from src.ai.enricher import ContentEnricher
from src.models import ContentItem, SourceType


class _StubAIClient:
    def __init__(self) -> None:
        self._responses = iter(
            [
                '{"queries": []}',
                """{
                  "whats_new_en": "What happened.",
                  "whats_new_zh": "发生了什么。",
                  "why_it_matters_en": "Why it matters.",
                  "why_it_matters_zh": "为什么重要。",
                  "key_details_en": "Important caveat.",
                  "key_details_zh": "重要限制。"
                }""",
            ]
        )

    async def complete(self, **_kwargs: object) -> str:
        return next(self._responses)


def test_enrichment_preserves_semantic_summary_sections_as_paragraphs() -> None:
    item = ContentItem(
        id="paragraphs",
        source_type=SourceType.RSS,
        title="Paragraph test",
        url="https://example.com/paragraphs",
        published_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        ai_summary="Fallback summary",
    )

    asyncio.run(ContentEnricher(_StubAIClient())._enrich_item(item))

    assert item.metadata["detailed_summary_zh"] == (
        "发生了什么。\n\n为什么重要。\n\n重要限制。"
    )
    assert item.metadata["detailed_summary_en"] == (
        "What happened.\n\nWhy it matters.\n\nImportant caveat."
    )


def test_identical_web_searches_share_one_in_flight_request(monkeypatch) -> None:
    enricher = ContentEnricher(_StubAIClient())
    calls = 0

    async def fake_search(query: str, max_results: int = 3) -> list:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return [{"title": query, "url": "https://example.com", "body": "x"}]

    monkeypatch.setattr(enricher, "_web_search", fake_search)

    async def run() -> list:
        return await asyncio.gather(
            enricher._cached_web_search("  Bitcoin ETF "),
            enricher._cached_web_search("bitcoin   etf"),
        )

    first, second = asyncio.run(run())
    assert calls == 1
    assert first == second
