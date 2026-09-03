from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_pr_checks_do_not_repeat_after_merge() -> None:
    ci = _workflow("ci.yml")
    codeql = _workflow("codeql.yml")

    assert "pull_request:" in ci
    assert "\n  push:" not in ci
    assert "group: ci-${{ github.event.pull_request.number }}" in ci
    assert "cancel-in-progress: true" in ci
    assert "npm run check" in ci
    assert "ops/daily-dispatcher" in ci

    assert "pull_request:" in codeql
    assert "\n  push:" not in codeql
    assert 'cron: "23 3 * * 1"' in codeql
    assert (
        "group: codeql-${{ github.event.pull_request.number || github.run_id }}"
        in codeql
    )
    assert "cancel-in-progress: true" in codeql


def test_all_hosted_jobs_have_bounded_runtime() -> None:
    expected_limits = {
        "ci.yml": 15,
        "codeql.yml": 15,
        "daily-summary.yml": 30,
        "deploy-docs.yml": 10,
        "event-archive-migration.yml": 10,
        "feed-collection.yml": 30,
        "schedule-watchdog.yml": 5,
        "source-change.yml": 20,
    }

    for workflow_name, limit in expected_limits.items():
        assert (
            f"timeout-minutes: {limit}" in _workflow(workflow_name)
        ), workflow_name


def test_event_migration_has_explicit_gate_and_incremental_continuation() -> None:
    migration = _workflow("event-archive-migration.yml")
    daily = _workflow("daily-summary.yml")

    assert "workflow_dispatch:" in migration
    assert "schedule:" not in migration
    assert 'CONFIRMATION: ${{ inputs.confirmation }}' in migration
    assert 'if [ "$CONFIRMATION" != "MIGRATE" ]' in migration
    assert "group: bmtnews-feed-update" in migration
    assert "Apply reviewed migration" in migration
    assert "Verify byte-level idempotence" in migration
    assert "Verify migration coverage" in migration
    assert "peaceiris/actions-gh-pages@v4" in migration
    assert "keep_files: true" in migration

    collection = _workflow("feed-collection.yml")
    assert "Restore published event state" in collection
    assert "_data/archive" in collection
    assert "python -m src.event_brief_backfill" in collection
    assert "Deploy incremental event pages" in collection
    assert "_data/events.json" in daily
    assert "python -m src.event_brief_backfill" in daily
    assert "Apply approved event archive migration" not in daily


def test_docs_deploy_rebuilds_entities_from_published_archive() -> None:
    deploy = _workflow("deploy-docs.yml")

    assert "'src/entity_republish.py'" in deploy
    assert "Checkout current published site" in deploy
    assert "Restore current published archive" in deploy
    assert "python -m src.entity_republish" in deploy
    assert "--archive-root docs/_data/archive" in deploy
    assert "--entity-root docs/entity" in deploy
    assert "--data-root docs/_data" in deploy
