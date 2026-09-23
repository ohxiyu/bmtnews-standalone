---
layout: default
title: Scoring System
---

# Scoring System

After fetching content from all sources, BMTNews uses an AI model to score each item on a 0-10 scale. This determines what appears in the daily summary.

## Production scoring policy

The configured generation model (DeepSeek `deepseek-flash` in production) scores
each uncached candidate directly from 0 to 10 and selects its category in the
same analysis call. The prompt's 0–2, 3–4, 5–6, 7–8 and 9–10 anchors define
the scale. The fixed edition window makes old recaps score zero unless they
contain a concrete new development. Invalid output or exhausted retries score
zero and are not stored in the analysis cache. Prefilter failure keeps the
candidate for full analysis.

The run report counts scores by producing model; each new archive row includes
`score_model`. Historical scores are not rewritten. Analysis cache fingerprints
include the configured scorer and a new direct-scoring revision, so scores from
the retired evaluation policy are not reused. Cache entries expire after 30
days under the production configuration.

URL deduplication, the event catalog and DeepSeek semantic comparison remain
separate stages. The semantic comparator retries invalid or transient responses
once, logs sanitized diagnostics, and stops publication if comparison remains
unavailable; it does not publish an unchecked batch.

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
2. **Web search** — Each concept is searched via DuckDuckGo to gather context.
3. **Structured analysis** — The item content and search results are sent to AI, which produces:
   - `whats_new` — what specifically happened or changed
   - `why_it_matters` — significance and impact
   - `key_details` — notable technical details or caveats
   - `background` — background knowledge for readers without deep domain expertise

These fields are combined into a `detailed_summary` stored in the item's metadata and used in the final daily summary.
The writing prompt asks for source-supported claims and reference URLs are
restricted to observed search results. There is no independent post-generation
factual verifier; a failed expansion falls back to translation and is reported
as degraded, rather than excluding the story.
