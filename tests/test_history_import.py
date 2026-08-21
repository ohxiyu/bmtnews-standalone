from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.history_import import HistoryImportError, import_published_history


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_archive(root: Path, relative: str, records: list[dict[str, object]]) -> None:
    _write(
        root,
        relative,
        "".join(f"{json.dumps(record)}\n" for record in records),
    )


def test_import_adds_only_missing_immutable_history(tmp_path: Path) -> None:
    current = tmp_path / "current"
    history = tmp_path / "history"
    output = tmp_path / "output"
    _write(current, "_posts/2026-08-21-summary-zh.md", "current")
    _write(history, "_posts/2026-08-06-summary-zh.md", "old post")
    _write(history, "editions/2026-08-06/zh.html", "old edition")
    _write(history, "_data/bmtnews_state.json", '{"date":"2026-08-06"}')
    _write(history, "index.md", "legacy home")

    report = import_published_history(current, history, output)

    assert (output / "_posts/2026-08-06-summary-zh.md").read_text() == "old post"
    assert (output / "editions/2026-08-06/zh.html").read_text() == "old edition"
    assert not (output / "_data/bmtnews_state.json").exists()
    assert not (output / "index.md").exists()
    assert report.imported_posts == 1
    assert report.imported_editions == 1
    assert report.ignored_files == 2


def test_import_is_idempotent_for_identical_current_files(tmp_path: Path) -> None:
    current = tmp_path / "current"
    history = tmp_path / "history"
    output = tmp_path / "output"
    relative = "_posts/2026-08-06-summary-en.md"
    _write(current, relative, "same")
    _write(history, relative, "same")

    report = import_published_history(current, history, output)

    assert report.imported_posts == 0
    assert report.unchanged_files == 1
    assert not (output / relative).exists()


def test_import_rejects_different_content_at_current_path(tmp_path: Path) -> None:
    current = tmp_path / "current"
    history = tmp_path / "history"
    output = tmp_path / "output"
    relative = "editions/2026-08-06/en.html"
    _write(current, relative, "new")
    _write(history, relative, "old")

    with pytest.raises(HistoryImportError, match="conflicts with the current site"):
        import_published_history(current, history, output)

    assert not output.exists()


def test_import_merges_archive_with_current_records_winning(tmp_path: Path) -> None:
    current = tmp_path / "current"
    history = tmp_path / "history"
    output = tmp_path / "output"
    relative = "_data/archive/2026-08.jsonl"
    shared = {"date": "2026-08-06", "rank": 1, "item_id": "shared"}
    current_only = {"date": "2026-08-21", "rank": 1, "item_id": "current"}
    history_only = {"date": "2026-08-05", "rank": 2, "item_id": "history"}
    _write_archive(current, relative, [shared, current_only])
    _write_archive(history, relative, [history_only, shared])

    report = import_published_history(current, history, output)

    records = [
        json.loads(line)
        for line in (output / relative).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["item_id"] for record in records] == [
        "history",
        "shared",
        "current",
    ]
    assert report.archive_records_added == 1
    assert report.archive_records_unchanged == 1


def test_import_rejects_conflicting_archive_record(tmp_path: Path) -> None:
    current = tmp_path / "current"
    history = tmp_path / "history"
    output = tmp_path / "output"
    relative = "_data/archive/2026-08.jsonl"
    _write_archive(
        current,
        relative,
        [{"date": "2026-08-06", "rank": 1, "item_id": "same"}],
    )
    _write_archive(
        history,
        relative,
        [{"date": "2026-08-06", "rank": 2, "item_id": "same"}],
    )

    with pytest.raises(HistoryImportError, match="Archive history conflicts"):
        import_published_history(current, history, output)


def test_import_rejects_history_symlinks(tmp_path: Path) -> None:
    current = tmp_path / "current"
    history = tmp_path / "history"
    output = tmp_path / "output"
    current.mkdir()
    history.mkdir()
    target = history / "target.md"
    target.write_text("target", encoding="utf-8")
    link = history / "_posts/2026-08-06-summary-en.md"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)

    with pytest.raises(HistoryImportError, match="may not contain symlinks"):
        import_published_history(current, history, output)
