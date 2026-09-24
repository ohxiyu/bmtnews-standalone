import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from src.ai.prefilter import ContentPrefilter
from src.ai.result_cache import AnalysisResultCache
from src.ai.summarizer import generate_edition_overviews
from src.models import ContentItem, SourceType
from src.models import AIConfig, Config, FilteringConfig, SourcesConfig
from src.orchestrator import BMTNewsOrchestrator
from src.storage.manager import StorageManager


def _item(index: int, *, category: str = "crypto-markets") -> ContentItem:
    return ContentItem(
        id=f"rss:test:{index}",
        source_type=SourceType.RSS,
        title=f"Story {index}",
        url=f"https://example.com/{index}",
        content=f"Body {index}",
        published_at=datetime(2026, 8, 26, tzinfo=timezone.utc),
        metadata={"category": category},
    )


def test_result_cache_restores_analysis_and_enrichment(tmp_path):
    path = tmp_path / "analysis-cache.json"
    item = _item(1)
    item.ai_score = 8.5
    item.ai_reason = "Material event"
    item.ai_summary = "A concise summary"
    item.ai_tags = ["bitcoin"]
    item.metadata["title_zh"] = "重要事件"
    item.metadata["background_zh"] = "背景"

    cache = AnalysisResultCache(path, model="test:model")
    cache.store_analysis(item)
    cache.store_enrichment(item)
    cache.save()

    restored = _item(1)
    reloaded = AnalysisResultCache(path, model="test:model")
    assert reloaded.restore_analysis(restored) is True
    assert reloaded.restore_enrichment(restored) is True
    assert restored.ai_score == 8.5
    assert restored.ai_tags == ["bitcoin"]
    assert restored.metadata["title_zh"] == "重要事件"
    assert restored.metadata["background_zh"] == "背景"

    changed = _item(1)
    changed.content = "Changed source body"
    assert reloaded.restore_analysis(changed) is False


def test_cache_invalidates_changed_prompt_and_enrichment_inputs(tmp_path, monkeypatch):
    from src.ai import prompts
    cache = AnalysisResultCache(tmp_path / "cache.json", model="test")
    item = _item(1)
    item.ai_score = 8
    item.ai_summary = "Initial summary"
    item.metadata["background_zh"] = "背景"
    cache.store_analysis(item)
    cache.store_enrichment(item)
    item.ai_summary = "Corrected summary"
    assert not cache.restore_enrichment(item)
    monkeypatch.setattr(prompts, "CONTENT_ANALYSIS_SYSTEM", "Changed policy")
    assert not cache.restore_analysis(_item(1))


def test_cached_items_never_reenter_paid_prefilter(tmp_path, monkeypatch):
    config = Config(ai=AIConfig(provider="openai", model="test", api_key_env="TEST",
                    prefilter_enabled=True, prefilter_max_candidates=20,
                    result_cache_path=str(tmp_path / "cache.json")),
                    sources=SourcesConfig(), filtering=FilteringConfig())
    orchestrator = BMTNewsOrchestrator(config, StorageManager(data_dir=str(tmp_path / "data")))
    cache = orchestrator._result_cache()
    for i in range(20):
        cached = _item(i)
        cached.ai_score = 8
        cache.store_analysis(cached)
    seen = []
    async def select(self, items, **kwargs):
        from src.ai.prefilter import PrefilterResult
        seen.extend(row.id for row in items)
        return PrefilterResult(items[:5], len(items), len(items)-5, 0)
    async def analyze(self, items):
        for row in items:
            row.ai_score = 9
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda config: object())
    monkeypatch.setattr(ContentPrefilter, "select", select)
    monkeypatch.setattr("src.orchestrator.ContentAnalyzer.analyze_batch", analyze)
    result = asyncio.run(orchestrator._analyze_content([_item(i) for i in range(30)]))
    assert seen == [f"rss:test:{i}" for i in range(20, 30)]
    assert len(result) == 20
    assert result[0].ai_score == 9


