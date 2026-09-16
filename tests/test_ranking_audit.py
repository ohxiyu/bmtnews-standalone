import asyncio
import json
import re
from datetime import datetime, timedelta, timezone

import pytest

from src.models import AIConfig, Config, ContentItem, FilteringConfig, SourcesConfig, SourceType
from src.orchestrator import BMTNewsOrchestrator
from src.storage.manager import StorageManager


def story(i, title=None, score=8.5):
    return ContentItem(id=str(i), title=title or f"Distinct story {i}",
        url=f"https://example.com/{i}", source_type=SourceType.RSS,
        published_at=datetime(2026, 9, 16, tzinfo=timezone.utc) + timedelta(minutes=i),
        ai_score=score, metadata={"category": "crypto-markets"})


def orchestrator(tmp_path):
    return BMTNewsOrchestrator(Config(ai=AIConfig(provider="openai", model="test", api_key_env="TEST"),
        sources=SourcesConfig(), filtering=FilteringConfig(max_items=3, minimum_display_items=3)),
        StorageManager(data_dir=str(tmp_path)))


def test_coinex_cross_cluster_duplicates_are_actually_compared(tmp_path, monkeypatch):
    runner = orchestrator(tmp_path)
    items = [story(0, "CoinEx to Close Exchange on Ninth Anniversary"),
             story(1, "CoinEx Shuts Down: Withdraw Your Balance in Time - CryptoTicker"),
             story(2, "Crypto exchange CoinEx to shut down after 9 years, citing market slump"),
             story(3, "CoinEx launches a separate wallet", score=8), story(4, score=7)]
    calls = []
    class Client:
        async def complete(self, **kw):
            titles = re.findall(r"\[\d+\] (.*)", kw["user"])
            calls.append(titles)
            assert len(titles) <= 24
            group = [i for i, title in enumerate(titles) if any(s in title for s in ("Close Exchange", "Shuts Down", "shut down"))]
            return json.dumps({"duplicates": [group] if len(group) > 1 else []})
    monkeypatch.setattr("src.orchestrator.same_thread", lambda *a: False)
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda *a: Client())
    pool, result = asyncio.run(runner._audit_daily_ranking(items, runner.apply_balanced_digest(items)))
    assert len(calls) == 2
    assert [i.id for i in result.items] == ["2", "3", "4"]
    assert {i.id for i in pool} == {"2", "3", "4"}


def test_refill_is_rechecked_and_stops_at_bound(tmp_path, monkeypatch):
    runner = orchestrator(tmp_path)
    items = [story(i) for i in range(12)]
    calls = []
    class Client:
        async def complete(self, **kw):
            calls.append(kw)
            return '{"duplicates": [[0,1,2]]}'
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda *a: Client())
    _, result = asyncio.run(runner._audit_daily_ranking(items, runner.apply_balanced_digest(items)))
    assert len(calls) == 3
    assert len(result.items) == 1  # no unchecked fourth refill


def test_invalid_final_audit_fails_closed(tmp_path, monkeypatch):
    runner = orchestrator(tmp_path)
    class Client:
        async def complete(self, **kw):
            return '{"duplicates": [[0,0]]}'
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda *a: Client())
    items = [story(0), story(1)]
    with pytest.raises(RuntimeError, match="refusing to publish"):
        asyncio.run(runner._audit_daily_ranking(items, runner.apply_balanced_digest(items)))


def test_final_audit_has_a_hard_size_bound(tmp_path):
    runner = orchestrator(tmp_path)
    from src.orchestrator import BalancedDigestResult
    items = [story(i) for i in range(25)]
    with pytest.raises(RuntimeError, match="24-item"):
        asyncio.run(runner._audit_daily_ranking(items, BalancedDigestResult(items=items)))


def test_quota_refill_preserves_crypto_target_side_caps_and_score_order(tmp_path, monkeypatch):
    from pathlib import Path
    runner = orchestrator(tmp_path)
    production = json.loads((Path(__file__).resolve().parents[1] / "data/config.github.json").read_text())
    runner.config.filtering = FilteringConfig.model_validate(production["filtering"])
    items = []
    for category in ("exchange-operations", "crypto-markets", "crypto-protocols", "ai-labs", "macro-regulation"):
        for _ in range(6):
            entry = story(len(items), score=9 - len(items) / 100)
            entry.metadata.update(category=category, feed_name=f"source-{entry.id}")
            items.append(entry)
    calls = []
    class Client:
        async def complete(self, **kw):
            titles = re.findall(r"\[\d+\] Distinct story (\d+)", kw["user"])
            calls.append(titles)
            same = [i for i, value in enumerate(titles) if int(value) < 3]
            return json.dumps({"duplicates": [same] if len(same) > 1 else []})
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda *a: Client())
    _, result = asyncio.run(runner._audit_daily_ranking(items, runner.apply_balanced_digest(items)))
    assert len(result.items) <= 14
    assert sum(result.group_counts.get(g, 0) for g in runner.config.filtering.primary_groups) >= 9
    assert result.group_counts.get("technology", 0) <= 3
    assert result.group_counts.get("regulation", 0) <= 2
    assert [i.ai_score for i in result.items] == sorted([i.ai_score for i in result.items], reverse=True)
    assert sum(int(i.id) < 3 for i in result.items) == 1
    assert len(calls) > 1


def test_no_duplicates_preserve_order_and_use_one_pass(tmp_path, monkeypatch):
    runner = orchestrator(tmp_path)
    class Client:
        async def complete(self, **kw):
            return '{"duplicates": []}'
    monkeypatch.setattr("src.orchestrator.create_ai_client", lambda *a: Client())
    items = [story(0, score=7), story(1, score=9), story(2, score=8)]
    _, result = asyncio.run(runner._audit_daily_ranking(items, runner.apply_balanced_digest(items)))
    assert [i.id for i in result.items] == ["1", "2", "0"]
