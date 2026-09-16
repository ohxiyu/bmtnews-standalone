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


def test_shared_schedule_has_exact_coverage_without_overlap_or_early_publication():
    actual = []
    for cron in configured_crons():
        minute, hour, day, month, weekday = cron.split()
        assert (day, month, weekday) == ("*", "*", "*")
        for utc_hour in range(24):
            for utc_minute in range(60):
                if matches(utc_hour, hour) and matches(utc_minute, minute):
                    actual.append(((utc_hour + 8) % 24) * 60 + utc_minute)
    expected = [7 * 60 + minute for minute in (26, 36, 46, 56)]
    expected += list(range(8 * 60, 24 * 60, 5))
    assert sorted(actual) == expected
    assert len(actual) == len(set(actual)) == 196


def test_runtime_health_and_cron_routes_match_deployment_configuration():
    source = (ROOT / "ops/daily-dispatcher/src/square.ts").read_text()
    cron = re.search(r'export const SQUARE_CRON = (".*?");', source)[1]
    match = re.search(r"export const CONFIGURED_CRONS = (\[.*?\]);", source, re.S)
    assert match is not None
    lib = (ROOT / "ops/daily-dispatcher/src/lib.ts").read_text()
    schedules = json.loads(re.search(r"export const SCHEDULE_CRONS = (\[.*?\]) as const", lib, re.S)[1])
    resolved = match[1].replace("SQUARE_CRON", cron)
    for index in (0, 1):
        resolved = resolved.replace(f"SCHEDULE_CRONS[{index}]", json.dumps(schedules[index]))
    assert json.loads(resolved) == configured_crons()
