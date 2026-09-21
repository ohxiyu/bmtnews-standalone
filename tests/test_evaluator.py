import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from src.ai.evaluator import JevEvaluator, EvaluationError, validate_answers, create_evaluator
from src.ai.analyzer import ContentAnalyzer
from src.ai.prefilter import ContentPrefilter
from src.ai.topic_dedup import duplicate_groups
from src.ai.prompts import TOPIC_DEDUP_SYSTEM, DAILY_EVENT_DEDUP_SYSTEM
from src.ai.result_cache import AnalysisResultCache
from src.models import EvaluationConfig, AIConfig, ContentItem, SourceType
from src.edition import edition_window_for


def item(n=0):
    return ContentItem(id=f"test-{n}", source_type=SourceType.RSS, title=f"Story {n}",
        content=f"Source evidence {n}", url=f"https://example.com/{n}",
        published_at=datetime(2026, 9, 21, tzinfo=timezone.utc), ai_score=8)


def choice(question, selected):
    return {"type": "choice", "choice": selected,
            "probabilities": {key: float(key == selected) for key in question["criteria"]}}


def score(question, value):
    return {"type": "score", "score": value,
            "probabilities": {str(i): float(i == value) for i in range(len(question["criteria"]))}}


@pytest.fixture
def evaluator(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test-key-never-log")
    return JevEvaluator(EvaluationConfig(enabled=True))


@pytest.mark.parametrize("invalid", [None, True, float("nan"), float("inf"), -0.1, 1.1])
def test_rejects_invalid_boolean_probability(invalid):
    with pytest.raises(EvaluationError):
        validate_answers({"answers": {"x": {"type": "boolean", "probability": invalid}}}, {"x": {"type": "boolean"}})


@pytest.mark.parametrize("answer", [
    {"type": "choice", "choice": "x", "probabilities": {"a": 1, "b": 0}},
    {"type": "choice", "choice": "a", "probabilities": {"a": 0, "b": 1}},
    {"type": "choice", "choice": "a", "probabilities": {"a": 1}},
    {"type": "choice", "choice": "a", "probabilities": {"a": 1, "b": 1}},
])
def test_invalid_choices_cannot_drive_decisions(answer):
    with pytest.raises(EvaluationError):
        validate_answers({"answers": {"x": answer}}, {"x": {"type": "choice", "criteria": {"a": "a", "b": "b"}}})


def test_missing_key_fails_before_calls(monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    with pytest.raises(EvaluationError, match="missing_api_key"):
        JevEvaluator(EvaluationConfig(enabled=True))
    assert create_evaluator(None) is None
    assert create_evaluator(AIConfig(provider="deepseek", model="test", api_key_env="TEST")) is None


def test_http_contract_and_bounded_retry(evaluator, monkeypatch):
    calls = []
    async def no_sleep(_): pass
    monkeypatch.setattr("src.ai.evaluator.asyncio.sleep", no_sleep)
    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://ai-gateway.vercel.sh/v1/evaluate"
        assert request.headers["Authorization"] == "Bearer test-key-never-log"
        assert "messages" not in json.loads(request.content)
        if len(calls) == 1:
            return httpx.Response(529, text="provider unavailable")
        return httpx.Response(200, json={"answers": {"x": {"type": "boolean", "probability": 0.9}}})
    evaluator.transport = httpx.MockTransport(handler)
    result = asyncio.run(evaluator.evaluate("state", {"x": {"type": "boolean"}}, stage="test"))
    assert result["x"]["probability"] == 0.9
    assert len(calls) == 2


@pytest.mark.parametrize("status", [401, 402, 403])
def test_account_errors_are_sanitized_and_not_retried(evaluator, status):
    calls = []
    def handler(request):
        calls.append(1)
        return httpx.Response(status, text="test-key-never-log")
    evaluator.transport = httpx.MockTransport(handler)
    with pytest.raises(EvaluationError) as caught:
        asyncio.run(evaluator.evaluate("state", {"x": {"type": "boolean"}}, stage="test"))
    assert "test-key" not in str(caught.value)
    assert caught.value.status_code == status and len(calls) == 1


def test_analysis_drives_score_category_and_preserves_generated_text(evaluator):
    async def evaluate(state, questions, **kwargs):
        assert "source_text" in state and "edition_window" in state
        return {"impact": score(questions["impact"], 4), "novelty": score(questions["novelty"], 5),
                "recap": choice(questions["recap"], "new_development"),
                "category": choice(questions["category"], "crypto")}
    evaluator.evaluate = evaluate
    article = item()
    article.ai_summary = "Existing summary"
    asyncio.run(evaluator.analyze(article, ["crypto", "ai"], edition_window_for(datetime(2026, 9, 22, tzinfo=timezone.utc), "Asia/Shanghai")))
    assert article.ai_score == 8.5
    assert article.metadata["category"] == "crypto"
    assert article.ai_summary == "Existing summary"
    assert article.metadata["evaluation"]["model"] == "typesafe-ai/jev"


def test_legacy_zero_cannot_override_jev(evaluator):
    async def evaluate(state, questions, **kwargs):
        return {"impact": score(questions["impact"], 5), "novelty": score(questions["novelty"], 5),
                "recap": choice(questions["recap"], "new_development")}
    evaluator.evaluate = evaluate
    article = item(); article.ai_score = 0
    asyncio.run(evaluator.analyze(article, [], edition_window_for(datetime(2026, 9, 22, tzinfo=timezone.utc), "Asia/Shanghai")))
    assert article.ai_score == 10


def test_updates_merge_only_within_same_daily_edition(evaluator):
    async def evaluate(state, questions, **kwargs):
        return {key: choice(q, "update") for key, q in questions.items()}
    evaluator.evaluate = evaluate
    assert asyncio.run(evaluator.duplicates([item(0), item(1)], TOPIC_DEDUP_SYSTEM)) == {"duplicates": []}
    assert asyncio.run(evaluator.duplicates([item(0), item(1)], DAILY_EVENT_DEDUP_SYSTEM)) == {"duplicates": [[0, 1]]}


def test_low_probability_duplicate_does_not_remove_news(evaluator):
    async def evaluate(state, questions, **kwargs):
        return {key: {"type": "choice", "choice": "duplicate", "probabilities": {
            "duplicate": 0.6, "update": 0.2, "distinct": 0.1, "uncertain": 0.1}} for key in questions}
    evaluator.evaluate = evaluate
    assert asyncio.run(evaluator.duplicates([item(0), item(1)], TOPIC_DEDUP_SYSTEM)) == {"duplicates": []}


def test_every_pair_is_checked_with_bounded_questions(evaluator):
    seen = []
    async def evaluate(state, questions, **kwargs):
        assert len(questions) <= 28 and len(state) <= 8
        seen.extend(questions)
        return {key: choice(q, "distinct") for key, q in questions.items()}
    evaluator.evaluate = evaluate
    asyncio.run(evaluator.duplicates([item(i) for i in range(24)], TOPIC_DEDUP_SYSTEM))
    assert len(seen) == len(set(seen)) == 276


def test_dedup_failure_never_calls_generation_model(monkeypatch):
    class Evaluator:
        async def duplicates(self, *args): raise EvaluationError("test")
    class Client:
        async def complete(self, **kwargs): raise AssertionError("generation model called")
    monkeypatch.setattr("src.ai.topic_dedup.create_evaluator", lambda _: Evaluator())
    with pytest.raises(EvaluationError, match="test"):
        asyncio.run(duplicate_groups(Client(), [item(0), item(1)], [[0, 1]]))


def test_prefilter_uses_jev_without_text_call(monkeypatch):
    class Evaluator:
        async def prefilter(self, batch): return {index: float(index) for index, _ in batch}
    class Client:
        async def complete(self, **kwargs): raise AssertionError("text call")
    monkeypatch.setattr("src.ai.prefilter.create_evaluator", lambda _: Evaluator())
    result = asyncio.run(ContentPrefilter(Client(), batch_size=5).select([item(i) for i in range(12)], maximum=6, reserve_per_category=1))
    assert result.evaluated == 12 and result.removed == 6


def test_degraded_scoring_is_not_cached(tmp_path):
    article = item(); article.metadata["evaluation_degraded"] = True
    cache = AnalysisResultCache(tmp_path / "cache.json", model="jev")
    cache.store_analysis(article)
    assert not cache.restore_analysis(item())


def test_grounding_rejects_unsupported_and_uncertain(evaluator):
    for selected in ("unsupported", "insufficient"):
        async def evaluate(state, questions, **kwargs):
            return {"grounding": choice(questions["grounding"], selected)}
        evaluator.evaluate = evaluate
        assert not asyncio.run(evaluator.verify({"source": "x", "generated": "y"}))


def test_analyzer_uses_only_jev_and_clears_stale_scores(monkeypatch, tmp_path):
    class Evaluator:
        fail = False
        async def analyze(self, article, *args):
            if self.fail: raise EvaluationError("temporary")
            article.ai_score = 9
    evaluator = Evaluator()
    monkeypatch.setattr("src.ai.analyzer.create_evaluator", lambda _: evaluator)
    class Client:
        async def complete(self, **kwargs):
            raise AssertionError("generation model called")
    analyzer = ContentAnalyzer(Client())
    article = item()
    asyncio.run(analyzer.analyze_batch([article]))
    assert article.ai_score == 9 and article.ai_summary == article.title and article.ai_tags == []
    evaluator.fail = True
    asyncio.run(analyzer.analyze_batch([article]))
    assert article.ai_score is None and article.metadata["evaluation_error"]["code"] == "temporary"
    cache = AnalysisResultCache(tmp_path / "pending.json", model="jev")
    cache.store_analysis(article)
    assert not cache.restore_analysis(item())


def test_generation_cannot_bypass_check_through_translation(monkeypatch):
    from src.ai.enricher import ContentEnricher
    class Evaluator:
        async def verify(self, state): return False
    monkeypatch.setattr("src.ai.enricher.create_evaluator", lambda _: Evaluator())
    class Client:
        async def complete(self, **kwargs):
            return '{"title_zh":"标题","summary_zh":"未经证实的结论"}'
    enricher = ContentEnricher(Client())
    with pytest.raises(EvaluationError, match="unsupported_translation"):
        asyncio.run(enricher._translate_item(item()))


def test_cache_separates_edition_windows_and_persists_evaluation(tmp_path):
    cache = AnalysisResultCache(tmp_path / "cache.json", model="jev")
    article = item(); article.metadata["evaluation"] = {"model": "typesafe-ai/jev"}
    cache.analysis_context = ["first-start", "first-end"]
    cache.store_analysis(article)
    restored = item()
    assert cache.restore_analysis(restored)
    assert restored.metadata["evaluation"]["model"] == "typesafe-ai/jev"
    cache.analysis_context = ["second-start", "second-end"]
    assert not cache.restore_analysis(item())


def test_prefilter_failure_passes_to_full_analysis_without_replacement_scores(monkeypatch):
    class Evaluator:
        async def prefilter(self, batch): raise EvaluationError("timeout")
    class Client:
        async def complete(self, **kwargs): raise AssertionError("generation model called")
    monkeypatch.setattr("src.ai.prefilter.create_evaluator", lambda _: Evaluator())
    result = asyncio.run(ContentPrefilter(Client(), batch_size=5).select([item(i) for i in range(12)], maximum=6))
    assert result.evaluated == 0 and result.failed_batches == 3
    assert len(result.items) == 12


def test_invalid_jev_cache_is_recomputed_without_generation_model(monkeypatch):
    calls = []
    class Evaluator:
        async def duplicates(self, *args):
            calls.append(1)
            return {"duplicates": [[0, 1]]}
    class Client:
        async def complete(self, **kwargs): raise AssertionError("generation model called")
    class Cache:
        def get_comparison(self, *args): return {"duplicates": [[0, 100]]}
        def store_comparison(self, *args): pass
    monkeypatch.setattr("src.ai.topic_dedup.create_evaluator", lambda _: Evaluator())
    assert asyncio.run(duplicate_groups(Client(), [item(0), item(1)], [[0, 1]], cache=Cache())) == [[0, 1]]
    assert calls == [1]


def test_schema_errors_keep_specific_reason_without_provider_text(evaluator, monkeypatch):
    async def no_sleep(_): pass
    monkeypatch.setattr("src.ai.evaluator.asyncio.sleep", no_sleep)
    evaluator.transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"secret": "do-not-log"}))
    with pytest.raises(EvaluationError) as caught:
        asyncio.run(evaluator.evaluate("state", {"x": {"type": "boolean"}}, stage="test"))
    assert caught.value.code == "missing_answers"
    assert "do-not-log" not in str(caught.value)


