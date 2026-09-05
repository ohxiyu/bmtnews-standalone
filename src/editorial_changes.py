"""Skip costly daily rebuilds when a saved edit cannot affect today's plan."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .editorial import editorial_plan_from_payload


def effective_content(payload: object, edition_date: date) -> dict:
    plan = editorial_plan_from_payload(payload, edition_date)
    # Scheduling fields already participated in active_on(). Notes are internal.
    excluded = {"date", "starts", "expires", "enabled", "note"}
    return {
        "editorial": [entry.model_dump(mode="json", exclude=excluded) for entry in plan.editorial],
        "sponsored": [entry.model_dump(mode="json", exclude=excluded) for entry in plan.sponsored],
        "suppressed_urls": sorted(set(plan.suppressed_urls)),
    }


def affects_today(before: object, after: object, edition_date: date) -> bool:
    return effective_content(before, edition_date) != effective_content(after, edition_date)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before-ref", required=True)
    parser.add_argument("--date", type=date.fromisoformat)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.before_ref):
        parser.error("before-ref must be an exact commit SHA")
    edition_date = args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date()
    after = json.loads(Path("data/editorial.json").read_text(encoding="utf-8"))
    previous = subprocess.run(
        ["git", "show", f"{args.before_ref}:data/editorial.json"],
        capture_output=True, text=True, check=False,
    )
    # Unknown prior state must not suppress a genuine publication.
    changed = True
    if previous.returncode == 0:
        try:
            changed = affects_today(json.loads(previous.stdout), after, edition_date)
        except ValueError:
            pass
    print(f"changed={str(changed).lower()}")
    print(f"edition_date={edition_date.isoformat()}")


if __name__ == "__main__":
    main()
