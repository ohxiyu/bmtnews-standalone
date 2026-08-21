#!/usr/bin/env python3
"""Local smoke check for BMTNews MCP integration."""

from __future__ import annotations

import asyncio
import json

from src.mcp.pipeline_adapter import resolve_project_path
from src.mcp.server import bmt_get_metrics
from src.mcp.service import BMTNewsPipelineService


async def _main() -> None:
    project_path = resolve_project_path()
    service = BMTNewsPipelineService()
    validation = await service.validate_config(
        project_path=str(project_path),
        check_env=False,
    )
    metrics = bmt_get_metrics()

    payload = {
        "ok": True,
        "project_path": str(project_path),
        "config_path": validation["config_path"],
        "enabled_sources": validation["enabled_sources"],
        "languages": validation["ai"]["languages"],
        "metrics_ok": metrics["ok"],
        "metrics_tool": metrics["tool"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
