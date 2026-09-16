import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path

import pytest

from src.ai.result_cache import AnalysisResultCache
from src.ai.topic_dedup import duplicate_groups
from src.ai.prompts import DAILY_EVENT_DEDUP_SYSTEM, TOPIC_DEDUP_SYSTEM
from src.edition import edition_window_for
from src.models import ContentItem, SourceType


def stories(count):
    return [ContentItem(id=str(i), title=f"Story {i}", url=f"https://example.com/{i}",
                        source_type=SourceType.RSS, ai_summary=f"Summary {i}",
                        published_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
            for i in range(count)]


class Client:
    def __init__(self, response='{"duplicates": []}'):
        self.calls = []
        self.response = response

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def compare(client, items, **kwargs):
    return asyncio.run(duplicate_groups(client, items, [list(range(len(items)))], **kwargs))


def test_normal_14_story_audit_uses_one_call_and_all_pairs():
    client = Client()
    compare(client, stories(14))
    assert len(client.calls) == 1  # previously 3 overlapping calls / 28 excerpts
    assert len(re.findall(r"\[\d+\] Story", client.calls[0]["user"])) == 14


@pytest.mark.parametrize("count", [25, 37, 62])
def test_larger_clusters_keep_every_pair_and_24_item_bound(count):
    client = Client()
    compare(client, stories(count))
    seen = set()
    for call in client.calls:
        ids = [int(i) for i in re.findall(r"\[\d+\] Story (\d+)", call["user"])]
        assert len(ids) <= 24
        seen.update(combinations(ids, 2))
    assert seen == set(combinations(range(count), 2))


def test_validated_comparison_survives_restart_without_model_call(tmp_path):
    path = tmp_path / "cache.json"
    cache = AnalysisResultCache(path, model="deepseek:deepseek-flash")
    client = Client('{"duplicates": [[0, 1]]}')
    assert compare(client, stories(3), cache=cache) == [[0, 1]]
    cache.save()
    restarted = AnalysisResultCache(path, model="deepseek:deepseek-flash")
    next_client = Client()
    assert compare(next_client, stories(3), cache=restarted) == [[0, 1]]
    assert not next_client.calls
    assert restarted.comparison_hits == 1
    assert cache.comparison_misses == 1


@pytest.mark.parametrize("change", ["model", "prompt", "content", "date", "order", "policy"])
def test_cache_invalidates_changed_comparison_inputs(tmp_path, change):
    path = tmp_path / "cache.json"
    cache = AnalysisResultCache(path, model="old-model")
    items = stories(3)
    compare(Client(), items, cache=cache)
    cache.save()
    model = "new-model" if change == "model" else "old-model"
    revision = "changed" if change == "policy" else "2026-09-input-aware-v2"
    cache = AnalysisResultCache(path, model=model, prompt_revision=revision)
    if change == "content":
        items[0].ai_summary = "New material development"
    if change == "date":
        items[0].published_at += timedelta(days=1)
    if change == "order":
        items.reverse()
    client = Client()
    compare(client, items, cache=cache,
            system=DAILY_EVENT_DEDUP_SYSTEM if change == "prompt" else TOPIC_DEDUP_SYSTEM)
    assert len(client.calls) == 1


def test_expired_comparison_is_not_reused(tmp_path):
    cache = AnalysisResultCache(tmp_path / "cache.json", model="test")
    compare(Client(), stories(2), cache=cache)
    next(iter(cache.entries.values()))["stored_at"] = "2000-01-01T00:00:00+00:00"
    client = Client()
    compare(client, stories(2), cache=cache)
    assert len(client.calls) == 1


def test_invalid_response_never_cached_and_corrupt_hit_is_revalidated(tmp_path):
    cache = AnalysisResultCache(tmp_path / "cache.json", model="test")
    with pytest.raises(RuntimeError, match="invalid_response"):
        compare(Client('{"duplicates": [[0,0]]}'), stories(2), cache=cache)
    assert not cache.entries
    compare(Client(), stories(2), cache=cache)
    next(iter(cache.entries.values()))["value"] = {"duplicates": [[0, 99]]}
    client = Client('{"duplicates": [[0,1]]}')
    assert compare(client, stories(2), cache=cache) == [[0, 1]]
    assert len(client.calls) == 1


@pytest.mark.parametrize("status,reason,calls", [
    (402, "insufficient_balance", 1), (401, "authentication_failed", 1),
    (403, "permission_denied", 1), (429, "rate_limited", 2), (503, "provider_error", 2),
])
def test_provider_failures_are_bounded_and_sanitized(status, reason, calls):
    class ProviderError(Exception):
        status_code = status
    client = Client()
    async def fail(**kwargs):
        client.calls.append(kwargs)
        raise ProviderError("SECRET raw provider message")
    client.complete = fail
    with pytest.raises(RuntimeError, match=reason) as error:
        compare(client, stories(2))
    assert "SECRET" not in str(error.value)
    assert len(client.calls) == calls


def test_failed_jobs_explicitly_preserve_ai_cache():
    root = Path(__file__).parents[1]
    for workflow in ("daily-summary.yml", "feed-collection.yml"):
        text = (root / ".github/workflows" / workflow).read_text()
        assert "actions/cache/restore@v5" in text
        assert "actions/cache@v5" not in text
        assert "if: ${{ always() }}\n        uses: actions/cache/save@v5" in text
        assert text.count("${{ runner.os }}-bmtnews-pipeline-v2-${{ github.run_id }}-${{ github.run_attempt }}") == 2


def test_new_model_and_default_cutoff_on_previous_utc_date():
    root = Path(__file__).parents[1]
    assert json.loads((root / "data/config.github.json").read_text())["ai"]["model"] == "deepseek-flash"
    window = edition_window_for(datetime(2026, 9, 16, 23, 26, tzinfo=timezone.utc),
                                "Asia/Shanghai")
    assert window.date == "2026-09-17"
    assert window.end.isoformat() == "2026-09-17T07:00:00+08:00"
    assert window.end - window.start == timedelta(days=1)


def test_legacy_republication_can_keep_original_eight_am_cutoff():
    from src.edition import edition_window_for_date
    assert edition_window_for_date("2026-09-16", "Asia/Shanghai", 8).end.hour == 8


def test_first_new_cutoff_overlaps_old_window_without_losing_an_hour():
    from src.edition import edition_window_for_date
    old = edition_window_for_date("2026-09-16", "Asia/Shanghai", 8)
    new = edition_window_for_date("2026-09-17", "Asia/Shanghai")
    assert old.end - new.start == timedelta(hours=1)
    assert new.end - old.end == timedelta(hours=23)


def test_report_exposes_comparison_cache_counters():
    from src.run_report import render_markdown_report
    text = render_markdown_report({"kind": "daily_publish", "metrics": {"comparison_cache_hits": 3,
                                              "comparison_cache_misses": 2}})
    assert "去重比较缓存命中" in text
    assert "去重比较缓存未命中" in text


def test_cache_stores_only_validated_indices_not_arbitrary_model_fields(tmp_path):
    cache = AnalysisResultCache(tmp_path / "cache.json", model="test")
    compare(Client('{"duplicates": [], "untrusted_extra": "do not persist"}'),
            stories(2), cache=cache)
    assert next(iter(cache.entries.values()))["value"] == {"duplicates": []}