def test_prefilter_batches_candidates_and_preserves_scarce_categories():
    calls = 0

    class Client:
        config = SimpleNamespace(analysis_concurrency=3)

        async def complete(self, **kwargs):
            nonlocal calls
            calls += 1
            indices = [
                int(line.split("]", 1)[0][1:])
                for line in kwargs["user"].splitlines()
                if line.startswith("[")
            ]
            return json.dumps(
                {"items": [{"index": index, "score": index} for index in indices]}
            )

    items = [_item(i) for i in range(12)]
    items[0].metadata["category"] = "macro-regulation"
    result = asyncio.run(
        ContentPrefilter(Client(), batch_size=5).select(
            items,
            maximum=6,
            reserve_per_category=1,
        )
    )
    assert calls == 3
    assert len(result.items) == 6
    assert items[0] in result.items
    assert result.removed == 6
    assert result.failed_batches == 0


def test_prefilter_reuses_only_an_identical_complete_batch(tmp_path):
    path = tmp_path / "analysis-cache.json"
    items = [_item(i) for i in range(8)]

    class Client:
        config = SimpleNamespace(analysis_concurrency=2)

        def __init__(self):
            self.calls = 0

        async def complete(self, **kwargs):
            self.calls += 1
            indices = [
                int(line.split("]", 1)[0][1:])
                for line in kwargs["user"].splitlines() if line.startswith("[")
            ]
            return json.dumps({"items": [
                {"index": index, "score": index} for index in indices
            ]})

    first_client = Client()
    cache = AnalysisResultCache(path, model="test:model")
    first = asyncio.run(ContentPrefilter(first_client, batch_size=5, cache=cache).select(
        items, maximum=5, reserve_per_category=1,
    ))
    assert first_client.calls == 2
    assert (first.cache_hits, first.cache_misses) == (0, 2)
    assert cache.snapshot() == {"hits": 0, "misses": 0, "entries": 0}
    cache.save()

    second_client = Client()
    cache = AnalysisResultCache(path, model="test:model")
    second = asyncio.run(ContentPrefilter(second_client, batch_size=5, cache=cache).select(
        [_item(i) for i in range(8)], maximum=5, reserve_per_category=1,
    ))
    assert second_client.calls == 0
    assert (second.cache_hits, second.cache_misses) == (2, 0)
    assert cache.snapshot() == {"hits": 0, "misses": 0, "entries": 0}
    assert [item.id for item in second.items] == [item.id for item in first.items]

    changed = [_item(i) for i in range(8)]
    changed[0].content = "Updated lead with a material new fact"
    third_client = Client()
    third = asyncio.run(ContentPrefilter(third_client, batch_size=5, cache=cache).select(
        changed, maximum=5, reserve_per_category=1,
    ))
    assert third_client.calls == 1
    assert (third.cache_hits, third.cache_misses) == (1, 1)

    new_model_client = Client()
    new_model = AnalysisResultCache(path, model="test:new-model")
    new_model_result = asyncio.run(ContentPrefilter(
        new_model_client, batch_size=5, cache=new_model,
    ).select([_item(i) for i in range(8)], maximum=5))
    assert new_model_client.calls == 2
    assert new_model_result.cache_misses == 2


def test_prefilter_batches_have_a_separate_short_lived_capacity(tmp_path):
    path = tmp_path / "cache.json"
    cache = AnalysisResultCache(path, model="test:model", max_entries=100)
    for index in range(100):
        item = _item(index)
        item.ai_score = 8.0
        cache.store_analysis(item)
    for index in range(260):
        cache.store_prefilter_batch("prefilter policy", f"batch {index}", {index: 7.0})
    cache.save()

    reloaded = AnalysisResultCache(path, model="test:model", max_entries=100)
    assert len(reloaded.entries) == 100
    assert len(reloaded.prefilter_batches) == 256
    assert all(reloaded.restore_analysis(_item(index)) for index in range(100))


