"""Bounded, read-only replay from cached public inputs; never publish or collect."""
import asyncio
import json
import subprocess
from datetime import datetime
from itertools import combinations
from pathlib import Path

from src.ai.client import create_ai_client
from src.ai.topic_dedup import duplicate_groups
from src.models import Config, ContentItem
from src.orchestrator import BMTNewsOrchestrator
from src.threads import fingerprint, same_thread


def git_json(path):
    return json.loads(subprocess.check_output(["git", "show", path], text=True))


def inputs():
    config = Config.model_validate(git_json("origin/main:data/config.github.json"))
    # Construct only the cache accessor, never publishers/collectors.
    accessor = object.__new__(BMTNewsOrchestrator)
    accessor.config = config
    accessor._analysis_cache = None
    cache = accessor._result_cache()
    state = git_json("origin/gh-pages:_data/bmtnews_state.json")
    staged = json.loads(Path("data/staging-items.json").read_text())
    history = [ContentItem.model_validate(row) for row in state["dedup_history"]]
    items = []
    seen = {str(item.url) for item in history}
    # Preserve the failed edition's legacy 08:00 window, not PR91's new cutoff.
    end = datetime.fromisoformat(state["date"] + "T08:00:00+08:00")
    from datetime import timedelta
    for row in staged["items"]:
        item = ContentItem.model_validate(row)
        if not end - timedelta(days=1) <= item.published_at < end:
            continue
        if str(item.url) in seen:
            continue
        seen.add(str(item.url))
        if cache.restore_analysis(item) and (item.ai_score or 0) >= config.filtering.ai_score_threshold:
            items.append(item)
    items.sort(key=lambda item: item.ai_score or 0, reverse=True)
    items = history + items
    prints = [fingerprint(title_zh=str(i.metadata.get("title_zh") or ""),
                          title_en=str(i.metadata.get("title_en") or i.title),
                          summary_zh=str(i.metadata.get("detailed_summary_zh") or ""),
                          summary_en=str(i.ai_summary or ""), tags=i.ai_tags) for i in items]
    parents = list(range(len(items)))
    def root(i):
        while parents[i] != i:
            i = parents[i]
        return i
    for a, b in combinations(range(len(items)), 2):
        if same_thread(prints[a], prints[b]):
            parents[root(b)] = root(a)
    groups = {}
    for i in range(len(items)):
        groups.setdefault(root(i), []).append(i)
    # Explicitly reconstruct production's 6-item blocks / <=12-item calls.
    batches = []
    for group in groups.values():
        if len(group) < 2:
            continue
        blocks = [group[i:i+6] for i in range(0, len(group), 6)]
        batches.extend([group] if len(blocks) == 1 else [a+b for a,b in combinations(blocks, 2)])
    return config, items, batches, cache.snapshot()


async def run():
    config, items, batches, cache = inputs()
    print(json.dumps({"mode": "cached_subset_not_exact_historical_replay", "items": len(items),
                      "batches": [len(b) for b in batches], "cache": cache, "call_limit": 12}))
    client = create_ai_client(config.ai)
    # Disable SDK retries as well; the total HTTP call ceiling is twelve.
    client.client = client.client.with_options(max_retries=0)
    calls = 0
    class BoundedClient:
        async def complete(self, **kwargs):
            nonlocal calls
            if calls >= 12:
                raise RuntimeError("diagnostic_budget_exhausted")
            calls += 1
            return await client.complete(**kwargs)
    try:
        for batch in batches:
            await duplicate_groups(BoundedClient(), items, [batch])
        print(json.dumps({"result": "all_replayed_batches_valid", "calls": calls}))
    except RuntimeError:
        # The shared dedup logger emits only its allowlisted diagnosis.
        print(json.dumps({"result": "stopped_on_failure_or_budget", "calls": calls}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    asyncio.run(run())
