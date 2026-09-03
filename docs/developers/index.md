---
layout: default
title: BMTNews API and Agent Developer Resources
description: Public BMTNews REST API, OpenAPI specification, feeds, agent instructions, caching, errors, and attribution guidance.
permalink: /developers/
interface_language: en
eyebrow: BMTNEWS API
hide_language_toggle: true
---

BMTNews exposes a public, read-only REST surface for agents, research tools,
notebooks, and feed readers. No API key or account is required. The files are
generated with each daily edition and served from Cloudflare's edge. Clients
should cache responses according to their HTTP headers, avoid unnecessary
polling, and retain the original publisher URL when presenting a story.

## REST endpoints

- [`GET /api/latest.json`](/api/latest.json) returns the newest complete edition.
- [`GET /api/editions.json`](/api/editions.json) lists available edition dates.
- `GET /editions/{date}/edition.json` returns one dated edition, where `date`
  uses `YYYY-MM-DD`.
- [`GET /api/events.json`](/api/events.json) lists events with at least two
  verified material updates, newest change first.
- `GET /api/events/{event_id}.json` returns one chronological event timeline,
  including status, current state, update type, story IDs, and source evidence.
- [`GET /openapi.json`](/openapi.json) is the authoritative OpenAPI 3.1
  description. Every operation has a unique `operationId`, typed parameters,
  response schemas, and an explicit JSON error response.

The API is intentionally read-only. It does not expose source-management,
editorial, authentication, webhook, or publishing operations. A successful
edition response contains bilingual titles and summaries, ranking, score,
category, source attribution, original URLs, tags, source-confirmation count,
and optional thread data. The latest edition also includes publication-window,
run-statistic, overview, and market-snapshot fields when available.

```bash
curl -sS https://bmt.news/api/latest.json
curl -sS https://bmt.news/api/editions.json
curl -sS https://bmt.news/editions/2026-08-24/edition.json
curl -sS https://bmt.news/api/events.json
```

## Errors and compatibility

Unknown API routes return an HTTP `404` with an `application/json` body:

```json
{
  "error": {
    "code": "not_found",
    "message": "No API endpoint exists at this path.",
    "resolution": "Read /openapi.json or /developers/ and use a documented endpoint."
  }
}
```

Unsupported methods return `405 method_not_allowed`. All public JSON responses
allow cross-origin reads. Agents should first read `/api/editions.json` rather
than guessing historical dates.

## Markdown and agent discovery

The Chinese and English homepages support HTTP content negotiation. Send an
`Accept` header that prefers `text/markdown` to receive CommonMark-style text
from the same canonical URL. Responses declare
`Content-Type: text/markdown; charset=utf-8` and
`Vary: Accept, Accept-Encoding`. Browser requests continue to receive the
normal HTML page. Stable Markdown files are also available at
[`/index.html.md`](/index.html.md) and [`/en/index.html.md`](/en/index.html.md).

Start agent discovery with [`/llms.txt`](/llms.txt), and use
[`/sitemap.xml`](/sitemap.xml) for the complete indexable page inventory.
Category-specific Atom feeds are available for
[crypto](/feeds/crypto-en.xml), [AI and technology](/feeds/technology-en.xml),
and [policy](/feeds/policy-en.xml), with corresponding `-zh.xml` files.

## Attribution and limits

BMTNews analysis is not investment advice. Third-party titles, reporting, and
other source materials remain subject to their original rights. When quoting or
summarizing an item, cite the original URL from the API and identify BMTNews as
the ranking and analysis layer. See [Legal and content rights](/legal/) for the
full boundary. For corrections, rights concerns, or security reports, use the
channels on the [contact page](/contact/).
