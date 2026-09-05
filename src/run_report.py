"""Structured reporting for one native BMTNews pipeline run."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from ._file_utils import _atomic_write_text


DEFAULT_RUN_REPORT_PATH = Path("data/run-report.json")
AlertSeverity = Literal["info", "warning", "failure"]
RunKind = Literal[
    "legacy_full", "staging_fetch", "daily_publish", "weekly_review", "x_slot"
]

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[-_]?key|authorization|cookie|credential|password|secret|signature|token)"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
_HTTP_URL = re.compile(r"https?://[^\s<>'\"]+")

_LEGACY_METRIC_LABELS = (
    ("fetched_raw", "本次采集"),
    ("unique_after_url_dedup", "URL 去重后"),
    ("staged_total", "暂存累计"),
    ("edition_candidates", "本期候选"),
    ("current_day_items", "属于当日"),
    ("skipped_published_history", "跳过历史发布"),
    ("skipped_already_analyzed", "跳过已分析"),
    ("analyzed_this_run", "本次分析"),
    ("analyzed_today", "今日累计分析"),
    ("above_threshold", "分数达标"),
    ("topic_duplicates_removed", "主题去重删除"),
    ("balanced_digest_removed", "配额筛选删除"),
    ("newly_displayed", "本次新增展示"),
    ("displayed_today", "今日页面展示"),
    ("high_priority", "高优先级"),
)

_STAGING_METRIC_LABELS = (
    ("fetched_raw", "本次采集"),
    ("unique_after_url_dedup", "URL 去重后"),
    ("staged_added", "新增暂存"),
    ("staged_total", "暂存累计"),
)

_DAILY_METRIC_LABELS = (
    ("fetched_raw", "最终补采"),
    ("unique_after_url_dedup", "补采 URL 去重后"),
    ("staging_items_before", "出刊前暂存"),
    ("staging_only_candidates", "仅由日内暂存补回"),
    ("staged_total", "合并后暂存"),
    ("edition_candidates", "固定窗口候选"),
    ("fallback_candidates", "36 小时保底候选"),
    ("skipped_published_history", "跳过历史发布"),
    ("prefilter_evaluated", "批量粗筛评估"),
    ("prefilter_removed", "批量粗筛移除"),
    ("analyzed_this_run", "本次评估（含缓存）"),
    ("analysis_cache_misses", "新增 AI 分析"),
    ("analysis_cache_hits", "分析缓存命中"),
    ("enrichment_cache_hits", "补充缓存命中"),
    ("fallback_analyzed", "保底补充分析"),
    ("above_threshold", "分数达标"),
    ("below_threshold", "低于分数门槛"),
    ("topic_duplicates_removed", "主题去重删除"),
    ("qualified_after_topic_dedup", "去重后合格"),
    ("category_reclassified", "AI 内容分类调整"),
    ("category_limit_deferred", "分类限额暂缓"),
    ("source_limit_deferred", "来源限额暂缓"),
    ("balanced_digest_removed", "配额筛选删除"),
    ("quota_borrowed", "Crypto 软借用"),
    ("minimum_fill_added", "安全下限补入"),
    ("displayed_today", "本期最终展示"),
    ("high_priority", "高优先级"),
    ("telegram_messages_sent", "Telegram 推送"),
    ("telegram_message_chars", "Telegram 消息字符"),
    ("ai_total_tokens", "AI Token 总量"),
)

_REPORT_TITLES = {
    "legacy_full": "BMTNews 采集运行报告",
    "staging_fetch": "BMTNews 日内采集报告",
    "daily_publish": "BMTNews 早间日报发布报告",
}

_METRICS_BY_KIND = {
    "legacy_full": _LEGACY_METRIC_LABELS,
    "staging_fetch": _STAGING_METRIC_LABELS,
    "daily_publish": _DAILY_METRIC_LABELS,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_url(match: re.Match[str]) -> str:
    raw = match.group(0).rstrip(".,);]")
    suffix = match.group(0)[len(raw) :]
    try:
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        safe = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        return safe + suffix
    except ValueError:
        return "<redacted-url>" + suffix


def sanitize_diagnostic(value: object, limit: int = 500) -> str:
    """Remove common credentials and URL query data from public diagnostics."""
    text = str(value).replace("\r", " ").replace("\n", " ").strip()
    text = _HTTP_URL.sub(_sanitize_url, text)
    text = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        text,
    )
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _public_fetch_report(payload: dict[str, Any]) -> dict[str, Any]:
    report: dict[str, Any] = {
        key: payload[key]
        for key in (
            "status",
            "attempted",
            "successful",
            "empty",
            "failed",
            "item_count",
        )
        if key in payload
    }
    sources = []
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        public_source = {
            key: source[key]
            for key in ("source", "status", "item_count", "subsource_counts")
            if key in source
        }
        if source.get("error"):
            public_source["error"] = sanitize_diagnostic(source["error"])
        sources.append(public_source)
    report["sources"] = sources
    return report


@dataclass
class RunAlert:
    """One informational, warning, or failure signal for the run."""

    severity: AlertSeverity
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": sanitize_diagnostic(self.message),
        }


@dataclass
class RunReport:
    """Mutable report populated as the native pipeline advances."""

    run_id: str
    date: str
    timezone_name: str
    started_at: datetime
    kind: RunKind = "legacy_full"
    window_start: datetime | None = None
    window_end: datetime | None = None
    status: Literal["running", "success", "warning", "failure"] = "running"
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    metrics: dict[str, int] = field(default_factory=dict)
    ai_usage: list[dict[str, Any]] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    fetch_report: dict[str, Any] | None = None
    summaries: list[str] = field(default_factory=list)
    breakdowns: dict[str, dict[str, int]] = field(default_factory=dict)
    alerts: list[RunAlert] = field(default_factory=list)
    error: str | None = None

    @classmethod
    def start(
        cls,
        *,
        date: str,
        timezone_name: str,
        started_at: datetime | None = None,
        kind: RunKind = "legacy_full",
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> "RunReport":
        moment = started_at or _utc_now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        run_id = moment.astimezone(timezone.utc).strftime("run-%Y%m%dT%H%M%S.%fZ")
        return cls(
            run_id=run_id,
            date=date,
            timezone_name=timezone_name,
            started_at=moment,
            kind=kind,
            window_start=window_start,
            window_end=window_end,
        )

    def set_metric(self, name: str, value: int) -> None:
        self.metrics[name] = max(0, int(value))

    def set_timing(self, name: str, seconds: float) -> None:
        self.timings[name] = round(max(0.0, float(seconds)), 3)

    def add_timing(self, name: str, seconds: float) -> None:
        self.set_timing(name, self.timings.get(name, 0.0) + seconds)

    def set_breakdown(self, name: str, values: dict[str, int]) -> None:
        self.breakdowns[name] = {
            sanitize_diagnostic(key, limit=160): max(0, int(value))
            for key, value in values.items()
        }

    def attach_fetch_report(self, payload: dict[str, Any] | None) -> None:
        if payload is None:
            return
        self.fetch_report = _public_fetch_report(payload)
        if payload.get("status") == "partial_failure":
            failed = int(payload.get("failed", 0))
            attempted = int(payload.get("attempted", 0))
            self.add_alert(
                "warning",
                "partial_source_failure",
                f"采集存在部分失败（{failed}/{attempted} 个顶层来源完全失败）；详见来源诊断，已使用其余内容继续生成。",
            )

    def add_alert(
        self,
        severity: AlertSeverity,
        code: str,
        message: str,
    ) -> None:
        if any(alert.code == code for alert in self.alerts):
            return
        self.alerts.append(RunAlert(severity, code, message))

    def record_summary(self, language: str) -> None:
        if language not in self.summaries:
            self.summaries.append(language)

    def fail(self, error: object) -> None:
        self.error = sanitize_diagnostic(error)
        self.status = "failure"
        self.add_alert("failure", "pipeline_failed", self.error)

    def finish(self, finished_at: datetime | None = None) -> None:
        moment = finished_at or _utc_now()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        self.finished_at = moment
        self.duration_seconds = round(
            max(0.0, (moment - self.started_at).total_seconds()),
            3,
        )
        if self.status == "running":
            self.status = (
                "warning"
                if any(alert.severity == "warning" for alert in self.alerts)
                else "success"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 2,
            "run_id": self.run_id,
            "kind": self.kind,
            "date": self.date,
            "timezone": self.timezone_name,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at is not None else None
            ),
            "duration_seconds": self.duration_seconds,
            "window_start": (
                self.window_start.isoformat()
                if self.window_start is not None
                else None
            ),
            "window_end": (
                self.window_end.isoformat()
                if self.window_end is not None
                else None
            ),
            "metrics": dict(self.metrics),
            "ai_usage": list(self.ai_usage),
            "timings": dict(self.timings),
            "fetch_report": self.fetch_report,
            "summaries": list(self.summaries),
            "breakdowns": {
                name: dict(values)
                for name, values in self.breakdowns.items()
            },
            "alerts": [alert.to_dict() for alert in self.alerts],
            "error": self.error,
        }


def save_run_report(
    report: RunReport,
    path: Path = DEFAULT_RUN_REPORT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report.to_dict(), ensure_ascii=False, indent=2)
    _atomic_write_text(path, f"{payload}\n")
    return path


def load_run_report(path: Path = DEFAULT_RUN_REPORT_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _markdown_cell(value: object) -> str:
    return sanitize_diagnostic(value, limit=240).replace("|", "\\|")


def render_markdown_report(payload: dict[str, Any]) -> str:
    """Render a compact GitHub Actions job summary."""
    status = str(payload.get("status", "unknown"))
    kind = str(payload.get("kind") or "legacy_full")
    title = _REPORT_TITLES.get(kind, _REPORT_TITLES["legacy_full"])
    metric_labels = _METRICS_BY_KIND.get(kind, _LEGACY_METRIC_LABELS)
    icons = {
        "success": "✅",
        "warning": "⚠️",
        "failure": "❌",
        "running": "⏳",
    }
    lines = [
        f"## {title}",
        "",
        f"{icons.get(status, 'ℹ️')} **状态：{status}**",
        "",
        f"- 运行：`{_markdown_cell(payload.get('run_id', 'unknown'))}`",
        f"- 日期：{_markdown_cell(payload.get('date', '—'))} "
        f"({_markdown_cell(payload.get('timezone', '—'))})",
        f"- 耗时：{_markdown_cell(payload.get('duration_seconds', '—'))} 秒",
    ]
    metrics = payload.get("metrics") or {}
    if payload.get("window_start") and payload.get("window_end"):
        lines += [
            f"- 固定窗口：`{_markdown_cell(payload['window_start'])}` → "
            f"`{_markdown_cell(payload['window_end'])}`（结束时间不包含）",
        ]
    if "cutoff_lag_minutes" in metrics:
        lines.append(f"- 截止后启动：{int(metrics['cutoff_lag_minutes'])} 分钟")
    if "staging_age_minutes" in metrics:
        lines.append(f"- 日内暂存年龄：{int(metrics['staging_age_minutes'])} 分钟")

    present_metrics = [
        (key, label)
        for key, label in metric_labels
        if key in metrics
    ]
    if present_metrics:
        lines += [
            "",
            "### 处理漏斗",
            "",
            "| 阶段 | 数量 |",
            "| --- | ---: |",
        ]
        for key, label in present_metrics:
            lines.append(f"| {label} | {int(metrics[key])} |")

    timings = payload.get("timings") or {}
    if timings:
        lines += [
            "",
            "### 性能分段",
            "",
            "| 阶段 | 耗时（秒） |",
            "| --- | ---: |",
        ]
        for stage, seconds in timings.items():
            lines.append(
                f"| {_markdown_cell(stage)} | {float(seconds):.3f} |"
            )

    breakdowns = payload.get("breakdowns") or {}
    candidate_groups = breakdowns.get("candidate_groups") or {}
    fallback_groups = breakdowns.get("fallback_candidate_groups") or {}
    qualified_groups = breakdowns.get("qualified_groups") or {}
    selected_groups = breakdowns.get("selected_groups") or {}
    group_limits = breakdowns.get("group_limits") or {}
    if (
        candidate_groups
        or fallback_groups
        or qualified_groups
        or selected_groups
        or group_limits
    ):
        group_keys = list(
            dict.fromkeys(
                [
                    *group_limits,
                    *candidate_groups,
                    *fallback_groups,
                    *qualified_groups,
                    *selected_groups,
                ]
            )
        )
        lines += [
            "",
            "### 内容配额",
            "",
            "| 分组 | 固定窗口候选 | 保底候选 | 去重后合格 | 最终入选 | 上限 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for group in group_keys:
            limit = group_limits.get(group)
            lines.append(
                f"| {_markdown_cell(group)} | "
                f"{int(candidate_groups.get(group, 0))} | "
                f"{int(fallback_groups.get(group, 0))} | "
                f"{int(qualified_groups.get(group, 0))} | "
                f"{int(selected_groups.get(group, 0))} | "
                f"{int(limit) if limit is not None else '不限'} |"
            )
        if "primary_selected" in metrics and "primary_required" in metrics:
            lines += [
                "",
                f"Crypto 主轨：**{int(metrics['primary_selected'])} / "
                f"{int(metrics['primary_required'])}**（最低目标）",
            ]

    candidate_sources = breakdowns.get("candidate_sources") or {}
    fallback_sources = breakdowns.get("fallback_candidate_sources") or {}
    qualified_sources = breakdowns.get("qualified_sources") or {}
    selected_sources = breakdowns.get("selected_sources") or {}
    if (
        candidate_sources
        or fallback_sources
        or qualified_sources
        or selected_sources
    ):
        source_keys = list(
            dict.fromkeys(
                [
                    *candidate_sources,
                    *fallback_sources,
                    *qualified_sources,
                    *selected_sources,
                ]
            )
        )
        lines += [
            "",
            "### 来源贡献",
            "",
            "| 细分来源 | 固定窗口候选 | 保底候选 | 去重后合格 | 最终入选 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for source in source_keys:
            lines.append(
                f"| {_markdown_cell(source)} | "
                f"{int(candidate_sources.get(source, 0))} | "
                f"{int(fallback_sources.get(source, 0))} | "
                f"{int(qualified_sources.get(source, 0))} | "
                f"{int(selected_sources.get(source, 0))} |"
            )

    fetch_report = payload.get("fetch_report") or {}
    sources = fetch_report.get("sources") or []
    if sources:
        lines += [
            "",
            "### 来源状态",
            "",
            "| 来源 | 状态 | 条数 | 诊断 |",
            "| --- | --- | ---: | --- |",
        ]
        for source in sources:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _markdown_cell(source.get("source", "unknown")),
                        _markdown_cell(source.get("status", "unknown")),
                        str(int(source.get("item_count", 0))),
                        _markdown_cell(source.get("error", "")) or "—",
                    ]
                )
                + " |"
            )
            for subsource, count in (
                source.get("subsource_counts") or {}
            ).items():
                lines.append(
                    f"| ↳ {_markdown_cell(subsource)} | — | "
                    f"{int(count)} | — |"
                )

    if payload.get("ai_usage"):
        lines += ["", "### AI 分阶段用量", "",
                  "| 模型 / 阶段 | 调用 | 输入 | 输出 | 输入缓存 | 截断 |",
                  "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for row in payload["ai_usage"]:
            label = _markdown_cell(f'{row.get("model", "")} / {row.get("stage", "")}')
            values = [int(row.get(key, 0)) for key in
                      ("calls", "input_tokens", "output_tokens", "cached_input_tokens", "truncated_calls")]
            lines.append("| " + label + " | " + " | ".join(map(str, values)) + " |")

    alerts = payload.get("alerts") or []
    if alerts:
        lines += ["", "### 提示与预警", ""]
        alert_icons = {"info": "ℹ️", "warning": "⚠️", "failure": "❌"}
        for alert in alerts:
            severity = str(alert.get("severity", "info"))
            lines.append(
                f"- {alert_icons.get(severity, 'ℹ️')} "
                f"`{_markdown_cell(alert.get('code', 'unknown'))}` "
                f"{_markdown_cell(alert.get('message', ''))}"
            )

    return "\n".join(lines).rstrip() + "\n"


def render_github_annotations(payload: dict[str, Any]) -> list[str]:
    """Return workflow commands for report warnings and failures."""
    annotations = []
    for alert in payload.get("alerts") or []:
        severity = str(alert.get("severity", "info"))
        if severity not in {"warning", "failure"}:
            continue
        command = "warning" if severity == "warning" else "error"
        title = sanitize_diagnostic(alert.get("code", "pipeline_alert"), limit=80)
        message = sanitize_diagnostic(alert.get("message", ""), limit=500)
        title = title.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        message = message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        annotations.append(f"::{command} title=BMTNews {title}::{message}")
    return annotations


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a BMTNews run report")
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_RUN_REPORT_PATH,
        help="Run report JSON path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Markdown file to append to; defaults to GITHUB_STEP_SUMMARY or stdout",
    )
    args = parser.parse_args()

    output_path = args.output
    if output_path is None and os.getenv("GITHUB_STEP_SUMMARY"):
        output_path = Path(os.environ["GITHUB_STEP_SUMMARY"])

    payload = None
    if args.input.exists():
        payload = load_run_report(args.input)
        markdown = render_markdown_report(payload)
    else:
        missing_title = _REPORT_TITLES["legacy_full"]
        markdown = (
            f"## {missing_title}\n\n"
            "⚠️ 本次任务没有生成结构化运行报告，请检查初始化或依赖安装步骤。\n"
        )

    if payload is not None and os.getenv("GITHUB_ACTIONS") == "true":
        for annotation in render_github_annotations(payload):
            print(annotation)

    if output_path is None:
        print(markdown, end="")
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8") as output_file:
            output_file.write(markdown)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
