import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.ai.enricher import ContentEnricher, GroundingRejected
from src.ai.evaluator import EvaluationError, JevEvaluator
from src.ai.result_cache import AnalysisResultCache
from src.models import AIConfig, Config, ContentItem, EvaluationConfig, FilteringConfig, SourcesConfig, SourceType
from src.orchestrator import BMTNewsOrchestrator
from src.storage.manager import StorageManager


def story(index=0):
    return ContentItem(id=str(index), title=f"Protocol {index} paused withdrawals",
        content="The team paused withdrawals. The cause is unconfirmed.\n--- Top Comments ---\nSomeone claims all funds are lost.",
        ai_summary="A stale unsupported summary", ai_score=8,
        source_type=SourceType.RSS, url=f"https://example.com/{index}",
        published_at=datetime(2026, 9, 21, tzinfo=timezone.utc))


def decision(kind="supported", probability=1):
    return {"accepted": kind == "supported" and probability >= .9, "decision": kind,
            "supported_probability": probability, "threshold": .9}


BRIEF = {"title_zh": "协议暂停提现", "summary_zh": "团队暂停提现，原因尚未确认。",
         "title_en": "Withdrawals paused", "summary_en": "The team paused withdrawals; the cause is unconfirmed."}


def test_translation_generation_and_check_use_identical_source(monkeypatch):
    seen = {}
    class Evaluator:
        async def assess_grounding(self, state):
            seen["check"] = state
            return decision()
    class Client:
        async def complete(self, **kwargs):
            seen["prompt"] = kwargs["user"]
            return json.dumps(BRIEF)
    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: Evaluator())
    row = story()
    asyncio.run(ContentEnricher(Client())._translate_item(row))
    source = json.loads(seen["prompt"].split("Source JSON:\n")[1].split("\nReturn ")[0])
    assert source == seen["check"]["source"]
    assert "stale unsupported" not in seen["prompt"]
    assert "all funds" not in seen["prompt"]
    assert row.metadata["detailed_summary_en"] == BRIEF["summary_en"]
    assert row.metadata["grounding_checks"]["translation"]["accepted"]


@pytest.mark.parametrize("kind,probability,code", [("unsupported",0,"translation_unsupported"),
    ("insufficient",.2,"translation_insufficient"), ("supported",.8,"translation_low_confidence")])
def test_content_rejection_reasons_are_distinct(monkeypatch, kind, probability, code):
    class Evaluator:
        async def assess_grounding(self, state): return decision(kind, probability)
    class Client:
        async def complete(self, **kwargs): return json.dumps(BRIEF)
    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: Evaluator())
    row = story()
    with pytest.raises(GroundingRejected) as caught:
        asyncio.run(ContentEnricher(Client())._translate_item(row))
    assert caught.value.code == code
    assert "detailed_summary_zh" not in row.metadata
    assert row.metadata["grounding_checks"]["translation"]["supported_probability"] == probability


def test_rejected_item_does_not_cancel_sibling_and_clears_stale_text(monkeypatch):
    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: object())
    enricher = ContentEnricher(SimpleNamespace(config=SimpleNamespace(enrichment_concurrency=2)))
    async def enrich(row):
        row.metadata["background_zh"] = "Partial stale output"
        if row.id == "0": raise GroundingRejected("generation_unsupported")
        row.metadata["evaluation_grounding"] = "supported"
        row.metadata["detailed_summary_zh"] = "Valid"
    async def translate(row): raise GroundingRejected("translation_insufficient")
    monkeypatch.setattr(enricher, "_enrich_item", enrich)
    monkeypatch.setattr(enricher, "_translate_item", translate)
    rows = [story(0),story(1)]
    asyncio.run(enricher.enrich_batch(rows))
    assert rows[0].metadata["enrichment_status"] == "rejected"
    assert "background_zh" not in rows[0].metadata
    assert rows[1].metadata["enrichment_status"] == "complete"


