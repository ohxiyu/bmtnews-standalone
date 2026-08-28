"""Detect a missing daily edition and dispatch one recovery run."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


DEFAULT_WORKFLOW = "daily-summary.yml"
DEFAULT_REF = "main"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_CUTOFF_HOUR = 8
DEFAULT_GRACE_MINUTES = 47
ACTIVE_STATUSES = frozenset(
    {"queued", "in_progress", "waiting", "pending", "requested"}
)
DecisionState = Literal["healthy", "missing", "missing_with_active_run"]


class GitHubApiError(RuntimeError):
    """A safe-to-publish GitHub API failure."""


@dataclass(frozen=True)
class WatchdogDecision:
    """Health decision for the latest edition whose grace period has elapsed."""

    state: DecisionState
    edition_cutoff: datetime
    due_at: datetime
    latest_success_at: datetime | None
    latest_success_url: str | None
    active_run_url: str | None

    @property
    def should_dispatch(self) -> bool:
        return self.state == "missing"

    def age(self, now: datetime) -> timedelta | None:
        if self.latest_success_at is None:
            return None
        return max(timedelta(0), now - self.latest_success_at)


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("workflow run is missing a timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _run_timestamp(run: dict[str, Any]) -> datetime:
    for field in ("updated_at", "run_started_at", "created_at"):
        if run.get(field):
            return _parse_timestamp(run[field])
    raise ValueError("workflow run is missing all known timestamps")


def _run_started_timestamp(run: dict[str, Any]) -> datetime:
    for field in ("run_started_at", "created_at", "updated_at"):
        if run.get(field):
            return _parse_timestamp(run[field])
    raise ValueError("workflow run is missing all known timestamps")


def _required_edition(
    now: datetime,
    *,
    timezone_name: str,
    cutoff_hour: int,
    grace_minutes: int,
) -> tuple[datetime, datetime]:
    if not 0 <= cutoff_hour <= 23:
        raise ValueError("cutoff-hour must be between 0 and 23")
    if grace_minutes < 0:
        raise ValueError("grace-minutes cannot be negative")

    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    cutoff = local_now.replace(
        hour=cutoff_hour,
        minute=0,
        second=0,
        microsecond=0,
    )
    due_at = cutoff + timedelta(minutes=grace_minutes)
    if local_now < due_at:
        cutoff -= timedelta(days=1)
        due_at -= timedelta(days=1)
    return cutoff, due_at


def evaluate_workflow_runs(
    workflow_runs: Sequence[dict[str, Any]],
    *,
    now: datetime,
    ref: str,
    timezone_name: str = DEFAULT_TIMEZONE,
    cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
    grace_minutes: int = DEFAULT_GRACE_MINUTES,
) -> WatchdogDecision:
    """Require a successful publication after the latest due cutoff."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    edition_cutoff, due_at = _required_edition(
        now,
        timezone_name=timezone_name,
        cutoff_hour=cutoff_hour,
        grace_minutes=grace_minutes,
    )
    cutoff_utc = edition_cutoff.astimezone(timezone.utc)

    branch_runs = [run for run in workflow_runs if run.get("head_branch") == ref]
    successful_runs = [
        run
        for run in branch_runs
        if run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and _run_started_timestamp(run) >= cutoff_utc
    ]
    active_runs = [
        run
        for run in branch_runs
        if run.get("status") in ACTIVE_STATUSES
        and _run_started_timestamp(run) >= cutoff_utc
    ]

    latest_success = (
        max(successful_runs, key=_run_timestamp) if successful_runs else None
    )
    latest_success_at = (
        _run_timestamp(latest_success) if latest_success is not None else None
    )
    latest_success_url = (
        str(latest_success.get("html_url") or "") or None
        if latest_success is not None
        else None
    )

    latest_active = max(active_runs, key=_run_timestamp) if active_runs else None
    active_run_url = (
        str(latest_active.get("html_url") or "") or None
        if latest_active is not None
        else None
    )

    if latest_success is not None:
        state: DecisionState = "healthy"
    elif latest_active is not None:
        state = "missing_with_active_run"
    else:
        state = "missing"

    return WatchdogDecision(
        state=state,
        edition_cutoff=edition_cutoff,
        due_at=due_at,
        latest_success_at=latest_success_at,
        latest_success_url=latest_success_url,
        active_run_url=active_run_url,
    )


def _validate_repository(repository: str) -> str:
    parts = repository.split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError("repository must use the owner/name format")
    return repository


