"""Content analysis using AI."""

import asyncio
import json
import re
from datetime import timedelta
from typing import Iterable, List, Optional
from pydantic import BaseModel, Field, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, MofNCompleteColumn

from .client import AIClient
from .evaluator import create_evaluator, EvaluationError
from .prompts import CONTENT_ANALYSIS_SYSTEM, CONTENT_ANALYSIS_USER
from .utils import parse_json_response
from ..models import ContentItem
from ..edition import EditionWindow, edition_window_for

DEFAULT_THROTTLE_SEC = 0.0


class AnalysisResult(BaseModel):
    """Validated structured result returned by the analysis model."""

    score: float = Field(ge=0, le=10, allow_inf_nan=False)
    reason: str
    summary: str
    tags: list[str]
    category: Optional[str] = None


class ContentAnalyzer:
    """Analyzes content items using AI to determine importance."""

    def __init__(
        self,
        ai_client: AIClient,
        *,
        allowed_categories: Optional[Iterable[str]] = None,
        edition_window: Optional[EditionWindow] = None,
    ):
        self.client = ai_client
        self.evaluator = create_evaluator(getattr(ai_client, "config", None))
        self.edition_window = edition_window
        self.allowed_categories = tuple(
            dict.fromkeys(
                category.strip()
                for category in (allowed_categories or [])
                if category.strip()
            )
        )
        self._allowed_category_set = set(self.allowed_categories)

    @staticmethod
    def _parse_json_response(response: str) -> Optional[dict]:
        """Try multiple strategies to extract a JSON object from an AI response.

        Returns the parsed dict, or None if all strategies fail.
        """
        return parse_json_response(response)

    def _get_throttle_sec(self) -> float:
        """Return the configured inter-item throttle, clamped to zero or above."""
        config = getattr(self.client, "config", None)
        throttle_sec = getattr(config, "throttle_sec", DEFAULT_THROTTLE_SEC)
        return max(throttle_sec, 0.0)

    def _get_concurrency(self) -> int:
        """Return the configured analysis concurrency, clamped to 1 or above."""
        config = getattr(self.client, "config", None)
        concurrency = getattr(config, "analysis_concurrency", 1)
        return max(concurrency, 1)

    async def analyze_batch(self, items: List[ContentItem]) -> List[ContentItem]:
        # Enabled evaluation has one owner and its own bounded request retry.
        if self.evaluator is not None:
            semaphore = asyncio.Semaphore(self._get_concurrency())
            async def evaluate(item):
                async with semaphore:
                    item.ai_score = None
                    item.ai_reason = None
                    item.ai_summary = item.title
                    item.ai_tags = []
                    item.metadata.pop("evaluation", None)
                    item.metadata.pop("evaluation_degraded", None)
                    item.metadata.pop("evaluation_error", None)
                    window = self.edition_window or edition_window_for(
                        item.published_at + timedelta(days=1), "Asia/Shanghai",
                    )
                    try:
                        await self.evaluator.analyze(item, self.allowed_categories, window)
                    except EvaluationError as exc:
                        item.ai_score = None
                        item.metadata["evaluation_error"] = {"code": exc.code, "status": exc.status_code}
                        print(f"Jev score pending for {item.id}: {exc}")
            await asyncio.gather(*(evaluate(item) for item in items))
            return items

        throttle_sec = self._get_throttle_sec()
        concurrency = self._get_concurrency()
        semaphore = asyncio.Semaphore(concurrency)

        async def _process(item: ContentItem, index: int, progress_task) -> ContentItem:
            async with semaphore:
                try:
                    await self._analyze_item(item)
                except Exception as e:
                    print(f"Error analyzing item {item.id}: {e}")
                    item.ai_score = 0.0
                    item.ai_reason = "Analysis failed"
                    item.ai_summary = item.title
            # Never hold a scarce model-concurrency slot while only waiting
            # for the provider pacing delay.
            if throttle_sec > 0 and index < len(items) - 1:
                await asyncio.sleep(throttle_sec)
            progress.advance(progress_task)
            return item

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            transient=True,
        ) as progress:
            task = progress.add_task("Analyzing", total=len(items))
            coros = [
                _process(item, i, task) for i, item in enumerate(items)
            ]
            analyzed_items = await asyncio.gather(*coros)

        return analyzed_items

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=10)
    )
    async def _analyze_item(self, item: ContentItem) -> None:
        """Analyze a single content item.

        Args:
            item: Content item to analyze (modified in-place)
        """
        # Prepare content section
        content_section = ""
        if item.content:
            # Split off comments if present
            content_text = item.content
            if "--- Top Comments ---" in content_text:
                main, comments_part = content_text.split("--- Top Comments ---", 1)
                content_section = f"Content: {main.strip()[:800]}"
            else:
                content_section = f"Content: {content_text[:1000]}"

        # Prepare discussion section (comments, engagement)
        discussion_parts = []
        if item.content and "--- Top Comments ---" in item.content:
            comments_part = item.content.split("--- Top Comments ---", 1)[1]
            discussion_parts.append(f"Community Comments:\n{comments_part[:1500]}")

        meta = item.metadata
        engagement_items = []
        if meta.get("score"):
            engagement_items.append(f"score: {meta['score']}")
        if meta.get("descendants"):
            engagement_items.append(f"{meta['descendants']} comments")
        if meta.get("favorite_count"):
            engagement_items.append(f"{meta['favorite_count']} likes")
        if meta.get("retweet_count"):
            engagement_items.append(f"{meta['retweet_count']} retweets")
        if meta.get("reply_count"):
            engagement_items.append(f"{meta['reply_count']} replies")
        if meta.get("views"):
            engagement_items.append(f"{meta['views']} views")
        if meta.get("bookmarks"):
            engagement_items.append(f"{meta['bookmarks']} bookmarks")
        if meta.get("upvote_ratio"):
            engagement_items.append(f"upvote ratio: {meta['upvote_ratio']:.0%}")
        if engagement_items:
            discussion_parts.append(f"Engagement: {', '.join(engagement_items)}")
        if meta.get("discussion_url"):
            discussion_parts.append(f"Discussion: {meta['discussion_url']}")
        if meta.get("community_note"):
            discussion_parts.append(f"Community Note: {meta['community_note']}")

        discussion_section = "\n".join(discussion_parts) if discussion_parts else ""

        # Generate user prompt
        if self.allowed_categories:
            category_instruction = (
                "Choose the single best content category from this exact JSON list: "
                f"{json.dumps(self.allowed_categories)}. Classify the article itself, "
                "not the publisher or feed."
            )
        else:
            category_instruction = (
                "No content-category taxonomy is configured; return null for category."
            )
        user_prompt = CONTENT_ANALYSIS_USER.format(
            title=item.title,
            source=f"{item.source_type.value}",
            author=item.author or "Unknown",
            url=str(item.url),
            source_category=item.metadata.get("category") or "Unclassified",
            category_instruction=category_instruction,
            content_section=content_section,
            discussion_section=discussion_section
        )

        # Apply only to requests already needed on cache misses. Preserve the
        # existing cache/prompt fingerprints: no paid historical rescoring.
        # Collection runs use the fixed edition containing publication, never
        # wall-clock time (which would misdate retries and historical runs).
        window = self.edition_window or edition_window_for(
            item.published_at + timedelta(days=1), "Asia/Shanghai",
        )
        freshness = (
            f"Publication: {item.published_at.isoformat()}. "
            f"News window: [{window.start.isoformat()}, {window.end.isoformat()}). "
            "Score 0 for a recap of events before this window without a concrete "
            "in-window development. Recent publication, popularity or importance "
            "does not make an old event new. Resolve relative dates against publication; "
            "do not invent event dates. For a genuine new development, score and "
            "summarize that development, not the old background. Explain in reason."
        )

        # Replace the verbose secondary considerations, rather than adding a
        # second pass or expanding the input budget. Scoring anchors stay intact.
        before, rest = CONTENT_ANALYSIS_SYSTEM.split("Consider:\n", 1)
        _, calibration = rest.split("Scoring granularity and calibration:", 1)
        system_prompt = (
            before + freshness
            + "\nJudge evidenced impact and novelty; popularity and official marketing "
            "alone do not establish value. AI/technology need no crypto connection.\n\n"
            + "Scoring granularity and calibration:" + calibration
        )

        # Get AI completion
        response = await self.client.complete(
            system=system_prompt,
            user=user_prompt,
        )

        # Parse JSON response with robust fallback
        parsed = self._parse_json_response(response)
        try:
            result = AnalysisResult.model_validate(parsed) if parsed is not None else None
        except ValidationError:
            result = None
        if result is None:
            print(f"Warning: could not parse analysis response for {item.id}, using defaults")
            item.ai_score = 0.0
            item.ai_reason = "Analysis response parse failed"
            item.ai_summary = item.title
            item.ai_tags = []
            return

        # Update item with analysis results
        item.ai_score = result.score
        item.ai_reason = result.reason
        item.ai_summary = result.summary
        item.ai_tags = result.tags
        if result.category in self._allowed_category_set:
            source_category = item.metadata.get("category")
            if source_category != result.category:
                item.metadata.setdefault("source_category", source_category)
                item.metadata["category"] = result.category