@pytest.mark.parametrize("all_failed", [False, True])
def test_unscored_items_cannot_enter_ranking(tmp_path, monkeypatch, all_failed):
    from src.models import Config, FilteringConfig, SourcesConfig
    from src.orchestrator import BMTNewsOrchestrator
    from src.storage.manager import StorageManager
    config = Config(ai=AIConfig(provider="deepseek", model="test", api_key_env="TEST",
        evaluator=EvaluationConfig(enabled=True), result_cache_enabled=False),
        sources=SourcesConfig(), filtering=FilteringConfig())
    orchestrator = BMTNewsOrchestrator(config, StorageManager(data_dir=str(tmp_path / "data")))
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda _: object())
    class Evaluator:
        async def analyze(self, article, *args):
            if all_failed or article.id == "test-0": raise EvaluationError("timeout")
            article.ai_score = 8.5
    monkeypatch.setattr("src.ai.analyzer.create_evaluator", lambda _: Evaluator())
    if all_failed:
        with pytest.raises(RuntimeError, match="No candidates have a valid Jev score"):
            asyncio.run(orchestrator._analyze_content([item(0), item(1)]))
    else:
        result = asyncio.run(orchestrator._analyze_content([item(0), item(1)]))
        assert [row.id for row in result] == ["test-1"]
