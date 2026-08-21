"""Weekly digest and scoring-calibration review built from the archive.

Both outputs read only archived editions, so the weekly job is cheap and
independent of the daily pipeline's staging state:

- the **weekly digest** is a reader-facing page summarizing the week
- the **calibration review** is a maintainer-facing note comparing what the
  curator scored highly against what actually kept generating coverage

Neither can block the daily edition: they run in their own workflow.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta
from pathlib import Path
from typing import List, Optional, Sequence

from ._file_utils import _atomic_write_text
from .ai.utils import unwrap_prose_response
from .archive import ArchiveRecord
from .threads import collect_threads

logger = logging.getLogger(__name__)

WEEKLY_ROOT = Path("docs/weekly")
DATA_ROOT = Path("docs/_data")
CALIBRATION_ROOT = DATA_ROOT / "calibration"

_LANGUAGE_NAMES = {
    "zh": "Simplified Chinese (简体中文)",
    "en": "English",
}
_LABELS = {
    "zh": {
        "title": "本周回顾",
        "intro": "过去 7 天的重点回顾，按主线、持续事件和值得记住三部分整理。",
        "stats": "本周共发布 {items} 条，覆盖 {days} 天，其中 {threads} 条持续事件。",
        "index_title": "周报存档",
        "empty": "本周暂无归档内容。",
        "back": "返回首页",
    },
    "en": {
        "title": "Weekly Review",
        "intro": "The past seven days, organized by throughline, continuing threads, and stories worth remembering.",
        "stats": "{items} stories published across {days} days, including {threads} continuing threads.",
        "index_title": "Weekly Archive",
        "empty": "Nothing archived for this week yet.",
        "back": "Back to the feed",
    },
}


@dataclass
class WeeklyContext:
    """Everything the weekly prompts need, derived from the archive."""

    start: date_type
    end: date_type
    records: List[ArchiveRecord] = field(default_factory=list)
    threads: List[tuple[str, List[ArchiveRecord]]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.records

    @property
    def stats(self) -> dict[str, int]:
        return {
            "items": len(self.records),
            "days": len({record.date for record in self.records}),
            "threads": len(self.threads),
        }


def build_weekly_context(
    records: Sequence[ArchiveRecord],
    *,
    end: date_type,
    days: int = 7,
) -> WeeklyContext:
    """Select the archive slice for the week ending on ``end`` (inclusive)."""
    start = end - timedelta(days=days - 1)
    window = [
        record
        for record in records
        if (value := record.date_value) is not None and start <= value <= end
    ]
    window.sort(key=lambda record: (record.date, record.rank))
    return WeeklyContext(
        start=start,
        end=end,
        records=window,
        threads=collect_threads(window, minimum_days=2, limit=12),
    )


def _format_items(records: Sequence[ArchiveRecord], language: str) -> str:
    lines = []
    for record in records:
        score = f"{record.score:.1f}" if record.score is not None else "—"
        summary = record.summary_for(language)
        lines.append(
            f"- [{record.date}] [{score}/10] {record.title_for(language)}"
            + (f" — {summary}" if summary else "")
        )
    return "\n".join(lines) if lines else "(none)"


def _format_threads(
    threads: Sequence[tuple[str, List[ArchiveRecord]]],
    language: str,
) -> str:
    lines = []
    for thread_id, records in threads:
        dates = sorted({record.date for record in records})
        titles = " → ".join(
            record.title_for(language)
            for record in sorted(records, key=lambda r: (r.date, r.rank))
        )
        lines.append(f"- [{thread_id}] {dates[0]}…{dates[-1]}: {titles}")
    return "\n".join(lines) if lines else "(none)"


async def generate_weekly_digest(
    ai_client,
    context: WeeklyContext,
    *,
    language: str,
    max_items: int = 60,
) -> Optional[str]:
    """Generate the weekly Markdown body.

    Returns None only when there is nothing to write about or the model
    returned nothing usable. Provider errors are raised, not swallowed.
    """
    if context.is_empty:
        return None
    from .ai.prompts import WEEKLY_DIGEST_SYSTEM, WEEKLY_DIGEST_USER

    ranked = sorted(
        context.records,
        key=lambda record: (-(record.score or 0), record.date),
    )[:max_items]
    # Errors propagate to the caller, which owns the run report and can say
    # *why* nothing was produced. Swallowing them here is what let a 400 from
    # the provider look like a successful run for two weeks.
    response = await ai_client.complete(
        system=WEEKLY_DIGEST_SYSTEM,
        user=WEEKLY_DIGEST_USER.format(
            date=context.end.isoformat(),
            language_name=_LANGUAGE_NAMES.get(language, "English"),
            items=_format_items(ranked, language),
            threads=_format_threads(context.threads, language),
        ),
        response_format="text",
    )
    text = unwrap_prose_response(
        response, keys=("digest", "review", "body", "markdown", "text")
    ).strip()
    return text or None


async def generate_calibration_review(
    ai_client,
    context: WeeklyContext,
    *,
    high_threshold: float = 8.0,
    language: str = "zh",
) -> Optional[str]:
    """Generate the maintainer-facing scoring audit.

    Returns None when there is nothing to audit. Provider errors are raised.
    """
    if context.is_empty:
        return None
    from .ai.prompts import SCORE_CALIBRATION_SYSTEM, SCORE_CALIBRATION_USER

    high = [r for r in context.records if (r.score or 0) >= high_threshold]
    low = [r for r in context.records if (r.score or 0) < high_threshold]
    if not high and not low:
        return None
    response = await ai_client.complete(
        system=SCORE_CALIBRATION_SYSTEM,
        user=SCORE_CALIBRATION_USER.format(
            date=context.end.isoformat(),
            high_threshold=f"{high_threshold:g}",
            high_items=_format_items(high[:40], language),
            low_items=_format_items(low[:40], language),
            threads=_format_threads(context.threads, language),
        ),
        response_format="text",
    )
    text = unwrap_prose_response(
        response, keys=("review", "calibration", "body", "markdown", "text")
    ).strip()
    return text or None


def render_weekly_page(
    body: str,
    context: WeeklyContext,
    *,
    language: str,
) -> str:
    """Wrap the generated Markdown in Jekyll front matter."""
    labels = _LABELS[language]
    stats = context.stats
    prefix = "" if language == "zh" else "/en"
    title = f"{labels['title']} · {context.end.isoformat()}"
    header = (
        "---\n"
        "layout: default\n"
        f'title: "{title}"\n'
        f"permalink: {prefix}/weekly/{context.end.isoformat()}/\n"
        f"interface_language: {language}\n"
        f'description: "{labels["intro"]}"\n'
        "page_type: archive\n"
        "---\n\n"
    )
    stats_line = labels["stats"].format(**stats)
    footer = f"\n\n[{labels['back']}]({prefix}/)\n"
    return f"{header}*{stats_line}*\n\n{body.strip()}{footer}"


def build_weeks_index_data(weeks: Sequence[str]) -> dict:
    """Data consumed by the always-present /weekly/ index page."""
    return {"weeks": sorted({week for week in weeks}, reverse=True)}


def save_weekly_page(
    content: str,
    *,
    end: date_type,
    language: str,
    root: Path = WEEKLY_ROOT,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    suffix = "" if language == "zh" else "en-"
    path = root / f"{suffix}{end.isoformat()}.md"
    _atomic_write_text(path, content)
    return path


def save_weeks_index_data(
    weeks: Sequence[str],
    *,
    data_root: Path = DATA_ROOT,
) -> Path:
    """Write the data file backing the committed /weekly/ index page."""
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / "weeks.json"
    _atomic_write_text(
        path,
        json.dumps(build_weeks_index_data(weeks), ensure_ascii=False, indent=2)
        + "\n",
    )
    return path


def save_calibration_review(
    body: str,
    *,
    end: date_type,
    root: Path = CALIBRATION_ROOT,
) -> Path:
    """Store the audit next to the site data (not linked from any page)."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{end.isoformat()}.md"
    _atomic_write_text(path, body.strip() + "\n")
    return path


def known_weeks(root: Path = WEEKLY_ROOT) -> List[str]:
    """List the weekly pages already published (zh filenames are canonical)."""
    if not root.exists():
        return []
    weeks = []
    for path in root.glob("*.md"):
        stem = path.stem
        if stem.startswith("en-") or stem.endswith("index"):
            continue
        weeks.append(stem)
    return sorted(set(weeks), reverse=True)
