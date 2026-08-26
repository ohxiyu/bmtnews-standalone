from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.models import (
    AIConfig,
    Config,
    ContentItem,
    FilteringConfig,
    SourceType,
    SourcesConfig,
)
from src.orchestrator import BMTNewsOrchestrator
from src.run_report import (
    RunReport,
    load_run_report,
    render_github_annotations,
    render_markdown_report,
    sanitize_diagnostic,
    save_run_report,
)
from src.storage.manager import StorageManager


STARTED_AT = datetime(2026, 7, 27, 1, 2, 3, tzinfo=timezone.utc)


def test_partial_fetch_failure_produces_warning_report(tmp_path: Path) -> None:
    report = RunReport.start(
        date="2026-07-27",
        timezone_name="Asia/Shanghai",
        started_at=STARTED_AT,
    )
    report.set_metric("fetched_raw", 12)
    report.set_metric("displayed_today", 3)
    report.attach_fetch_report(
        {
            "status": "partial_failure",
            "attempted": 2,
            "successful": 1,
            "empty": 0,
            "failed": 1,
            "item_count": 12,
            "sources": [
                {
                    "source": "RSS Feeds",
                    "status": "success",
                    "item_count": 12,
                    "subsource_counts": {"Example": 12},
                },
                {
                    "source": "GitHub",
                    "status": "failure",
                    "item_count": 0,
                    "error": (
                        "RuntimeError: GET https://api.example.test/items"
                        "?token=secret failed; api_key=also-secret"
                    ),
                },
            ],
        }
    )
    report.finish(STARTED_AT + timedelta(seconds=12.3456))

    path = save_run_report(report, tmp_path / "run-report.json")
    payload = load_run_report(path)

    assert payload["status"] == "warning"
    assert payload["duration_seconds"] == 12.346
    assert payload["metrics"]["fetched_raw"] == 12
    assert payload["alerts"][0]["code"] == "partial_source_failure"
    diagnostic = payload["fetch_report"]["sources"][1]["error"]
    assert "token=secret" not in diagnostic
    assert "also-secret" not in diagnostic
    assert "https://api.example.test/items" in diagnostic


def test_failed_report_preserves_safe_error_and_renders_markdown() -> None:
    report = RunReport.start(
        date="2026-07-27",
        timezone_name="Asia/Shanghai",
        started_at=STARTED_AT,
    )
    report.set_metric("fetched_raw", 0)
    report.fail("Authorization token=super-secret failed")
    report.finish(STARTED_AT + timedelta(seconds=2))

    payload = report.to_dict()
    markdown = render_markdown_report(payload)

    assert payload["status"] == "failure"
    assert "super-secret" not in payload["error"]
    assert "## BMTNews 采集运行报告" in markdown
    assert "| 本次采集 | 0 |" in markdown
    assert "`pipeline_failed`" in markdown
    assert render_github_annotations(payload) == [
        "::error title=BMTNews pipeline_failed::Authorization token=<redacted> failed"
    ]


def test_daily_report_renders_window_quotas_and_source_contribution() -> None:
    report = RunReport.start(
        date="2026-07-29",
        timezone_name="Asia/Shanghai",
        started_at=STARTED_AT,
        kind="daily_publish",
        window_start=datetime(
            2026, 7, 28, 12, 0, tzinfo=timezone.utc
        ),
        window_end=datetime(
            2026, 7, 29, 12, 0, tzinfo=timezone.utc
        ),
    )
    report.set_metric("fetched_raw", 19)
    report.set_metric("edition_candidates", 51)
    report.set_metric("displayed_today", 7)
    report.set_metric("primary_selected", 4)
    report.set_metric("primary_required", 9)
    report.set_timing("fetch", 1.2344)
    report.add_timing("analysis", 2.0)
    report.add_timing("analysis", 0.3456)
    report.set_breakdown(
        "selected_groups",
        {"Crypto Markets": 4, "Technology": 3},
    )
    report.set_breakdown(
        "candidate_groups",
        {"Crypto Markets": 12, "Technology": 4},
    )
    report.set_breakdown(
        "fallback_candidate_groups",
        {"Crypto Markets": 3},
    )
    report.set_breakdown(
        "qualified_groups",
        {"Crypto Markets": 6, "Technology": 3},
    )
    report.set_breakdown(
        "group_limits",
        {"Crypto Markets": 4, "Technology": 3},
    )
    report.set_breakdown(
        "candidate_sources",
        {"rss/CoinDesk": 12},
    )
    report.set_breakdown(
        "selected_sources",
        {"rss/CoinDesk": 2},
    )
    report.set_breakdown(
        "qualified_sources",
        {"rss/CoinDesk": 5},
    )
    report.set_breakdown(
        "fallback_candidate_sources",
        {"rss/CoinDesk": 3},
    )
    report.add_alert(
        "warning",
        "primary_quota_shortfall",
        "Crypto 主轨只有 4/9 条合格内容。",
    )
    report.finish(STARTED_AT + timedelta(seconds=10))

    payload = report.to_dict()
    markdown = render_markdown_report(payload)

    assert payload["version"] == 2
    assert payload["kind"] == "daily_publish"
    assert payload["timings"] == {"fetch": 1.234, "analysis": 2.346}
    assert "## BMTNews 早间日报发布报告" in markdown
    assert "### 性能分段" in markdown
    assert "| analysis | 2.346 |" in markdown
    assert "| 固定窗口候选 | 51 |" in markdown
    assert "| Crypto Markets | 12 | 3 | 6 | 4 | 4 |" in markdown
    assert "Crypto 主轨：**4 / 9**" in markdown
    assert "| rss/CoinDesk | 12 | 3 | 5 | 2 |" in markdown
    assert "| URL 去重后 | 0 |" not in markdown


