"""MCP server entrypoint for BMTNews."""

from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import FastMCP

from . import archive_tools
from .errors import BMTNewsMcpError
from .service import BMTNewsPipelineService


mcp = FastMCP(name="bmtnews-mcp")
service = BMTNewsPipelineService()

SERVER_STARTED_AT = datetime.now(timezone.utc).isoformat()
METRICS: dict[str, Any] = {
    "started_at": SERVER_STARTED_AT,
    "tool_calls_total": 0,
    "tool_calls_success": 0,
    "tool_calls_failed": 0,
    "tool_calls_by_name": {},
    "tool_errors_by_code": {},
    "tool_last_duration_ms": {},
    "last_error": None,
}


def _ok(tool: str, data: dict[str, Any], duration_ms: float | None = None) -> dict[str, Any]:
    payload = {
        "ok": True,
        "tool": tool,
        "data": data,
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    if duration_ms is not None:
        payload["meta"]["duration_ms"] = round(duration_ms, 2)
    return payload


def _err(tool: str, error: Exception, duration_ms: float | None = None) -> dict[str, Any]:
    if isinstance(error, BMTNewsMcpError):
        code = error.code
        message = error.message
        details = error.details
    else:
        code = "BMT_INTERNAL_ERROR"
        message = str(error)
        details = None

    payload = {
        "ok": False,
        "tool": tool,
        "error": {
            "code": code,
            "message": message,
            "details": details,
        },
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
    if duration_ms is not None:
        payload["meta"]["duration_ms"] = round(duration_ms, 2)
    return payload


def _record_metrics(tool: str, ok: bool, duration_ms: float, error_code: str | None = None) -> None:
    METRICS["tool_calls_total"] += 1
    if ok:
        METRICS["tool_calls_success"] += 1
    else:
        METRICS["tool_calls_failed"] += 1

    by_name = METRICS["tool_calls_by_name"]
    by_name[tool] = by_name.get(tool, 0) + 1

    METRICS["tool_last_duration_ms"][tool] = round(duration_ms, 2)

    if error_code:
        by_code = METRICS["tool_errors_by_code"]
        by_code[error_code] = by_code.get(error_code, 0) + 1
        METRICS["last_error"] = {
            "tool": tool,
            "code": error_code,
            "at": datetime.now(timezone.utc).isoformat(),
        }


async def _run_tool(tool: str, runner: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    started = perf_counter()
    try:
        data = await runner()
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics(tool, ok=True, duration_ms=elapsed_ms)
        return _ok(tool, data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err(tool, exc, duration_ms=elapsed_ms)
        code = payload["error"]["code"]
        _record_metrics(tool, ok=False, duration_ms=elapsed_ms, error_code=code)
        return payload


def _resource_result(resource: str, loader: Callable[[], Any]) -> dict[str, Any]:
    try:
        data = loader()
        return {
            "ok": True,
            "resource": resource,
            "data": data,
        }
    except Exception as exc:
        return _err(resource, exc)


def _metrics_snapshot() -> dict[str, Any]:
    uptime_seconds = (
        datetime.now(timezone.utc) - datetime.fromisoformat(METRICS["started_at"])
    ).total_seconds()
    return {
        **METRICS,
        "uptime_seconds": round(uptime_seconds, 2),
    }


@mcp.tool()
async def bmt_validate_config(
    project_path: str | None = None,
    config_path: str | None = None,
    sources: list[str] | None = None,
    check_env: bool = True,
) -> dict[str, Any]:
    """Validate BMTNews config and required environment variables."""

    return await _run_tool(
        "bmt_validate_config",
        lambda: service.validate_config(
            project_path=project_path,
            config_path=config_path,
            sources=sources,
            check_env=check_env,
        ),
    )


@mcp.tool()
async def bmt_fetch_items(
    hours: int = 24,
    run_id: str | None = None,
    project_path: str | None = None,
    config_path: str | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    """Fetch and deduplicate content into the raw stage."""

    return await _run_tool(
        "bmt_fetch_items",
        lambda: service.fetch_items(
            hours=hours,
            run_id=run_id,
            project_path=project_path,
            config_path=config_path,
            sources=sources,
        ),
    )


@mcp.tool()
async def bmt_score_items(
    run_id: str,
    source_stage: str = "raw",
    project_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Score a stage into the scored stage."""

    return await _run_tool(
        "bmt_score_items",
        lambda: service.score_items(
            run_id=run_id,
            source_stage=source_stage,
            project_path=project_path,
            config_path=config_path,
        ),
    )


@mcp.tool()
async def bmt_filter_items(
    run_id: str,
    threshold: float | None = None,
    source_stage: str = "scored",
    topic_dedup: bool = True,
    project_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Filter scored items into the filtered stage."""

    return await _run_tool(
        "bmt_filter_items",
        lambda: service.filter_items(
            run_id=run_id,
            threshold=threshold,
            source_stage=source_stage,
            topic_dedup=topic_dedup,
            project_path=project_path,
            config_path=config_path,
        ),
    )


@mcp.tool()
async def bmt_enrich_items(
    run_id: str,
    source_stage: str = "filtered",
    project_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Enrich filtered items into the enriched stage."""

    return await _run_tool(
        "bmt_enrich_items",
        lambda: service.enrich_items(
            run_id=run_id,
            source_stage=source_stage,
            project_path=project_path,
            config_path=config_path,
        ),
    )


@mcp.tool()
async def bmt_generate_summary(
    run_id: str,
    language: str = "zh",
    source_stage: str | None = None,
    project_path: str | None = None,
    config_path: str | None = None,
    save_to_project_data: bool = False,
) -> dict[str, Any]:
    """Generate a markdown summary from a stage."""

    return await _run_tool(
        "bmt_generate_summary",
        lambda: service.generate_summary(
            run_id=run_id,
            language=language,
            source_stage=source_stage,
            project_path=project_path,
            config_path=config_path,
            save_to_project_data=save_to_project_data,
        ),
    )


@mcp.tool()
async def bmt_run_pipeline(
    hours: int = 24,
    languages: list[str] | None = None,
    threshold: float | None = None,
    project_path: str | None = None,
    config_path: str | None = None,
    sources: list[str] | None = None,
    enrich: bool = True,
    topic_dedup: bool = True,
    save_to_project_data: bool = False,
) -> dict[str, Any]:
    """Run fetch -> score -> filter -> enrich -> summarize in one call."""

    return await _run_tool(
        "bmt_run_pipeline",
        lambda: service.run_pipeline(
            hours=hours,
            languages=languages,
            threshold=threshold,
            project_path=project_path,
            config_path=config_path,
            sources=sources,
            enrich=enrich,
            topic_dedup=topic_dedup,
            save_to_project_data=save_to_project_data,
        ),
    )


@mcp.tool()
def bmt_list_runs(limit: int = 20) -> dict[str, Any]:
    """List recent runs and stage states."""

    started = perf_counter()
    try:
        data = service.list_runs(limit=limit)
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics("bmt_list_runs", ok=True, duration_ms=elapsed_ms)
        return _ok("bmt_list_runs", data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err("bmt_list_runs", exc, duration_ms=elapsed_ms)
        _record_metrics(
            "bmt_list_runs",
            ok=False,
            duration_ms=elapsed_ms,
            error_code=payload["error"]["code"],
        )
        return payload


@mcp.tool()
def bmt_get_run_meta(run_id: str) -> dict[str, Any]:
    """Read run metadata."""

    started = perf_counter()
    try:
        data = service.get_run_meta(run_id)
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics("bmt_get_run_meta", ok=True, duration_ms=elapsed_ms)
        return _ok("bmt_get_run_meta", data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err("bmt_get_run_meta", exc, duration_ms=elapsed_ms)
        _record_metrics(
            "bmt_get_run_meta",
            ok=False,
            duration_ms=elapsed_ms,
            error_code=payload["error"]["code"],
        )
        return payload


@mcp.tool()
def bmt_get_run_stage(run_id: str, stage: str, max_items: int = 200) -> dict[str, Any]:
    """Read items from a run stage."""

    started = perf_counter()
    try:
        data = service.get_run_stage(run_id=run_id, stage=stage, max_items=max_items)
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics("bmt_get_run_stage", ok=True, duration_ms=elapsed_ms)
        return _ok("bmt_get_run_stage", data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err("bmt_get_run_stage", exc, duration_ms=elapsed_ms)
        _record_metrics(
            "bmt_get_run_stage",
            ok=False,
            duration_ms=elapsed_ms,
            error_code=payload["error"]["code"],
        )
        return payload


@mcp.tool()
def bmt_get_run_summary(run_id: str, language: str = "zh") -> dict[str, Any]:
    """Read a generated run summary."""

    started = perf_counter()
    try:
        data = service.get_run_summary(run_id=run_id, language=language)
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics("bmt_get_run_summary", ok=True, duration_ms=elapsed_ms)
        return _ok("bmt_get_run_summary", data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err("bmt_get_run_summary", exc, duration_ms=elapsed_ms)
        _record_metrics(
            "bmt_get_run_summary",
            ok=False,
            duration_ms=elapsed_ms,
            error_code=payload["error"]["code"],
        )
        return payload


def _archive_tool(tool: str, runner: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    """Run one read-only archive query with the shared metrics wrapper."""
    started = perf_counter()
    try:
        data = runner()
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics(tool, ok=True, duration_ms=elapsed_ms)
        return _ok(tool, data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err(tool, exc, duration_ms=elapsed_ms)
        _record_metrics(
            tool,
            ok=False,
            duration_ms=elapsed_ms,
            error_code=payload["error"]["code"],
        )
        return payload


@mcp.tool()
def bmt_search_archive(
    query: str = "",
    since: str | None = None,
    until: str | None = None,
    category: str | None = None,
    min_score: float | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search published editions by text, date range, category, or score."""

    return _archive_tool(
        "bmt_search_archive",
        lambda: archive_tools.search_archive(
            query,
            since=since,
            until=until,
            category=category,
            min_score=min_score,
            limit=limit,
        ),
    )


@mcp.tool()
def bmt_get_thread(thread_id: str) -> dict[str, Any]:
    """Read the full cross-day timeline of one story thread."""

    return _archive_tool(
        "bmt_get_thread",
        lambda: archive_tools.get_thread(thread_id),
    )


@mcp.tool()
def bmt_list_threads(days: int = 30, limit: int = 20) -> dict[str, Any]:
    """List recent multi-day story threads."""

    return _archive_tool(
        "bmt_list_threads",
        lambda: archive_tools.list_threads(days=days, limit=limit),
    )


@mcp.tool()
def bmt_get_entity(name: str, limit: int = 30) -> dict[str, Any]:
    """Read archived coverage for one entity (company, protocol, regulator)."""

    return _archive_tool(
        "bmt_get_entity",
        lambda: archive_tools.get_entity(name, limit=limit),
    )


@mcp.tool()
def bmt_list_entities(days: int = 60, limit: int = 40) -> dict[str, Any]:
    """List recurring entities in the recent archive."""

    return _archive_tool(
        "bmt_list_entities",
        lambda: archive_tools.list_entities(days=days, limit=limit),
    )


@mcp.tool()
def bmt_get_metrics() -> dict[str, Any]:
    """Read in-memory server metrics."""

    started = perf_counter()
    try:
        data = _metrics_snapshot()
        elapsed_ms = (perf_counter() - started) * 1000
        _record_metrics("bmt_get_metrics", ok=True, duration_ms=elapsed_ms)
        return _ok("bmt_get_metrics", data, duration_ms=elapsed_ms)
    except Exception as exc:
        elapsed_ms = (perf_counter() - started) * 1000
        payload = _err("bmt_get_metrics", exc, duration_ms=elapsed_ms)
        _record_metrics(
            "bmt_get_metrics",
            ok=False,
            duration_ms=elapsed_ms,
            error_code=payload["error"]["code"],
        )
        return payload


@mcp.tool()
async def bmt_send_webhook(
    date: str,
    language: str = "zh",
    important_items: int = 0,
    all_items: int = 0,
    result: str = "success",
    summary: str = "",
    project_path: str | None = None,
    config_path: str | None = None,
) -> dict[str, Any]:
    """Send a webhook notification with the given variables.

    Uses the webhook URL (from environment variable), request_body template,
    and headers from the BMTNews config. Template variables #{date}, #{language},
    #{important_items}, #{all_items}, #{result}, #{timestamp},
    #{summary} are replaced in the URL and request_body before sending.
    """

    return await _run_tool(
        "bmt_send_webhook",
        lambda: service.send_webhook(
            date=date,
            language=language,
            important_items=important_items,
            all_items=all_items,
            result=result,
            summary=summary,
            project_path=project_path,
            config_path=config_path,
        ),
    )


@mcp.resource("bmtnews://server/info")
def r_server_info() -> dict[str, Any]:
    """Server metadata resource."""

    return {
        "name": "bmtnews-mcp",
        "started_at": SERVER_STARTED_AT,
        "runs_root": str(service.runs_root.resolve()),
    }


@mcp.resource("bmtnews://metrics")
def r_metrics() -> dict[str, Any]:
    """In-memory metrics snapshot."""

    return _resource_result("bmtnews://metrics", _metrics_snapshot)


@mcp.resource("bmtnews://runs")
def r_runs() -> dict[str, Any]:
    """Recent run list."""

    return _resource_result("bmtnews://runs", lambda: service.list_runs(limit=30))


@mcp.resource("bmtnews://runs/{run_id}/meta")
def r_run_meta(run_id: str) -> dict[str, Any]:
    """Run metadata resource."""

    return _resource_result(
        f"bmtnews://runs/{run_id}/meta",
        lambda: service.get_run_meta(run_id),
    )


@mcp.resource("bmtnews://runs/{run_id}/items/{stage}")
def r_run_items(run_id: str, stage: str) -> dict[str, Any]:
    """Run stage items resource."""

    return _resource_result(
        f"bmtnews://runs/{run_id}/items/{stage}",
        lambda: service.get_run_stage(run_id=run_id, stage=stage, max_items=200),
    )


@mcp.resource("bmtnews://runs/{run_id}/summary/{language}")
def r_run_summary(run_id: str, language: str) -> dict[str, Any]:
    """Run summary resource."""

    return _resource_result(
        f"bmtnews://runs/{run_id}/summary/{language}",
        lambda: service.get_run_summary(run_id=run_id, language=language),
    )


@mcp.resource("bmtnews://config/effective")
def r_effective_config() -> dict[str, Any]:
    """Effective default config resolved from local BMTNews path."""

    return _resource_result("bmtnews://config/effective", service.get_effective_config)


def main() -> None:
    """Run MCP server over stdio."""

    mcp.run()


if __name__ == "__main__":
    main()
