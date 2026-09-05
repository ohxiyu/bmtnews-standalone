"""Expand the production UTC schedule to verify the Shanghai coverage."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def matches(value, field):
    if field == "*":
        return True
    if field.startswith("*/"):
        return value % int(field[2:]) == 0
    if "," in field:
        return any(matches(value, part) for part in field.split(","))
    if "-" in field:
        start, end = map(int, field.split("-"))
        return start <= value <= end
    return value == int(field)


def configured_crons():
    return json.loads(
        (ROOT / "ops/daily-dispatcher/wrangler.jsonc").read_text()
    )["triggers"]["crons"]


def test_daily_schedule_has_exact_coverage_without_overlap_or_early_publication():
    actual = []
    for cron in configured_crons():
        minute, hour, day, month, weekday = cron.split()
        assert (day, month, weekday) == ("*", "*", "*")
        for utc_hour in range(24):
            for utc_minute in range(60):
                if matches(utc_hour, hour) and matches(utc_minute, minute):
                    actual.append(((utc_hour + 8) % 24) * 60 + utc_minute)
    expected = list(range(8 * 60 + 30, 12 * 60, 10))
    expected += list(range(12 * 60, 23 * 60 + 1, 60))
    assert sorted(actual) == expected
    assert len(actual) == len(set(actual)) == 33


def test_runtime_health_and_cron_routes_match_deployment_configuration():
    source = (ROOT / "ops/daily-dispatcher/src/lib.ts").read_text()
    match = re.search(r"export const SCHEDULE_CRONS = (\[.*?\]) as const;", source, re.S)
    assert match is not None
    assert json.loads(match[1]) == configured_crons()
