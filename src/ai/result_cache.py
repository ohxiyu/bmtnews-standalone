"""Small persistent cache for deterministic AI-derived item fields."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .._file_utils import _atomic_write_text
from ..models import ContentItem
from . import prompts


CACHE_VERSION = 1
ENRICHMENT_POLICY_VERSION = "news-editorial-v4"
ANALYSIS_FIELDS = ("ai_score", "ai_reason", "ai_summary", "ai_tags")
ENRICHMENT_PREFIXES = (
    "title_",
    "detailed_summary",
    "background",
    "community_discussion",
    "market_impact",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisResultCache:
    """JSON-backed cache shared between scheduled runs.

    Keys include the model, prompt revision and source content, so changing
    either the input or the editorial prompt cannot silently reuse stale AI
    output. Corrupt or old cache files fail open.
    """

    def __init__(
        self,
        path: Path,
        *,
        model: str,
        ttl_days: int = 30,
        max_entries: int = 4000,
        prompt_revision: str = "2026-09-input-aware-v2",
    ) -> None:
        self.path = path
        self.model = model
        self.ttl = timedelta(days=max(1, ttl_days))
        self.max_entries = max(100, max_entries)
        self.prompt_revision = prompt_revision
        self.analysis_context = None
        self.entries: dict[str, dict[str, Any]] = {}
        self.hits = 0
        self.misses = 0
        self.comparison_hits = 0
        self.comparison_misses = 0
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") == CACHE_VERSION and isinstance(
                payload.get("entries"), dict
            ):
                self.entries = payload["entries"]
        except (OSError, ValueError, TypeError):
            self.entries = {}
        self._prune()

    def _key(self, item: ContentItem, stage: str) -> str:
        material = json.dumps(
            {
                "stage": stage,
                **({"enrichment_policy": ENRICHMENT_POLICY_VERSION} if stage == "enrichment" else {}),
                "edition_window": self.analysis_context if stage == "analysis" else None,
                "model": self.model,
                "prompt": self.prompt_revision,
                "prompt_text": [
                    getattr(prompts, name, "")
                    for name in (
                        ("CONTENT_ANALYSIS_SYSTEM", "CONTENT_ANALYSIS_USER")
                        if stage == "analysis" else
                        ("CONTENT_ENRICHMENT_SYSTEM", "CONTENT_ENRICHMENT_USER", "CONCEPT_EXTRACTION_SYSTEM")
                    )
                ],
                "url": str(item.url),
                "title": item.title,
                "published_at": item.published_at.isoformat(),
                "content": (item.content or "")[:8000],
                "engagement": {key: item.metadata.get(key) for key in ("score", "descendants", "num_comments", "comments", "replies")},
                "analysis_inputs": {
                    "summary": item.ai_summary, "score": item.ai_score,
                    "reason": item.ai_reason,
                    "tags": ([] if item.metadata.get("evaluation") else item.ai_tags),
                } if stage == "enrichment" else None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _get(self, item: ContentItem, stage: str) -> dict[str, Any] | None:
        return self._get_key(self._key(item, stage))

    def _get_key(self, key: str) -> dict[str, Any] | None:
        entry = self.entries.get(key)
        if not isinstance(entry, dict):
            self.misses += 1
            return None
        try:
            stored_at = datetime.fromisoformat(str(entry["stored_at"]))
            if stored_at.tzinfo is None:
                stored_at = stored_at.replace(tzinfo=timezone.utc)
        except (KeyError, TypeError, ValueError):
            self.misses += 1
            return None
        if _utc_now() - stored_at > self.ttl or not isinstance(
            entry.get("value"), dict
        ):
            self.entries.pop(key, None)
            self._dirty = True
            self.misses += 1
            return None
        self.hits += 1
        return entry["value"]

    def _comparison_key(self, system: str, user: str) -> str:
        material = json.dumps(["comparison-v1", self.model, self.prompt_revision,
                               system, user], ensure_ascii=False)
        return hashlib.sha256(material.encode()).hexdigest()

    def get_comparison(self, system: str, user: str) -> dict[str, Any] | None:
        value = self._get_key(self._comparison_key(system, user))
        if value is None:
            self.comparison_misses += 1
        else:
            self.comparison_hits += 1
        return value

    def store_comparison(self, system: str, user: str, value: dict[str, Any]) -> None:
        """Caller must validate indices before storing; hits are revalidated."""
        self.entries[self._comparison_key(system, user)] = {
            "stored_at": _utc_now().isoformat(), "value": value,
        }
        self._dirty = True

    def restore_analysis(self, item: ContentItem) -> bool:
        value = self._get(item, "analysis")
        if value is None:
            return False
        for field in ANALYSIS_FIELDS:
            if field in value:
                setattr(item, field, value[field])
        if isinstance(value.get("category"), str):
            item.metadata["category"] = value["category"]
        if "source_category" in value:
            item.metadata["source_category"] = value["source_category"]
        if "evaluation" in value:
            item.metadata["evaluation"] = value["evaluation"]
            item.metadata.pop("evaluation_error", None)
            item.metadata.pop("evaluation_degraded", None)
        return item.ai_score is not None

    def store_analysis(self, item: ContentItem) -> None:
        if item.metadata.get("evaluation_degraded") or item.metadata.get("evaluation_error"):
            return
        if item.ai_score is None or item.ai_reason in {
            "Analysis failed",
            "Analysis response parse failed",
        }:
            return
        value = {field: getattr(item, field) for field in ANALYSIS_FIELDS}
        value["category"] = item.metadata.get("category")
        if "evaluation" in item.metadata:
            value["evaluation"] = item.metadata["evaluation"]
        if "source_category" in item.metadata:
            value["source_category"] = item.metadata["source_category"]
        self._put(item, "analysis", value)

    def restore_enrichment(self, item: ContentItem) -> bool:
        value = self._get(item, "enrichment")
        if value is None:
            return False
        item.metadata.update(value)
        if isinstance(value.get("editorial_tags"), list):
            item.ai_tags = list(value["editorial_tags"])
        return True

    def store_enrichment(self, item: ContentItem) -> None:
        if item.metadata.get("enrichment_status") in {"rejected", "verification_unavailable"}:
            return
        value = {
            key: val
            for key, val in item.metadata.items()
            if key in {"sources", "editorial_tags", "evaluation_grounding", "enrichment_status", "grounding_checks", "enrichment_fallback_reason"}
            or any(key.startswith(prefix) for prefix in ENRICHMENT_PREFIXES)
        }
        complete = any(
            key.startswith(("background_", "market_impact_")) and bool(val)
            for key, val in value.items()
        )
        verified_short = (
            value.get("evaluation_grounding") in {"supported_translation", "supported_core", "supported_sections"}
            and all(value.get(f"detailed_summary_{lang}") for lang in ("en", "zh"))
        )
        if value and (complete or verified_short):
            self._put(item, "enrichment", value)

    def _put(self, item: ContentItem, stage: str, value: dict[str, Any]) -> None:
        self.entries[self._key(item, stage)] = {
            "stored_at": _utc_now().isoformat(),
            "value": value,
        }
        self._dirty = True

    def _prune(self) -> None:
        cutoff = _utc_now() - self.ttl
        retained: list[tuple[str, dict[str, Any], datetime]] = []
        for key, entry in self.entries.items():
            try:
                stored_at = datetime.fromisoformat(str(entry["stored_at"]))
                if stored_at.tzinfo is None:
                    stored_at = stored_at.replace(tzinfo=timezone.utc)
            except (KeyError, TypeError, ValueError):
                continue
            if stored_at >= cutoff:
                retained.append((key, entry, stored_at))
        retained.sort(key=lambda row: row[2], reverse=True)
        pruned = {
            key: entry for key, entry, _ in retained[: self.max_entries]
        }
        if len(pruned) != len(self.entries):
            self._dirty = True
        self.entries = pruned

    def save(self) -> None:
        if not self._dirty:
            return
        self._prune()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(
            self.path,
            json.dumps(
                {"version": CACHE_VERSION, "entries": self.entries},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        self._dirty = False

    def snapshot(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": len(self.entries),
        }


def split_cached(
    cache: AnalysisResultCache,
    items: Iterable[ContentItem],
    *,
    stage: str,
) -> tuple[list[ContentItem], list[ContentItem]]:
    """Return cache hits and misses while applying cached fields in place."""
    restore = (
        cache.restore_analysis if stage == "analysis" else cache.restore_enrichment
    )
    hits: list[ContentItem] = []
    misses: list[ContentItem] = []
    for item in items:
        (hits if restore(item) else misses).append(item)
    return hits, misses