def _github_api_request(
    method: str,
    path: str,
    *,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        f"https://api.github.com{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "bmtnews-schedule-watchdog",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            body = response.read()
    except HTTPError as error:
        raise GitHubApiError(
            f"GitHub API {method} request failed with HTTP {error.code}"
        ) from None
    except URLError:
        raise GitHubApiError(
            f"GitHub API {method} request could not connect"
        ) from None

    if not body:
        return None
    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        raise GitHubApiError("GitHub API returned invalid JSON") from None
    if not isinstance(result, dict):
        raise GitHubApiError("GitHub API returned an unexpected response")
    return result


def fetch_workflow_runs(
    *,
    token: str,
    repository: str,
    workflow: str,
) -> list[dict[str, Any]]:
    repository = _validate_repository(repository)
    workflow_id = quote(workflow, safe="")
    payload = _github_api_request(
        "GET",
        f"/repos/{repository}/actions/workflows/{workflow_id}/runs?per_page=30",
        token=token,
    )
    runs = payload.get("workflow_runs") if payload is not None else None
    if not isinstance(runs, list) or not all(
        isinstance(run, dict) for run in runs
    ):
        raise GitHubApiError("GitHub API response is missing workflow_runs")
    return runs


def dispatch_workflow(
    *,
    token: str,
    repository: str,
    workflow: str,
    ref: str,
    edition_date: str,
    trigger_source: str = "github-watchdog",
) -> None:
    repository = _validate_repository(repository)
    workflow_id = quote(workflow, safe="")
    _github_api_request(
        "POST",
        f"/repos/{repository}/actions/workflows/{workflow_id}/dispatches",
        token=token,
        payload={
            "ref": ref,
            "inputs": {
                "edition_date": edition_date,
                "trigger_source": trigger_source,
            },
        },
    )


def _format_timestamp(value: datetime | None) -> str:
    return value.isoformat().replace("+00:00", "Z") if value is not None else "无"


def render_summary(
    decision: WatchdogDecision,
    *,
    now: datetime,
    repository: str,
    workflow: str,
    ref: str,
    recovery_dispatched: bool,
) -> str:
    status = {
        "healthy": "✅ 当期日报已成功发布",
        "missing": "❌ 当期日报已到期但没有成功记录",
        "missing_with_active_run": "⚠️ 当期日报未成功，但已有发布运行中",
    }[decision.state]
    age = decision.age(now)
    age_text = f"{age.total_seconds() / 3600:.2f} 小时" if age else "无成功记录"
    success_text = _format_timestamp(decision.latest_success_at)
    if decision.latest_success_url:
        success_text = f"[{success_text}]({decision.latest_success_url})"

    lines = [
        "## BMTNews 日报发布心跳",
        "",
        f"**状态：{status}**",
        "",
        f"- 仓库：`{repository}`",
        f"- 工作流：`{workflow}`",
        f"- 分支：`{ref}`",
        f"- 应发布期截止：{decision.edition_cutoff.isoformat()}",
        f"- 补跑判定时间：{decision.due_at.isoformat()}",
        f"- 最近成功：{success_text}",
        f"- 距今：{age_text}",
    ]
    if decision.active_run_url:
        lines.append(f"- 正在运行：[查看发布]({decision.active_run_url})")
    if recovery_dispatched:
        lines.append("- 自动处置：已触发一次 `workflow_dispatch` 补跑")
    elif decision.state == "missing_with_active_run":
        lines.append("- 自动处置：未重复触发，等待现有发布完成")
    else:
        lines.append("- 自动处置：无需补跑")
    return "\n".join(lines) + "\n"


def _append_summary(markdown: str) -> None:
    output = os.getenv("GITHUB_STEP_SUMMARY")
    if output:
        with Path(output).open("a", encoding="utf-8") as summary:
            summary.write(markdown)
    else:
        print(markdown)


def _escape_workflow_command(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _emit_error(message: str) -> None:
    print(
        "::error title=BMTNews schedule watchdog::"
        f"{_escape_workflow_command(message)}"
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether the latest due BMTNews edition was published"
    )
    parser.add_argument(
        "--repository",
        default=os.getenv("GITHUB_REPOSITORY", ""),
        help="GitHub repository in owner/name form",
    )
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--ref", default=DEFAULT_REF)
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--cutoff-hour", type=int, default=DEFAULT_CUTOFF_HOUR)
    parser.add_argument(
        "--grace-minutes",
        type=int,
        default=DEFAULT_GRACE_MINUTES,
    )
    parser.add_argument(
        "--trigger-source",
        default="github-watchdog",
        help="Identity recorded on a dispatched daily workflow run",
    )
    parser.add_argument(
        "--success-on-recovery",
        action="store_true",
        help="Keep a parent job successful when recovery is active or dispatched",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    token = os.getenv("GITHUB_TOKEN", "")
    now = datetime.now(timezone.utc)

    if not token or not args.repository or args.grace_minutes < 0:
        message = (
            "缺少 GITHUB_TOKEN/GITHUB_REPOSITORY，或 grace-minutes 无效"
        )
        _emit_error(message)
        return 1

    try:
        runs = fetch_workflow_runs(
            token=token,
            repository=args.repository,
            workflow=args.workflow,
        )
        decision = evaluate_workflow_runs(
            runs,
            now=now,
            ref=args.ref,
            timezone_name=args.timezone,
            cutoff_hour=args.cutoff_hour,
            grace_minutes=args.grace_minutes,
        )
        recovery_dispatched = False
        if decision.should_dispatch:
            dispatch_workflow(
                token=token,
                repository=args.repository,
                workflow=args.workflow,
                ref=args.ref,
                edition_date=decision.edition_cutoff.strftime("%Y-%m-%d"),
                trigger_source=args.trigger_source,
            )
            recovery_dispatched = True
        _append_summary(
            render_summary(
                decision,
                now=now,
                repository=args.repository,
                workflow=args.workflow,
                ref=args.ref,
                recovery_dispatched=recovery_dispatched,
            )
        )
    except (GitHubApiError, OSError, ValueError) as error:
        _emit_error(str(error))
        return 1

    if decision.state == "healthy":
        print("BMTNews daily edition heartbeat is healthy.")
        return 0
    if args.success_on_recovery and (
        recovery_dispatched or decision.state == "missing_with_active_run"
    ):
        print("BMTNews daily edition recovery is active or was dispatched.")
        return 0
    if recovery_dispatched:
        _emit_error("当期日报已到期但没有成功记录，已自动触发补跑")
    else:
        _emit_error("当期日报已到期但没有成功记录，已有发布正在运行")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
