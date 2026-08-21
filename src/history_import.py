"""Import immutable published history without replacing the current site."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


_POST_PATTERN = re.compile(
    r"^_posts/\d{4}-\d{2}-\d{2}-summary-(?:en|zh)\.md$"
)
_EDITION_PATTERN = re.compile(
    r"^editions/\d{4}-\d{2}-\d{2}/(?:edition\.json|en\.html|zh\.html)$"
)
_ARCHIVE_PATTERN = re.compile(r"^_data/archive/\d{4}-\d{2}\.jsonl$")


class HistoryImportError(ValueError):
    """Raised when a published-history snapshot cannot be merged safely."""


@dataclass(frozen=True)
class HistoryImportReport:
    """Summary of a published-history import."""

    imported_posts: int
    imported_editions: int
    unchanged_files: int
    archive_records_added: int
    archive_records_unchanged: int
    ignored_files: int


def _relative_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise HistoryImportError(f"History root does not exist: {root}")
    files: list[Path] = []
    for directory, directory_names, file_names in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in list(directory_names):
            path = directory_path / name
            if name == ".git":
                directory_names.remove(name)
                continue
            if path.is_symlink():
                raise HistoryImportError(
                    f"History snapshots may not contain symlinks: {path}"
                )
        for name in file_names:
            if name == ".git" and directory_path == root:
                continue
            path = directory_path / name
            if path.is_symlink():
                raise HistoryImportError(
                    f"History snapshots may not contain symlinks: {path}"
                )
            files.append(path.relative_to(root))
    return sorted(files, key=lambda path: path.as_posix())


def _immutable_kind(relative: Path) -> str | None:
    name = relative.as_posix()
    if _POST_PATTERN.fullmatch(name):
        return "post"
    if _EDITION_PATTERN.fullmatch(name):
        return "edition"
    return None


def _plan_immutable_files(
    current_root: Path,
    history_root: Path,
    history_files: Iterable[Path],
) -> tuple[list[tuple[str, Path]], int]:
    planned: list[tuple[str, Path]] = []
    unchanged = 0
    for relative in history_files:
        kind = _immutable_kind(relative)
        if kind is None:
            continue
        history_path = history_root / relative
        current_path = current_root / relative
        if current_path.exists():
            if current_path.is_symlink() or not current_path.is_file():
                raise HistoryImportError(
                    f"Current published path is not a regular file: {relative.as_posix()}"
                )
            if current_path.read_bytes() != history_path.read_bytes():
                raise HistoryImportError(
                    "Published history conflicts with the current site: "
                    f"{relative.as_posix()}"
                )
            unchanged += 1
            continue
        planned.append((kind, relative))
    return planned, unchanged


def _archive_identity(record: dict[str, Any]) -> tuple[str, str]:
    date = record.get("date")
    item_id = record.get("item_id")
    if not isinstance(date, str) or not date:
        raise HistoryImportError("Archive record is missing a string date")
    if not isinstance(item_id, str) or not item_id:
        raise HistoryImportError("Archive record is missing a string item_id")
    return date, item_id


def _read_archive(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise HistoryImportError(f"Archive path is not a regular file: {path}")

    records: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise HistoryImportError(
                f"Invalid JSONL record in {path}:{line_number}"
            ) from exc
        if not isinstance(value, dict):
            raise HistoryImportError(
                f"Archive record must be an object in {path}:{line_number}"
            )
        _archive_identity(value)
        records.append(value)
    return records


def _merge_archive(
    current_path: Path,
    history_path: Path,
) -> tuple[list[dict[str, Any]], int, int]:
    current_records = _read_archive(current_path)
    history_records = _read_archive(history_path)
    merged = {_archive_identity(record): record for record in current_records}
    added = 0
    unchanged = 0
    for record in history_records:
        identity = _archive_identity(record)
        existing = merged.get(identity)
        if existing is None:
            merged[identity] = record
            added += 1
        elif existing == record:
            unchanged += 1
        else:
            raise HistoryImportError(
                "Archive history conflicts with the current site: "
                f"date={identity[0]} item_id={identity[1]}"
            )
    ordered = sorted(
        merged.values(),
        key=lambda record: (
            str(record.get("date", "")),
            int(record.get("rank", 0)),
            str(record.get("item_id", "")),
        ),
    )
    return ordered, added, unchanged


def import_published_history(
    current_root: Path,
    history_root: Path,
    output_root: Path,
) -> HistoryImportReport:
    """Add missing immutable editions and archive records to ``output_root``.

    Current published files always win. A same-path or same-record difference is
    treated as a conflict instead of being overwritten. Runtime state, feeds,
    indexes, assets, and other mutable files are deliberately ignored.
    """

    current_root = current_root.resolve()
    history_root = history_root.resolve()
    output_root = output_root.resolve()
    history_files = _relative_files(history_root)
    planned, unchanged_files = _plan_immutable_files(
        current_root,
        history_root,
        history_files,
    )
    immutable_files_seen = len(planned) + unchanged_files

    archive_paths = [
        relative
        for relative in history_files
        if _ARCHIVE_PATTERN.fullmatch(relative.as_posix())
    ]
    archive_results: list[tuple[Path, list[dict[str, Any]]]] = []
    archive_records_added = 0
    archive_records_unchanged = 0
    for relative in archive_paths:
        records, added, unchanged = _merge_archive(
            current_root / relative,
            history_root / relative,
        )
        archive_results.append((relative, records))
        archive_records_added += added
        archive_records_unchanged += unchanged

    imported_posts = 0
    imported_editions = 0
    for kind, relative in planned:
        destination = output_root / relative
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise HistoryImportError(
                    f"Output path is not a regular file: {relative.as_posix()}"
                )
            if destination.read_bytes() != (history_root / relative).read_bytes():
                raise HistoryImportError(
                    f"Output already contains a different file: {relative.as_posix()}"
                )
            unchanged_files += 1
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(history_root / relative, destination)
        if kind == "post":
            imported_posts += 1
        else:
            imported_editions += 1

    for relative, records in archive_results:
        destination = output_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = "".join(
            f"{json.dumps(record, ensure_ascii=False, separators=(',', ':'))}\n"
            for record in records
        )
        destination.write_text(payload, encoding="utf-8")

    handled = immutable_files_seen + len(archive_paths)
    return HistoryImportReport(
        imported_posts=imported_posts,
        imported_editions=imported_editions,
        unchanged_files=unchanged_files,
        archive_records_added=archive_records_added,
        archive_records_unchanged=archive_records_unchanged,
        ignored_files=max(0, len(history_files) - handled),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely import immutable BMTNews published history"
    )
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = import_published_history(args.current, args.history, args.output)
    payload = json.dumps(asdict(report), ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(f"{payload}\n", encoding="utf-8")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
