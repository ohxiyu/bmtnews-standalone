# BMTNews MCP

BMTNews includes a built-in MCP server that exposes the native BMTNews pipeline as staged tools and read-only resources.

The MCP layer does not reimplement BMTNews business logic. It reuses the existing fetch, score, filter, enrich, and summarize modules from the main codebase.

## Tools

| Tool | Description |
| --- | --- |
| `bmt_validate_config` | Validate BMTNews config and required environment variables |
| `bmt_fetch_items` | Fetch and deduplicate content into the `raw` stage |
| `bmt_score_items` | Score items from a stage into `scored` |
| `bmt_filter_items` | Filter scored items into `filtered` |
| `bmt_enrich_items` | Enrich filtered items into `enriched` |
| `bmt_generate_summary` | Generate markdown from a stage |
| `bmt_run_pipeline` | Run fetch -> score -> filter -> enrich -> summarize |
| `bmt_list_runs` | List recent run artifacts |
| `bmt_get_run_meta` | Read metadata for a run |
| `bmt_get_run_stage` | Read items from a run stage |
| `bmt_get_run_summary` | Read a generated summary |
| `bmt_get_metrics` | Read in-memory server metrics |

## Resources

- `bmtnews://server/info`
- `bmtnews://metrics`
- `bmtnews://runs`
- `bmtnews://runs/{run_id}/meta`
- `bmtnews://runs/{run_id}/items/{stage}`
- `bmtnews://runs/{run_id}/summary/{language}`
- `bmtnews://config/effective`

## Install and Start

```bash
uv sync
uv run bmtnews-mcp
```

The server runs over stdio and is intended to be launched by an MCP client.

## Run Artifacts

Each run writes artifacts under `data/mcp-runs/<run_id>/`:

- `meta.json`
- `raw_items.json`
- `scored_items.json`
- `filtered_items.json`
- `enriched_items.json`
- `summary-<lang>.md`

## Design Principles

1. Keep BMTNews as the single source of business logic.
2. Preserve staged re-entry so a run can continue from intermediate artifacts.
3. Default to no extra side effects unless explicitly requested.

## Client Setup

See [integration.md](integration.md).
