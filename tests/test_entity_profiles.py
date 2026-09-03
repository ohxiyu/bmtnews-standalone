"""Tests for curated entity background profiles."""

import json
from pathlib import Path

import pytest

from src.entity_profiles import load_entity_profiles


def test_registry_covers_published_entities_and_major_exchanges() -> None:
    profiles = load_entity_profiles()

    assert {
        "anthropic",
        "cftc",
        "coinbase",
        "cosmos",
        "evm",
        "hyperliquid",
        "openai",
        "sec",
        "solana",
    } <= profiles.keys()
    assert {"binance", "bybit", "kraken", "okx"} <= profiles.keys()
    assert profiles["evm"].type_zh == "技术标准"
    assert profiles["coinbase"].identity_zh != profiles["coinbase"].background_zh
    assert all(
        not url or url.startswith("https://")
        for profile in profiles.values()
        for url in (profile.official_url, profile.updates_url)
    )


def test_registry_rejects_duplicate_slugs(tmp_path: Path) -> None:
    profile = {
        "slug": "duplicate",
        "label_zh": "示例",
        "label_en": "Example",
        "aliases": [],
        "type_zh": "公司",
        "type_en": "Company",
        "identity_zh": "一句说明。",
        "identity_en": "One line.",
        "background_zh": "背景说明。",
        "background_en": "Background.",
    }
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps({"schema_version": 1, "profiles": [profile, profile]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate entity profile slug"):
        load_entity_profiles(path)
