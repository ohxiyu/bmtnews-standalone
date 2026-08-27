from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import schedule_watchdog


# 08:47 in Asia/Shanghai: the 08:00 edition has reached its fallback time.
NOW = datetime(2026, 7, 27, 0, 47, tzinfo=timezone.utc)


def _run(
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    started_at: datetime,
    branch: str = "main",
    run_id: int = 1,
) -> dict[str, object]:
    completed_at = started_at + timedelta(minutes=5)
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "head_branch": branch,
        "created_at": started_at.isoformat(),
        "run_started_at": started_at.isoformat(),
        "updated_at": completed_at.isoformat(),
        "html_url": f"https://github.com/ohxiyu/bmtnews-standalone/actions/runs/{run_id}",
    }


def test_success_after_current_cutoff_is_healthy() -> None:
    decision = schedule_watchdog.evaluate_workflow_runs(
        [_run(started_at=NOW - timedelta(minutes=20))],
        now=NOW,
        ref="main",
    )

    assert decision.state == "healthy"
    assert decision.should_dispatch is False
    assert decision.edition_cutoff.isoformat() == "2026-07-27T08:00:00+08:00"


def test_previous_edition_success_requests_recovery_dispatch() -> None:
    decision = schedule_watchdog.evaluate_workflow_runs(
        [_run(started_at=NOW - timedelta(hours=23))],
        now=NOW,
        ref="main",
    )

    assert decision.state == "missing"
    assert decision.should_dispatch is True


def test_late_retry_still_requests_current_edition() -> None:
    late_retry = datetime(2026, 7, 27, 5, 17, tzinfo=timezone.utc)
    decision = schedule_watchdog.evaluate_workflow_runs(
        [_run(started_at=NOW - timedelta(hours=23))],
        now=late_retry,
        ref="main",
    )

    assert decision.state == "missing"
    assert decision.should_dispatch is True
    assert decision.edition_cutoff.isoformat() == "2026-07-27T08:00:00+08:00"


def test_missing_success_does_not_duplicate_current_active_run() -> None:
    decision = schedule_watchdog.evaluate_workflow_runs(
        [
            _run(started_at=NOW - timedelta(hours=23)),
            _run(
                status="in_progress",
                conclusion=None,
                started_at=NOW - timedelta(minutes=2),
                run_id=2,
            ),
        ],
        now=NOW,
        ref="main",
    )

    assert decision.state == "missing_with_active_run"
    assert decision.should_dispatch is False
    assert decision.active_run_url is not None


def test_runs_from_other_branches_do_not_satisfy_main() -> None:
    decision = schedule_watchdog.evaluate_workflow_runs(
        [
            _run(
                started_at=NOW - timedelta(minutes=20),
                branch="agent/example",
            )
        ],
        now=NOW,
        ref="main",
    )

    assert decision.state == "missing"
    assert decision.latest_success_at is None


def test_before_grace_period_still_checks_previous_edition() -> None:
    before_grace = datetime(
        2026, 7, 27, 0, 20, tzinfo=timezone.utc
    )
    previous_success = datetime(
        2026, 7, 26, 1, 0, tzinfo=timezone.utc
    )
    decision = schedule_watchdog.evaluate_workflow_runs(
        [_run(started_at=previous_success)],
        now=before_grace,
        ref="main",
    )

    assert decision.state == "healthy"
    assert decision.edition_cutoff.isoformat() == "2026-07-26T08:00:00+08:00"


def test_main_dispatches_recovery_and_fails_for_notification(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    summary = tmp_path / "summary.md"
    dispatches: list[dict[str, str]] = []
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "ohxiyu/bmtnews-standalone")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(schedule_watchdog, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        schedule_watchdog,
        "fetch_workflow_runs",
        lambda **kwargs: [],
    )
    monkeypatch.setattr(
        schedule_watchdog,
        "dispatch_workflow",
        lambda **kwargs: dispatches.append(kwargs),
    )

    exit_code = schedule_watchdog.main([])

    assert exit_code == 1
    assert dispatches == [
        {
            "token": "test-token",
            "repository": "ohxiyu/bmtnews-standalone",
            "workflow": "daily-summary.yml",
            "ref": "main",
            "edition_date": "2026-07-27",
        }
    ]
    assert "已触发一次 `workflow_dispatch` 补跑" in summary.read_text(
        encoding="utf-8"
    )
    assert "日报发布心跳" in summary.read_text(encoding="utf-8")
    assert "::error title=BMTNews schedule watchdog::" in capsys.readouterr().out


def test_dispatch_includes_explicit_edition_inputs(monkeypatch) -> None:
    requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        schedule_watchdog,
        "_github_api_request",
        lambda method, path, **kwargs: requests.append(
            {"method": method, "path": path, **kwargs}
        ),
    )

    schedule_watchdog.dispatch_workflow(
        token="test-token",
        repository="ohxiyu/bmtnews-standalone",
        workflow="daily-summary.yml",
        ref="main",
        edition_date="2026-07-27",
    )

    assert requests[0]["payload"] == {
        "ref": "main",
        "inputs": {
            "edition_date": "2026-07-27",
            "trigger_source": "github-watchdog",
        },
    }


def test_watchdog_workflow_has_schedule_aware_arguments() -> None:
    workflow = (
        Path(__file__).parents[1]
        / ".github"
        / "workflows"
        / "schedule-watchdog.yml"
    ).read_text(encoding="utf-8")

    assert "cron: '47 0 * * *'" in workflow
    assert "cron: '17 1-7 * * *'" in workflow
    assert "timezone:" not in workflow
    assert "cron: '47 8 * * *'" not in workflow
    assert "43 * * * *" not in workflow
    assert "actions: write" in workflow
    assert "timeout-minutes: 5" in workflow
    assert "actions/setup-python" not in workflow
    assert "--timezone Asia/Shanghai" in workflow
    assert "--cutoff-hour 8" in workflow
    assert "--grace-minutes 47" in workflow
    assert "--threshold-hours" not in workflow