def test_incomplete_prefilter_response_is_never_cached(tmp_path):
    class Client:
        config = SimpleNamespace(analysis_concurrency=2)

        def __init__(self):
            self.calls = 0

        async def complete(self, **kwargs):
            self.calls += 1
            indices = [
                int(line.split("]", 1)[0][1:])
                for line in kwargs["user"].splitlines() if line.startswith("[")
            ]
            return json.dumps({"items": [
                {"index": index, "score": 7} for index in indices[:3]
            ]})

    cache = AnalysisResultCache(tmp_path / "cache.json", model="test:model")
    client = Client()
    for _ in range(2):
        result = asyncio.run(ContentPrefilter(client, batch_size=5, cache=cache).select(
            [_item(i) for i in range(10)], maximum=5,
        ))
        assert result.cache_hits == 0
        assert result.cache_misses == 2
    assert client.calls == 4


def test_prefilter_failed_batch_is_kept_fail_open():
    class Client:
        config = SimpleNamespace(analysis_concurrency=2)

        async def complete(self, **kwargs):
            raise RuntimeError("provider unavailable")

    items = [_item(i) for i in range(8)]
    result = asyncio.run(
        ContentPrefilter(Client(), batch_size=5).select(items, maximum=5)
    )
    assert result.items == items
    assert result.failed_batches == 2
    assert result.removed == 0


def test_bilingual_overview_uses_one_model_call():
    calls = 0

    class Client:
        async def complete(self, **kwargs):
            nonlocal calls
            calls += 1
            return json.dumps(
                {
                    "zh": {
                        "headline": "监管与市场结构成为今日主线。",
                        "signals": [
                            {"label": "政策", "text": "监管机构发布新规则。", "item_rank": 1}
                        ],
                    },
                    "en": {
                        "headline": "Policy and market structure drove the day.",
                        "signals": [
                            {"label": "Policy", "text": "A regulator published new rules.", "item_rank": 1}
                        ],
                    },
                }
            )

    item = _item(1)
    item.ai_score = 8.5
    item.ai_summary = "A regulator published new rules."
    result = asyncio.run(
        generate_edition_overviews(
            Client(), [item], date="2026-08-26", languages=["zh", "en"]
        )
    )
    assert calls == 1
    assert set(result) == {"zh", "en"}
    assert result["zh"].signals[0].item_rank == 1


def test_topic_dedup_sends_only_local_candidate_cluster_to_ai(
    tmp_path, monkeypatch
):
    captured = ""

    class Client:
        async def complete(self, **kwargs):
            nonlocal captured
            captured = kwargs["user"]
            return '{"duplicates": [[0, 1]]}'

    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_KEY",
            result_cache_enabled=False,
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(),
    )
    orchestrator = BMTNewsOrchestrator(
        config, StorageManager(data_dir=str(tmp_path / "data"))
    )
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda _config: Client())
    first = _item(1)
    first.title = "Coinbase announces the same custody launch"
    first.ai_summary = "Coinbase launched institutional custody today."
    first.ai_tags = ["coinbase", "institutional-custody"]
    first.ai_score = 9.0
    duplicate = _item(2)
    duplicate.title = first.title
    duplicate.ai_summary = first.ai_summary
    duplicate.ai_tags = list(first.ai_tags)
    duplicate.ai_score = 8.0
    unrelated = _item(3)
    unrelated.title = "Unrelated AI compiler benchmark"
    unrelated.ai_summary = "A compiler benchmark was released."
    unrelated.ai_tags = ["ai", "compiler"]
    unrelated.ai_score = 7.5

    result = asyncio.run(
        orchestrator.merge_topic_duplicates([first, duplicate, unrelated], log=False)
    )
    assert result == [first, unrelated]
    assert "Unrelated AI compiler benchmark" not in captured
