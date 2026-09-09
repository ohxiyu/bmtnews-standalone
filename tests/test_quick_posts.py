from copy import deepcopy
from datetime import date
import json
from pathlib import Path

from src.quick_posts import public_posts, render_posts, publish
from src.editorial_changes import affects_today

DAY = date(2026, 9, 10)
ROW = {"type": "quick_post", "id": "12345678-1234-1234-1234-123456789abc",
       "body": "第一段。\n\n第二段 🚀", "date": "2026-09-10", "enabled": True,
       "updated_at": "2026-09-10T01:00:00Z", "note": "private", "request_hash": "private"}


def test_public_field_allowlist_and_no_fake_title_or_score():
    rows = public_posts({"items": [ROW]}, DAY)
    assert rows[0]["body"] == ROW["body"]
    assert not set(rows[0]) & {"note", "request_hash", "title", "score", "enabled"}
    assert rows[0]["url"] == ""


def test_drafts_future_old_invalid_and_duplicates_are_excluded():
    rows = [ROW, ROW, {**ROW, "id": "b" * 36, "enabled": False},
            {**ROW, "id": "c" * 36, "date": "2026-09-11"},
            {**ROW, "id": "d" * 36, "date": "2026-09-08"},
            {**ROW, "id": "e" * 36, "date": "bad"}]
    assert len(public_posts({"items": rows}, DAY)) == 1


def test_dates_and_pin_order():
    rows = [ROW, {**ROW, "id": "b" * 36, "date": "2026-09-09", "pin": True},
            {**ROW, "id": "c" * 36, "pin": True}]
    result = public_posts({"items": rows}, DAY)
    assert [row["id"] for row in result] == ["c" * 36, ROW["id"], "b" * 36]


def test_markup_urls_and_liquid_are_not_executed():
    row = {**ROW, "body": '<script>alert(1)</script>\n\n{{ secret }}', "url": "javascript:alert(1)",
           "image": '/assets/uploads/../../private'}
    result = public_posts({"items": [row]}, DAY)
    rendered = render_posts(result)
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "<p>{{ secret }}</p>" in rendered
    assert "<img" not in rendered and "javascript:" not in rendered
    assert rendered.count("<p>") == 2


def test_render_image_source_and_badges():
    row = {**ROW, "image": "/assets/uploads/quick-" + "a" * 64 + ".png",
           "url": "https://example.com/?x=1&y=2", "pin": True, "breaking": True}
    rendered = render_posts(public_posts({"items": [row]}, DAY))
    assert "Breaking" in rendered and "PIN" in rendered
    assert 'loading="lazy"' in rendered and "&amp;y=2" in rendered


def test_quick_only_edits_do_not_trigger_ai_rebuild():
    before = {"items": [{"type": "suppress", "url": "https://example.com", "date": str(DAY)}]}
    after = deepcopy(before)
    after["items"].append(ROW)
    assert not affects_today(before, after, DAY)


def test_publish_matches_html_and_json(tmp_path):
    source = tmp_path / "editorial.json"
    source.write_text(json.dumps({"items": [ROW]}))
    publish(source, tmp_path / "docs", DAY)
    data = json.loads((tmp_path / "docs/api/quick-posts.json").read_text())
    html = json.loads((tmp_path / "docs/_data/quick_posts.json").read_text())["html"]
    assert data["items"][0]["id"] in html
    assert "private" not in html
    assert data["date"] == str(DAY)


def test_all_publication_workflows_regenerate_stream():
    root = Path(__file__).parents[1]
    for name in ["daily-summary", "feed-collection", "deploy-docs", "weekly-review", "event-archive-migration"]:
        text = (root / f".github/workflows/{name}.yml").read_text()
        assert "uv run python -m src.quick_posts" in text
    page = (root / "docs/_includes/feed-home.html").read_text()
    assert "site.data.quick_posts.html" in page
