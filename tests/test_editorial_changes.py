from copy import deepcopy
from datetime import date
from pathlib import Path

from src.editorial_changes import affects_today


TODAY = date(2026, 9, 5)


def payload(**changes):
    return {"items": [{"type": "editorial", "url": "https://example.com/a",
                       "title_zh": "消息", **changes}]}


def test_drafts_future_dates_and_internal_notes_do_not_rebuild():
    assert not affects_today({}, payload(enabled=False), TODAY)
    assert not affects_today({}, payload(date="2026-09-06"), TODAY)
    assert not affects_today(payload(note="a"), payload(note="b"), TODAY)
    assert not affects_today(payload(), payload(date="2026-09-05"), TODAY)


def test_active_content_addition_update_removal_and_disable_rebuild():
    assert affects_today({}, payload(), TODAY)
    assert affects_today(payload(), {}, TODAY)
    assert affects_today(payload(), payload(summary_zh="新的正文"), TODAY)
    assert affects_today(payload(), payload(enabled=False), TODAY)
    assert affects_today(payload(), payload(date="2026-09-06"), TODAY)


def test_suppression_and_sponsored_changes_are_effective():
    suppress = {"items": [{"type": "suppress", "url": "https://example.com/a"}]}
    assert affects_today({}, suppress, TODAY)
    duplicate = deepcopy(suppress)
    duplicate["items"].append(duplicate["items"][0].copy())
    assert not affects_today(suppress, duplicate, TODAY)
    assert not affects_today({}, payload(type="sponsored", starts="2026-09-06"), TODAY)
    assert affects_today({}, payload(type="sponsored", starts="2026-09-05"), TODAY)


def test_admin_has_only_configured_login_and_pinned_integrity():
    config = Path("docs/admin/config.yml").read_text()
    page = Path("docs/admin/index.html").read_text()
    workflow = Path(".github/workflows/editorial-rebuild.yml").read_text()
    assert "auth_methods: [token]" in config
    assert 'integrity="sha384-' in page
    assert 'crossorigin="anonymous"' in page
    assert "steps.changes.outputs.changed == 'true'" in workflow
    assert "edition_date=" in workflow
