"""Curated, low-frequency background profiles for recurring entities.

Archive records explain what just happened.  These profiles explain what the
subject is, without asking the summarizer to infer an identity from one story.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping


ENTITY_PROFILES_PATH = Path(__file__).with_name("entity_profiles.json")


@dataclass(frozen=True)
class EntityProfile:
    slug: str
    label_zh: str
    label_en: str
    aliases: tuple[str, ...]
    type_zh: str
    type_en: str
    identity_zh: str
    identity_en: str
    background_zh: str
    background_en: str
    official_url: str = ""
    updates_url: str = ""

    def label_for(self, language: str) -> str:
        return self.label_en if language == "en" else self.label_zh

    def type_for(self, language: str) -> str:
        return self.type_en if language == "en" else self.type_zh

    def identity_for(self, language: str) -> str:
        return self.identity_en if language == "en" else self.identity_zh

    def background_for(self, language: str) -> str:
        return self.background_en if language == "en" else self.background_zh


def _required_text(raw: Mapping[str, object], key: str, slug: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise ValueError(f"entity profile {slug!r} is missing {key}")
    return value


@lru_cache(maxsize=4)
def load_entity_profiles(path: Path = ENTITY_PROFILES_PATH) -> dict[str, EntityProfile]:
    """Load and validate the source-controlled entity profile registry."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("entity profile schema_version must be 1")

    profiles: dict[str, EntityProfile] = {}
    for raw in payload.get("profiles", []):
        if not isinstance(raw, dict):
            raise ValueError("each entity profile must be an object")
        slug = _required_text(raw, "slug", "unknown")
        if slug in profiles:
            raise ValueError(f"duplicate entity profile slug: {slug}")
        aliases = raw.get("aliases", [])
        if not isinstance(aliases, list):
            raise ValueError(f"entity profile {slug!r} aliases must be a list")
        profiles[slug] = EntityProfile(
            slug=slug,
            label_zh=_required_text(raw, "label_zh", slug),
            label_en=_required_text(raw, "label_en", slug),
            aliases=tuple(str(value).strip() for value in aliases if str(value).strip()),
            type_zh=_required_text(raw, "type_zh", slug),
            type_en=_required_text(raw, "type_en", slug),
            identity_zh=_required_text(raw, "identity_zh", slug),
            identity_en=_required_text(raw, "identity_en", slug),
            background_zh=_required_text(raw, "background_zh", slug),
            background_en=_required_text(raw, "background_en", slug),
            official_url=str(raw.get("official_url") or "").strip(),
            updates_url=str(raw.get("updates_url") or "").strip(),
        )
    return profiles


def profile_for_slug(
    slug: str,
    profiles: Mapping[str, EntityProfile] | None = None,
) -> EntityProfile | None:
    registry = profiles if profiles is not None else load_entity_profiles()
    return registry.get(slug)