def test_provider_failure_is_not_content_rejection_or_translation_retry(monkeypatch):
    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: object())
    enricher = ContentEnricher(SimpleNamespace())
    async def enrich(row): raise EvaluationError("http_error",429)
    calls = []
    async def translate(row): calls.append(row)
    monkeypatch.setattr(enricher, "_enrich_item", enrich)
    monkeypatch.setattr(enricher, "_translate_item", translate)
    row = story()
    asyncio.run(enricher.enrich_batch([row]))
    assert row.metadata["enrichment_status"] == "verification_unavailable"
    assert row.metadata["grounding_error"] == {"code":"http_error","status":429}
    assert calls == []


@pytest.mark.parametrize("all_rejected", [False,True])
def test_orchestrator_removes_rejected_before_downstream_and_preserves_good_cache(tmp_path, monkeypatch, all_rejected):
    cfg = Config(ai=AIConfig(provider="deepseek",model="test",api_key_env="TEST",
        evaluator=EvaluationConfig(enabled=True),result_cache_path=str(tmp_path/"cache.json")),
        sources=SourcesConfig(),filtering=FilteringConfig())
    orchestrator = BMTNewsOrchestrator(cfg,StorageManager(data_dir=str(tmp_path/"data")))
    monkeypatch.setattr("src.orchestrator.create_ai_client",lambda _: object())
    monkeypatch.setattr("src.ai.enricher.create_evaluator",lambda _: object())
    async def enrich(self, rows):
        for row in rows:
            rejected = all_rejected or row.id == "0"
            row.metadata.update(enrichment_status="rejected" if rejected else "complete",
                evaluation_grounding="unsupported" if rejected else "supported",background_en="background",
                grounding_error={"code":"translation_insufficient"})
    monkeypatch.setattr(ContentEnricher,"enrich_batch",enrich)
    rows = [story(0),story(1)]
    if all_rejected:
        with pytest.raises(RuntimeError,match="No verified news remains"):
            asyncio.run(orchestrator._enrich_important_items(rows))
        assert rows == []
    else:
        asyncio.run(orchestrator._enrich_important_items(rows))
        assert [row.id for row in rows] == ["1"]
        assert orchestrator._result_cache().restore_enrichment(story(1))
    assert not orchestrator._result_cache().restore_enrichment(story(0))


def test_verified_short_translation_can_be_cached(tmp_path):
    cache = AnalysisResultCache(tmp_path/"cache.json",model="test")
    row = story()
    row.metadata.update(enrichment_status="translation_only",evaluation_grounding="supported_translation",
                        detailed_summary_en="Supported English",detailed_summary_zh="有来源支持")
    cache.store_enrichment(row)
    assert cache.restore_enrichment(story())


def test_grounding_detail_and_boolean_wrapper_agree(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY","test")
    evaluator = JevEvaluator(EvaluationConfig(enabled=True))
    async def evaluate(*args,**kwargs):
        return {"grounding":{"choice":"supported","probabilities":{"supported":.85,"unsupported":.1,"insufficient":.05}}}
    monkeypatch.setattr(evaluator,"evaluate",evaluate)
    result = asyncio.run(evaluator.assess_grounding({}))
    assert result == decision("supported",.85)
    assert not asyncio.run(evaluator.verify({}))


def test_new_grounding_policy_invalidates_only_generated_text(tmp_path, monkeypatch):
    cache = AnalysisResultCache(tmp_path/"cache.json",model="test")
    row = story()
    row.metadata["background_en"] = "Previously generated background"
    monkeypatch.setattr("src.ai.result_cache.ENRICHMENT_POLICY_VERSION","old")
    cache.store_analysis(row)
    cache.store_enrichment(row)
    monkeypatch.setattr("src.ai.result_cache.ENRICHMENT_POLICY_VERSION","new")
    assert cache.restore_analysis(story())
    assert not cache.restore_enrichment(story())
