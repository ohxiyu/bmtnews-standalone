"""Lightweight token usage tracker shared across AI clients.

This module keeps a simple in-memory counter of tokens used during a single
BMTNews run, so the orchestrator can print a summary at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict


@dataclass
class ProviderUsage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class TokenUsageSnapshot:
    total_input_tokens: int
    total_output_tokens: int
    per_provider: Dict[str, ProviderUsage] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


_provider_usage: Dict[str, ProviderUsage] = {}
_task_usage: dict[str, dict] = {}


def record_usage(provider: str, input_tokens: int = 0, output_tokens: int = 0, *,
                 model: str = "unspecified", stage: str = "other",
                 cached_input_tokens: int = 0, reasoning_tokens: int = 0,
                 elapsed_ms: int = 0, finish_reason: str | None = None) -> None:
    """Accumulate token usage for a given provider.

    Args:
        provider: Provider identifier, e.g. "openai", "anthropic".
        input_tokens: Prompt / input tokens used.
        output_tokens: Completion / output tokens used.
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return

    usage = _provider_usage.setdefault(provider, ProviderUsage())
    usage.input_tokens += max(0, input_tokens)
    usage.output_tokens += max(0, output_tokens)
    key = f"{provider}:{model}:{stage}"
    task = _task_usage.setdefault(key, {
        "provider": provider, "model": model, "stage": stage, "calls": 0,
        "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
        "reasoning_tokens": 0, "elapsed_ms": 0, "truncated_calls": 0,
    })
    task["calls"] += 1
    for name, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens),
                        ("cached_input_tokens", cached_input_tokens), ("reasoning_tokens", reasoning_tokens),
                        ("elapsed_ms", elapsed_ms)):
        task[name] += max(0, int(value or 0))
    task["truncated_calls"] += int(finish_reason == "length")


def get_usage_snapshot() -> TokenUsageSnapshot:
    """Return a snapshot of accumulated token usage."""
    total_in = sum(u.input_tokens for u in _provider_usage.values())
    total_out = sum(u.output_tokens for u in _provider_usage.values())
    return TokenUsageSnapshot(
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        per_provider={key: replace(value) for key, value in _provider_usage.items()},
    )


def reset_usage() -> None:
    """Reset all accumulated usage (useful for tests)."""
    _provider_usage.clear()
    _task_usage.clear()


def task_usage_snapshot() -> list[dict]:
    """Only numeric usage and model/stage labels; never prompts or responses."""
    return [dict(value) for _, value in sorted(_task_usage.items())]
