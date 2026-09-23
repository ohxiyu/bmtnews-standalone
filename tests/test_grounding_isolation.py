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
    assert row.metadata["title_en"] == row.title
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


RICH_REPORT = {
    "title_en": "Rewritten headline", "title_zh": "协议暂停提现",
    "whats_new_en": "The team paused withdrawals.",
    "whats_new_zh": "团队暂停提现。",
    "why_it_matters_en": "Users cannot withdraw during the pause.",
    "why_it_matters_zh": "暂停期间用户无法提现。",
    "key_details_en": "The cause is unconfirmed.",
    "key_details_zh": "原因尚未确认。",
    "background_en": "The protocol previously allowed withdrawals.",
    "background_zh": "该协议此前允许提现。",
    "community_discussion_en": "Commenters are concerned.",
    "community_discussion_zh": "评论者表示担忧。",
    "market_impact_en": "A pause could affect confidence.",
    "market_impact_zh": "暂停可能影响信心。",
    "sources": ["https://example.com/context", "https://evil.example/extra"],
    "tags": ["Protocol", "Withdrawals"],
}


@pytest.mark.parametrize("reject_optional", [False, True])
def test_rich_news_keeps_verified_core_and_only_supported_context(monkeypatch, reject_optional):
    checked = []

    class Evaluator:
        async def assess_grounding(self, state):
            checked.append(state)
            return decision("unsupported" if reject_optional and len(checked) == 1 else "supported")

    class Client:
        async def complete(self, **kwargs): return json.dumps(RICH_REPORT)

    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: Evaluator())
    enricher = ContentEnricher(Client())

    async def concepts(*_): return ["protocol"]
    async def search(*_): return [{"title": "Context", "url": "https://example.com/context",
                                  "body": "Previously allowed withdrawals"}]

    monkeypatch.setattr(enricher, "_extract_concepts", concepts)
    monkeypatch.setattr(enricher, "_cached_web_search", search)
    row = story()
    asyncio.run(enricher.enrich_batch([row]))
    assert row.metadata["enrichment_status"] == ("partial" if reject_optional else "complete")
    assert row.metadata["title_en"] == row.title
    assert row.metadata["title_zh"] == "协议暂停提现"
    assert row.metadata["detailed_summary_en"].startswith("The team paused withdrawals.")
    assert row.ai_tags == ["Protocol", "Withdrawals"]
    assert "all funds are lost" not in checked[0]["source"]["text"]
    if reject_optional:
        assert len(checked) == 2
        assert row.metadata["evaluation_grounding"] == "supported_core"
        assert "background_en" not in row.metadata
        assert "sources" not in row.metadata
        assert "why_it_matters_en" not in checked[1]["generated"]
    else:
        assert len(checked) == 1
        assert row.metadata["background_en"]
        assert row.metadata["community_discussion_zh"]
        assert row.metadata["market_impact_en"]
        assert row.metadata["sources"] == [{"url": "https://example.com/context", "title": "Context"}]


def test_editorial_tags_survive_jev_enrichment_cache(tmp_path):
    cache = AnalysisResultCache(tmp_path / "cache.json", model="jev")
    row = story()
    row.ai_tags = []
    row.ai_summary = row.title
    row.metadata["evaluation"] = {"model": "typesafe-ai/jev"}
    row.metadata.update(enrichment_status="complete", evaluation_grounding="supported",
                        background_en="Verified context", editorial_tags=["Protocol"])
    row.ai_tags = ["Protocol"]
    cache.store_enrichment(row)
    next_run = story()
    next_run.ai_tags = []
    next_run.ai_summary = next_run.title
    next_run.metadata["evaluation"] = {"model": "typesafe-ai/jev"}
    assert cache.restore_enrichment(next_run)
    assert next_run.ai_tags == ["Protocol"]


def test_original_chinese_headline_is_not_rewritten():
    row = story()
    row.title = "协议暂停提现"
    assert ContentEnricher._source_headline(row, "zh", "改写的标题") == row.title
    assert ContentEnricher._source_headline(row, "en", "Protocol pauses withdrawals") == "Protocol pauses withdrawals"


def test_failed_full_and_core_checks_still_require_verified_translation(monkeypatch):
    class Evaluator:
        async def assess_grounding(self, state):
            return decision("unsupported" if "whats_new_en" in state["generated"] else "supported")

    class Client:
        async def complete(self, **kwargs):
            return json.dumps(RICH_REPORT if "structured bilingual news report" in kwargs["user"] else BRIEF)

    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: Evaluator())
    enricher = ContentEnricher(Client())

    async def no_concepts(*_): return []
    monkeypatch.setattr(enricher, "_extract_concepts", no_concepts)
    row = story()
    asyncio.run(enricher.enrich_batch([row]))
    assert row.metadata["enrichment_status"] == "translation_only"
    assert row.metadata["enrichment_fallback_reason"] == "news_core_unsupported"
    assert row.metadata["title_en"] == row.title
    assert "background_en" not in row.metadata
    assert row.ai_score == 8


def test_incomplete_full_response_is_not_published_as_rich_news(monkeypatch):
    class Evaluator:
        async def assess_grounding(self, state): return decision()

    class Client:
        async def complete(self, **kwargs):
            if "structured bilingual news report" in kwargs["user"]:
                return json.dumps({"title_zh": "标题", "whats_new_en": "English only."})
            return json.dumps(BRIEF)

    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: Evaluator())
    enricher = ContentEnricher(Client())

    async def no_concepts(*_): return []
    monkeypatch.setattr(enricher, "_extract_concepts", no_concepts)
    row = story()
    asyncio.run(enricher.enrich_batch([row]))
    assert row.metadata["enrichment_status"] == "translation_only"
    assert row.metadata["enrichment_fallback_reason"] == "invalid_generation"
    assert row.metadata["detailed_summary_zh"] == BRIEF["summary_zh"]