def test_sanitize_diagnostic_removes_url_credentials_and_query() -> None:
    sanitized = sanitize_diagnostic(
        "GET https://user:pass@example.test/private?signature=secret#fragment failed"
    )

    assert sanitized == "GET https://example.test/private failed"


def test_native_pipeline_writes_funnel_and_frontend_stats(
    tmp_path: Path,
    monkeypatch,
) -> None:
    now = datetime.now(timezone.utc)
    items = [
        ContentItem(
            id="high",
            source_type=SourceType.RSS,
            title="High priority",
            url="https://example.test/high",
            content="content",
            author="publisher",
            published_at=now,
            ai_score=9.0,
        ),
        ContentItem(
            id="second",
            source_type=SourceType.RSS,
            title="Second",
            url="https://example.test/second",
            content="content",
            author="publisher",
            published_at=now,
            ai_score=8.0,
        ),
    ]
    config = Config(
        ai=AIConfig(
            provider="openai",
            model="test",
            api_key_env="TEST_API_KEY",
            languages=["zh"],
        ),
        sources=SourcesConfig(),
        filtering=FilteringConfig(
            ai_score_threshold=7.0,
            max_items=1,
        ),
    )
    storage = StorageManager(data_dir=str(tmp_path / "data"))
    orchestrator = BMTNewsOrchestrator(config, storage)

    async def fetch_all_sources(since):  # type: ignore[no-untyped-def]
        return items

    async def analyze_content(input_items):  # type: ignore[no-untyped-def]
        return input_items

    async def merge_topic_duplicates(input_items, *, log=True):  # type: ignore[no-untyped-def]
        return input_items

    async def no_op(input_items):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", analyze_content)
    monkeypatch.setattr(
        orchestrator,
        "merge_topic_duplicates",
        merge_topic_duplicates,
    )
    monkeypatch.setattr(orchestrator, "_expand_twitter_discussion", no_op)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", no_op)
    monkeypatch.chdir(tmp_path)

    asyncio.run(orchestrator.run(force_hours=24))

    payload = load_run_report(tmp_path / "data" / "run-report.json")
    assert payload["metrics"] == {
        "fetched_raw": 2,
        "unique_after_url_dedup": 2,
        "current_day_items": 2,
        "analyzed_this_run": 2,
        "above_threshold": 2,
        "topic_duplicates_removed": 0,
        "balanced_digest_removed": 1,
        "analyzed_today": 2,
        "newly_displayed": 1,
        "displayed_today": 1,
        "high_priority": 1,
    }
    assert payload["summaries"] == ["zh"]

    date = now.strftime("%Y-%m-%d")
    post = (tmp_path / "docs" / "_posts" / f"{date}-summary-zh.md").read_text(
        encoding="utf-8"
    )
    assert 'data-fetched="2"' in post
    assert 'data-analyzed="2"' in post
    assert 'data-selected="1"' in post
    assert 'data-critical="1"' in post
    assert (
        'class="daily-feed-layout is-editorial-grid feed-rendered-static"'
        in post
    )
    assert (
        tmp_path / "docs" / "editions" / date / "zh.html"
    ).exists()
