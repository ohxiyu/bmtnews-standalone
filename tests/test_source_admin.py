from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from src.source_admin import (
    SourceChangeError,
    SourceChangeRequest,
    _source_pointers,
    apply_source_change,
    parse_workflow_dispatch,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def production_config():
    return json.loads(
        (REPO_ROOT / "data" / "config.github.json").read_text(encoding="utf-8")
    )


def request(
    *,
    operation="add",
    source_type="rss",
    source_key="new",
    name="Example Crypto",
    endpoint="https://example.com/feed.xml",
    category="crypto-markets",
    enabled=True,
    reason="Adds a focused public crypto feed.",
):
    return SourceChangeRequest(
        operation=operation,
        source_type=source_type,
        source_key=source_key,
        name=name,
        endpoint=endpoint,
        category=category,
        enabled=enabled,
        reason=reason,
    )


def test_parses_workflow_dispatch_inputs():
    parsed = parse_workflow_dispatch(
        {
            "inputs": {
                "operation": "add",
                "source_type": "rss",
                "source_key": "",
                "name": "Example Crypto",
                "endpoint": "https://example.com/feed.xml",
                "category": "crypto-markets",
                "enabled": "true",
                "reason": "补充加密市场覆盖。",
            }
        }
    )

    assert parsed.operation == "add"
    assert parsed.source_type == "rss"
    assert parsed.source_key == ""
    assert parsed.enabled is True
    assert parsed.category == "crypto-markets"


def test_adds_rss_and_validates_result(production_config):
    config = deepcopy(production_config)
    before = len(config["sources"]["rss"])

    result = apply_source_change(
        config, request(), validate_network=False
    )

    assert len(config["sources"]["rss"]) == before + 1
    assert config["sources"]["rss"][-1] == {
        "name": "Example Crypto",
        "url": "https://example.com/feed.xml",
        "enabled": True,
        "category": "crypto-markets",
    }
    assert result["source_key"] == "rss|https://example.com/feed.xml"


def test_rejects_duplicate_rss_after_url_normalization(production_config):
    config = deepcopy(production_config)
    duplicate = request(
        name="CoinDesk duplicate",
        endpoint="https://www.coindesk.com/arc/outboundfeeds/rss",
    )

    with pytest.raises(SourceChangeError, match="already exists"):
        apply_source_change(config, duplicate, validate_network=False)


def test_pauses_and_removes_existing_rss(production_config):
    config = deepcopy(production_config)
    pointers = _source_pointers(config)
    key = next(
        pointer.key
        for pointer in pointers.values()
        if pointer.source_type == "rss"
        and pointer.item["name"] == "CoinDesk"
    )

    apply_source_change(
        config,
        request(
            operation="pause",
            source_key=key,
            name="CoinDesk",
            endpoint="https://www.coindesk.com/arc/outboundfeeds/rss/",
            enabled=False,
            reason="Temporarily pause this source.",
        ),
        validate_network=False,
    )
    assert _source_pointers(config)[key].item["enabled"] is False

    before = len(config["sources"]["rss"])
    apply_source_change(
        config,
        request(
            operation="remove",
            source_key=key,
            name="CoinDesk",
            endpoint="https://www.coindesk.com/arc/outboundfeeds/rss/",
            enabled=False,
            reason="Remove the retired duplicate source.",
        ),
        validate_network=False,
    )
    assert len(config["sources"]["rss"]) == before - 1
    assert key not in _source_pointers(config)


def test_updates_telegram_channel_without_losing_limits(production_config):
    config = deepcopy(production_config)
    key = "telegram|okxannouncements"

    result = apply_source_change(
        config,
        request(
            operation="update",
            source_type="telegram",
            source_key=key,
            name="@OKX_Announcements",
            endpoint="@OKX_Announcements",
            category="exchange-announcements",
            enabled=True,
            reason="Use the current public channel name.",
        ),
        validate_network=False,
    )

    updated = _source_pointers(config)[result["source_key"]].item
    assert updated["channel"] == "OKX_Announcements"
    assert updated["fetch_limit"] == 15


def test_partial_update_preserves_unspecified_fields(production_config):
    config = deepcopy(production_config)
    key = "telegram|okxannouncements"
    before = deepcopy(_source_pointers(config)[key].item)

    result = apply_source_change(
        config,
        request(
            operation="update",
            source_type="telegram",
            source_key=key,
            name="",
            endpoint="",
            category="crypto-markets",
            enabled=None,
            reason="Move this source into the primary crypto track.",
        ),
        validate_network=False,
    )

    updated = _source_pointers(config)[result["source_key"]].item
    assert updated["channel"] == before["channel"]
    assert updated["fetch_limit"] == before["fetch_limit"]
    assert updated["enabled"] == before["enabled"]
    assert updated["category"] == "crypto-markets"


def test_pause_only_requires_key_and_reason(production_config):
    config = deepcopy(production_config)
    key = "telegram|okxannouncements"

    apply_source_change(
        config,
        request(
            operation="pause",
            source_type="telegram",
            source_key=key,
            name="",
            endpoint="",
            category="",
            enabled=None,
            reason="Pause while the source is being reviewed.",
        ),
        validate_network=False,
    )

    assert _source_pointers(config)[key].item["enabled"] is False


def test_rejects_unknown_category(production_config):
    with pytest.raises(SourceChangeError, match="Unknown category"):
        apply_source_change(
            deepcopy(production_config),
            request(category="unreviewed-category"),
            validate_network=False,
        )


def test_rejects_secret_backed_and_private_rss_urls(production_config):
    with pytest.raises(SourceChangeError, match="secret-backed"):
        apply_source_change(
            deepcopy(production_config),
            request(endpoint="https://example.com/feed?token=${PRIVATE_TOKEN}"),
            validate_network=False,
        )

    with pytest.raises(SourceChangeError, match="non-public"):
        apply_source_change(
            deepcopy(production_config),
            request(endpoint="http://127.0.0.1/feed.xml"),
            validate_network=True,
        )


def test_singleton_source_can_pause_but_not_remove(production_config):
    config = deepcopy(production_config)
    apply_source_change(
        config,
        request(
            operation="pause",
            source_type="hackernews",
            source_key="hackernews|main",
            name="Hacker News",
            endpoint="Top stories",
            category="tech-community",
            enabled=False,
            reason="Pause the general technology source.",
        ),
        validate_network=False,
    )
    assert config["sources"]["hackernews"]["enabled"] is False

    with pytest.raises(SourceChangeError, match="pause it instead"):
        apply_source_change(
            config,
            request(
                operation="remove",
                source_type="hackernews",
                source_key="hackernews|main",
                name="Hacker News",
                endpoint="Top stories",
                category="tech-community",
                enabled=False,
                reason="Do not allow singleton removal.",
            ),
            validate_network=False,
        )


def test_source_registry_is_read_only_and_workflow_is_maintainer_only():
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "source-change.yml"
    ).read_text(encoding="utf-8")
    page = (REPO_ROOT / "docs" / "s" / "index.html").read_text(
        encoding="utf-8"
    )
    legacy_page = (
        REPO_ROOT / "docs" / "sources" / "index.html"
    ).read_text(encoding="utf-8")
    layout = (
        REPO_ROOT / "docs" / "_layouts" / "default.html"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "issues:" not in workflow
    assert "Verify requestor has write access" in workflow
    assert "pull-requests: write" in workflow
    assert "gh pr create" in workflow
    assert "--draft" in workflow
    assert "data-workflow-url=" in page
    assert "source-change-form" not in page
    assert "source-dialog" not in page
    assert "permalink: /s/" in page
    assert "noindex: true" in page
    assert "/sources/" not in layout
    assert "source-console" not in legacy_page
    assert "url={{ '/' | relative_url }}" in legacy_page
