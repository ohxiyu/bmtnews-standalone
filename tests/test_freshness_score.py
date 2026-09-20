"""Offline contract tests, not evidence of live model accuracy."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from rich.console import Console

from src.ai.analyzer import ContentAnalyzer
from src.ai.prompts import CONTENT_ANALYSIS_SYSTEM
from src.edition import edition_window_for_date
from src.models import AIConfig, Config, ContentItem, FilteringConfig, SourcesConfig, SourceType
from src.orchestrator import BMTNewsOrchestrator
from src.storage.manager import StorageManager


def item():
    return ContentItem(
        id="clarity-recap", source_type=SourceType.RSS,
        title="How the Clarity Act's Defeat Handed the SEC and CFTC the Wheel on Crypto",
        url="https://decrypt.co/378688/how-clarity-act-defeat-sec-cftc-wheel-crypto",
        published_at=datetime(2026, 9, 19, 17, 1, 3, tzinfo=timezone.utc),
        content="A bruising week: on Tuesday the Senate failed to advance the bill. "
                "The SEC released its measure Thursday.",
    )


def test_recap_zero_filtered_and_new_development_survives():
    calls = []
    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(dict(score=0 if len(calls) == 1 else 8,
                               reason="fixture", summary="fixture", tags=[]))
    window = edition_window_for_date("2026-09-20", "Asia/Shanghai")
    analyzer = ContentAnalyzer(SimpleNamespace(complete=complete), edition_window=window)
    old = item()
    new = item().model_copy(update={"id": "new", "content": "Today a new vote passed."})
    asyncio.run(analyzer.analyze_batch([old, new]))
    assert len(calls) == 2  # Exactly one existing scoring call per uncached item.
    system = calls[0]["system"]
    assert "2026-09-19T07:00:00+08:00" in system
    assert "2026-09-20T07:00:00+08:00" in system
    assert "Score 0 for a recap" in system
    assert "do not invent event dates" in system
    assert "2026-09-19T17:01:03+00:00" in system
    assert len(system) < len(CONTENT_ANALYSIS_SYSTEM)
    orchestrator = BMTNewsOrchestrator.__new__(BMTNewsOrchestrator)
    orchestrator.config = SimpleNamespace(filtering=FilteringConfig(ai_score_threshold=6))
    orchestrator.console = Console()
    selected = asyncio.run(orchestrator.filter_items(
        [old, new], topic_dedup=False, apply_balance=False, log=False,
    ))
    assert [row.id for row in selected.items] == ["new"]


def test_collection_window_uses_publication_not_execution_clock():
    calls = []
    async def complete(**kwargs):
        calls.append(kwargs)
        return json.dumps(dict(score=0, reason="recap", summary="fixture", tags=[]))
    asyncio.run(ContentAnalyzer(SimpleNamespace(complete=complete)).analyze_batch([item()]))
    assert "2026-09-19T07:00:00+08:00" in calls[0]["system"]
    assert "2026-09-20T07:00:00+08:00" in calls[0]["system"]


def test_existing_cached_score_is_not_rescored(tmp_path, monkeypatch):
    config = Config(ai=AIConfig(provider="openai", model="test", api_key_env="TEST",
                               result_cache_path=str(tmp_path / "cache.json")),
                    sources=SourcesConfig(), filtering=FilteringConfig())
    orchestrator = BMTNewsOrchestrator(config, StorageManager(data_dir=str(tmp_path / "data")))
    cached = item()
    cached.ai_score = 8
    orchestrator._result_cache().store_analysis(cached)
    def forbidden(*args, **kwargs):
        raise AssertionError("Cache hit must not create an AI client")
    monkeypatch.setattr("src.orchestrator.create_ai_client", forbidden)
    result = asyncio.run(orchestrator._analyze_content(
        [item()], edition_window=edition_window_for_date("2026-09-20", "Asia/Shanghai"),
    ))
    assert result[0].ai_score == 8  # Explicit no-rescoring rollout limitation.
