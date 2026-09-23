"""Offline regression tests for direct scoring and source-aware enrichment."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.ai.analyzer import ContentAnalyzer
from src.ai.client import ChainedAIClient
from src.ai.enricher import ContentEnricher
from src.ai.result_cache import AnalysisResultCache
from src.archive import build_records
from src.models import AIConfig, Config, ContentItem, FilteringConfig, SourceType, SourcesConfig
from src.orchestrator import BMTNewsOrchestrator
from src.run_report import RunReport
from src.storage.manager import StorageManager


def item() -> ContentItem:
    return ContentItem(
        id="rss:restored", source_type=SourceType.RSS,
        title="Protocol releases security update",
        url="https://example.com/story",
        content="Protocol released a security update on September 23.",
        published_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )


class StubClient:
    def __init__(self, config, responses):
        self.config = config
        self.responses = iter(responses)

    async def complete(self, *args, **kwargs):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


ANALYSIS = json.dumps({
    "score": 8.5, "reason": "Material security change",
    "summary": "A protocol released a security update.",
    "tags": ["security"], "category": "crypto-security",
})


def test_production_config_loads_without_retired_secret(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    payload = json.loads((Path(__file__).parents[1] / "data/config.github.json").read_text())
    config = Config.model_validate(payload)
    assert config.ai.provider.value == "deepseek"
    assert config.filtering.ai_score_threshold == 7.0
    with pytest.raises(ValidationError, match="ai.evaluator is no longer supported"):
        AIConfig.model_validate({**payload["ai"], "evaluator": {"enabled": False}})


def test_direct_analysis_records_producing_model_and_category():
    config = AIConfig(provider="deepseek", model="deepseek-flash", api_key_env="FAKE")
    story = item()
    asyncio.run(ContentAnalyzer(
        StubClient(config, [ANALYSIS]), allowed_categories=["crypto-security"],
    )._analyze_item(story))
    assert story.ai_score == 8.5
    assert story.metadata["category"] == "crypto-security"
    assert story.metadata["score_model"] == "deepseek:deepseek-flash"


def test_provider_fallback_records_actual_scoring_model():
    primary = AIConfig(provider="deepseek", model="primary", api_key_env="FAKE")
    fallback = AIConfig(provider="openai", model="fallback", api_key_env="FAKE")
    chain = ChainedAIClient(
        [primary, fallback],
        clients=[StubClient(primary, [RuntimeError("429 retryable")]),
                 StubClient(fallback, [ANALYSIS])],
    )
    story = item()
    asyncio.run(ContentAnalyzer(chain, allowed_categories=["crypto-security"])._analyze_item(story))
    assert story.metadata["score_model"] == "openai:fallback"


def test_retired_score_cache_entry_is_rejected_even_under_current_key(tmp_path):
    cache = AnalysisResultCache(tmp_path / "cache.json", model="deepseek:deepseek-flash",
                                prompt_revision="generation-direct-scoring-v1")
    story = item()
    cache.entries[cache._key(story, "analysis")] = {
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "value": {"ai_score": 9.9, "ai_summary": "Old", "evaluation": {"model": "old"}},
    }
    assert not cache.restore_analysis(story)
    assert story.ai_score is None


def test_new_archive_row_records_score_model_without_rewriting_history():
    story = item()
    story.ai_score = 8.5
    story.metadata["score_model"] = "deepseek:deepseek-flash"
    record = build_records([story], date="2026-09-23", top_category_of=lambda _: "crypto")[0]
    assert record.score == 8.5
    assert record.score_model == "deepseek:deepseek-flash"


def test_run_report_counts_cached_score_provenance(tmp_path):
    config = Config(
        ai=AIConfig(provider="deepseek", model="deepseek-flash", api_key_env="FAKE",
                    result_cache_path=str(tmp_path / "cache.json")),
        sources=SourcesConfig(), filtering=FilteringConfig(),
    )
    orchestrator = BMTNewsOrchestrator(config, StorageManager(data_dir=str(tmp_path / "data")))
    story = item()
    story.ai_score = 8.5
    story.ai_reason = "Material security change"
    story.metadata["score_model"] = "deepseek:deepseek-flash"
    orchestrator._result_cache().store_analysis(story)
    orchestrator.last_run_report = RunReport.start(date="2026-09-23", timezone_name="Asia/Shanghai")
    result = asyncio.run(orchestrator._analyze_content([item()]))
    assert result[0].metadata["score_model"] == "deepseek:deepseek-flash"
    assert orchestrator.last_run_report.breakdowns["score_models"] == {"deepseek:deepseek-flash": 1}


def test_enrichment_keeps_supported_sections_without_post_generation_gate(monkeypatch):
    class Client:
        async def complete(self, **kwargs):
            if "queries" in kwargs["user"]:
                return '{"queries": ["protocol security update"]}'
            return json.dumps({
                "title_zh": "协议发布安全更新",
                "whats_new_en": "The protocol released a security update.",
                "whats_new_zh": "该协议发布了安全更新。",
                "background_en": "The protocol previously disclosed the issue.",
                "background_zh": "该协议此前披露了该问题。",
                "market_impact_en": "Users may need to update clients.",
                "market_impact_zh": "用户可能需要更新客户端。",
                "sources": ["https://source.example/report", "https://invented.example"],
                "tags": ["security"],
            })

    enricher = ContentEnricher(Client())

    async def search(*args, **kwargs):
        return [{"title": "Source report", "url": "https://source.example/report", "body": "Context"}]

    monkeypatch.setattr(enricher, "_web_search", search)
    story = item()
    asyncio.run(enricher.enrich_batch([story]))
    assert story.metadata["enrichment_status"] == "complete"
    assert story.metadata["background_zh"] == "该协议此前披露了该问题。"
    assert story.metadata["sources"] == [{"url": "https://source.example/report", "title": "Source report"}]
    assert story.ai_tags == ["security"]
