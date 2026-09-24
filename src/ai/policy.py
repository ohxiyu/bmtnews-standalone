"""Explicit, reversible per-task policy for OpenAI-compatible requests."""
from . import prompts


def prompt_stage(system: str) -> str:
    from .prefilter import PREFILTER_SYSTEM
    if system == PREFILTER_SYSTEM:
        return "prefilter"
    for name, value in vars(prompts).items():
        if name.endswith("_SYSTEM") and value == system:
            return name.removesuffix("_SYSTEM").lower()
    if system.startswith("You are a translator."):
        return "translation"
    return "other"


def usage_stage(system: str) -> str:
    """Label dynamic scoring prompts without changing their request policy."""
    stage = prompt_stage(system)
    if stage != "other":
        return stage
    analysis_prefix = prompts.CONTENT_ANALYSIS_SYSTEM.split("Consider:\n", 1)[0]
    if system.startswith(analysis_prefix) and "Scoring granularity and calibration:" in system:
        return "content_analysis"
    return stage


SIMPLE_BUDGETS = {
    # Dedup returns indices for at most 24 stories, not a reasoning essay.
    # DeepSeek's implicit thinking can consume the entire output budget.
    "topic_dedup": 1536,
    "daily_event_dedup": 1536,
    # Bilingual overview is a short extraction from already enriched stories.
    "edition_overview": 2048,
    "prefilter": 2048,
    "content_analysis": 1536,
    "concept_extraction": 768,
    "translation": 2048,
}
