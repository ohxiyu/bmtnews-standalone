<div align="center">
<h1>🛰️ BMTNews</h1>

<p><strong>An AI-curated daily intelligence briefing for crypto markets, AI, and policy.</strong></p>

[![License](https://img.shields.io/badge/license-MIT-green.svg?style=for-the-badge&logo=opensourceinitiative&logoColor=white)](LICENSE)
[![Tool uv](https://img.shields.io/badge/Tool-uv-4B275F?style=for-the-badge&logo=uv&logoColor=white)](https://github.com/astral-sh/uv)
[![Website](https://img.shields.io/badge/Website-bmt.news-263238?style=for-the-badge&logo=homepage&logoColor=white)](https://bmt.news/)
[![Daily](https://img.shields.io/github/actions/workflow/status/ohxiyu/bmtnews-standalone/daily-summary.yml?branch=main&label=Daily&style=for-the-badge&logo=date-fns&logoColor=white)](https://bmt.news/)
[![Commit](https://img.shields.io/github/commit-activity/m/ohxiyu/bmtnews-standalone?label=Commit&style=for-the-badge&logo=github&logoColor=white)](https://github.com/ohxiyu/bmtnews-standalone/commits/main)

📡 One edition a day, in English and Chinese · [**Read it live →**](https://bmt.news/)

[📖 Live Site](https://bmt.news/) · [🤖 Public API & Agents](https://bmt.news/developers/) · [📋 Configuration](project-docs/configuration.md) · [🧵 Archive & Threads](project-docs/archive-and-threads.md) · [✍️ Editorial Layer](project-docs/editorial.md) · [简体中文](README_zh.md) · [日本語](README_ja.md)

</div>

## What BMTNews is

Crypto moves faster than anyone can read. BMTNews watches exchange announcement
channels, protocol releases, regulators, and the crypto and AI press, then
publishes **one ranked edition every morning at 08:30 Asia/Shanghai** — typically
7 to 14 stories that actually mattered, each with background, market-impact
analysis, and links to the coverage behind it.

It runs entirely on GitHub Actions and GitHub Pages. There is no server, no
database, and no runtime service to keep alive: git is the storage layer, and
every published artifact is a static file.

## What makes an edition

```
collect every ~4h ─► cached scoring ─► incremental event timeline
          │
          └──────────► fixed 24h edition ─► dedup ─► quota balance ─► publish
                                                            │
              events · entities · JSON API · feeds · weekly review
```

- **Fixed publication window.** Every edition covers exactly 08:00→08:00 local
  time, so nothing is double-counted and nothing silently disappears.
- **Scored, not just collected.** Each story gets a 0–10 importance score with
  calibrated anchors; only what clears the bar is published.
- **Deduplicated twice.** Identical URLs merge first, then AI topic
  deduplication collapses the same event reported by different outlets — and
  records how many outlets carried it.
- **Balanced by quota.** Per-category and per-source caps stop one exchange or
  one outlet from taking over the page.
- **Never empty.** When nothing clears the threshold, the top-scored stories
  are published as a labelled low-signal edition rather than a blank page.

## Features

- **📡 Broad, redundant sourcing** — exchange Telegram channels, protocol GitHub
  releases, regulator feeds (SEC, CFTC, Fed), the crypto press, AI labs, Hacker
  News, GDELT, and Google News
- **📄 Full-article reading** — major feeds are fetched in full rather than
  summarized from an RSS snippet
- **🧵 Event timelines** — material changes become chronological updates;
  repeated coverage adds source evidence without inventing another update
- **🏷️ Entity pages** — everything published about a company, protocol, or
  regulator, aggregated and linkable
- **🔍 Background & market impact** — each story carries researched context and
  a transmission-path analysis (analysis, never investment advice)
- **✍️ Editorial layer** — insert your own stories, run a labelled ad slot, or
  suppress a story, from a form-based web admin
- **🌐 Bilingual** — English and Chinese editions from the same source set
- **🔌 Machine-readable** — edition and event JSON endpoints plus per-category
  Atom feeds
- **📬 Multi-channel delivery** — the site, Telegram, email, webhooks, and
  optional X distribution spread across peak reading hours

## Quick start

```bash
# 1. Install (uv recommended)
uv sync --extra trafilatura

# 2. Configure
cp data/config.example.json data/config.json
cp .env.example .env          # add your AI provider key
uv run bmtnews-wizard         # or edit data/config.json directly

# 3. Run one edition
uv run bmtnews --mode publish --hours 24 --cutoff-hour 8
```

Other modes:

| Command | What it does |
|---|---|
| `uv run bmtnews --mode fetch` | Collect new items, reuse cached scoring, and increment the restored event catalog |
| `uv run bmtnews --mode publish` | Build and publish one fixed-window edition |
| `uv run bmtnews --mode weekly` | Build the weekly review from the archive |
| `uv run bmtnews --mode x-post` | Post the next scheduled story to X |
| `uv run bmtnews-mcp` | Serve the pipeline and archive over MCP |

Full configuration reference: [project-docs/configuration.md](project-docs/configuration.md).

## Automation

| Workflow | Schedule | Purpose |
|---|---|---|
| `feed-collection` | every ~4h + 08:37 | Collect new sources, update event pages, and run a daily recovery check |
| `daily-summary` | 08:30 Asia/Shanghai | Build and publish the edition |
| `weekly-review` | Mondays 09:30 | Weekly digest and scoring calibration |
| `x-distribution` | publication + 5× daily | Drip-post top stories immediately, then at peak hours |
| `editorial-rebuild` | on edit | Republish after an editorial change |

## Documentation

- [Public API and agent resources](https://bmt.news/developers/) · [OpenAPI](https://bmt.news/openapi.json) · [llms.txt](https://bmt.news/llms.txt)
- [Configuration reference](project-docs/configuration.md)
- [Archive, threads, entities, and the JSON API](project-docs/archive-and-threads.md)
- [Editorial layer and web admin](project-docs/editorial.md)
- [X distribution](project-docs/x-distribution.md)
- [Sources](project-docs/scrapers.md) · [Scoring](project-docs/scoring.md) · [Extractors](project-docs/extractors.md)

## Contributing

Source suggestions and pull requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).

## License

BMTNews source code is available under the MIT License — see
[LICENSE](LICENSE). Generated editions and third-party news materials are not
covered by the software license; see [Content and Data Rights](CONTENT-LICENSE.md)
and [Third-Party Notices](THIRD_PARTY_NOTICES.md).
