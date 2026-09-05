import asyncio
from types import SimpleNamespace

import pytest

from src.ai.client import OpenAIClient
from src.ai.prompts import CONTENT_ANALYSIS_SYSTEM, EVENT_RELATION_SYSTEM
from src.ai.tokens import reset_usage, task_usage_snapshot
from src.models import AIConfig


def client_fixture(monkeypatch, *, finish_reason="stop"):
    calls = []
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, prompt_cache_hit_tokens=60),
            choices=[SimpleNamespace(finish_reason=finish_reason, message=SimpleNamespace(content='{}'))],
        )
    monkeypatch.setenv("TEST_AI_KEY", "test-only")
    monkeypatch.setattr("src.ai.client.AsyncOpenAI", lambda **kwargs: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    client = OpenAIClient(AIConfig(provider="deepseek", model="deepseek-v4-flash",
                                  api_key_env="TEST_AI_KEY", economy_mode=True))
    reset_usage()
    return client, calls


def test_simple_tasks_use_explicit_non_thinking_budget(monkeypatch):
    client, calls = client_fixture(monkeypatch)
    asyncio.run(client.complete(CONTENT_ANALYSIS_SYSTEM, "test"))
    assert calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}
    assert calls[0]["max_tokens"] == 1536
    usage = task_usage_snapshot()[0]
    assert usage["stage"] == "content_analysis"
    assert usage["cached_input_tokens"] == 60
    assert usage["calls"] == 1


def test_event_reasoning_is_explicit_and_temperature_is_not_sent(monkeypatch):
    client, calls = client_fixture(monkeypatch)
    asyncio.run(client.complete(EVENT_RELATION_SYSTEM, "test", max_tokens=4096))
    assert calls[0]["reasoning_effort"] == "low"
    assert calls[0]["extra_body"]["thinking"]["type"] == "enabled"
    assert "temperature" not in calls[0]


def test_truncated_output_is_metered_but_not_accepted(monkeypatch):
    client, _ = client_fixture(monkeypatch, finish_reason="length")
    with pytest.raises(ValueError, match="truncated"):
        asyncio.run(client.complete(CONTENT_ANALYSIS_SYSTEM, "test"))
    assert task_usage_snapshot()[0]["truncated_calls"] == 1
