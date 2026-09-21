---
layout: default
title: Scoring System
---

# Scoring System

After fetching content from all sources, BMTNews uses an AI model to score each item on a 0-10 scale. This determines what appears in the daily summary.

## Production evaluation policy

With `ai.evaluator.enabled`, Jev is the only scoring and classification authority.
All candidates use rubric `jev-news-v2`: impact and novelty each range from 0 to 5,
with final score `round(2 * (0.75 * impact + 0.25 * novelty), 1)`. A high-confidence
old recap receives zero. DeepSeek scores, categories and freshness vetoes do not
participate. DeepSeek generates selected content after ranking.

Each evaluation request has at most two attempts. Account errors do not retry.
Failed scoring has `ai_score=null` and a sanitized `evaluation_error`; it is not a
zero-quality judgment, is not cached, and cannot enter ranking. If every attempted
candidate fails, publication stops. Partial failures leave the remaining uniformly
scored candidates eligible; existing quality thresholds and quotas still apply.

Prefilter errors pass those candidates to full Jev scoring without assigning
replacement scores. Dedup errors stop publication without calling DeepSeek.
Successful caches are separated by rubric/configuration and edition window, so
old mixed-policy results cannot enter the new ranking. Generation verification
still requires source support; translation cannot bypass it. Diagnostic errors
preserve HTTP/schema/unsupported distinctions without logging provider payloads.

When evaluation is explicitly disabled, the legacy standalone generation-model
pipeline remains available for existing configurations; it is never an automatic
fallback within an enabled Jev run.

## Filtering

After scoring, items are filtered by `filtering.ai_score_threshold` (default: `7.0`) and sorted by score descending. Optional balanced digest quotas are then applied before enrichment.

```json
{
  "filtering": {
    "ai_score_threshold": 7.0,
    "time_window_hours": 24,
    "max_items": 20,
    "category_groups": {
      "ai": {
        "limit": 5,
        "categories": ["ai-news", "ai-tools", "machine-learning"]
      }
    }
  }
}
```

`category_groups` limits each configured category group independently.
`max_items` caps the merged result. Both fields are optional; without them,
scoring and filtering behave as before.

Items scoring 9.0 or above are featured in the "Today's Highlights" section of the summary.

## Enrichment

Items that pass the score threshold and any balanced digest limits go through a second AI pass for enrichment (`src/ai/enricher.py`):

1. **Concept extraction** — AI identifies 1-3 technical concepts in the item that may need explanation.
2. **Web search** — Each concept is searched via DuckDuckGo to gather grounding context.
3. **Structured analysis** — The item content and search results are sent to AI, which produces:
   - `whats_new` — what specifically happened or changed
   - `why_it_matters` — significance and impact
   - `key_details` — notable technical details or caveats
   - `background` — background knowledge for readers without deep domain expertise

These fields are combined into a `detailed_summary` stored in the item's metadata and used in the final daily summary.
