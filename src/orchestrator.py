"""Main orchestrator coordinating the entire workflow."""

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date as date_type, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Literal, Optional
from urllib.parse import unquote_plus, urlsplit
import httpx
from rich.console import Console

from .models import Config, ContentItem
from ._file_utils import _atomic_write_text
from .storage.manager import StorageManager, safe_output_path
from .services.email import EmailManager
from .services.telegram_delivery import (
    TelegramDeliveryStatus,
    TelegramEditionPublisher,
)
from .services.webhook import WebhookNotifier
from .services.x_delivery import XDeliveryStatus, XEditionPublisher
from .scrapers.github import GitHubScraper
from .scrapers.hackernews import HackerNewsScraper
from .scrapers.rss import RSSScraper
from .scrapers.reddit import RedditScraper
from .scrapers.telegram import TelegramScraper
from .scrapers.twitter import TwitterScraper
from .scrapers.twitter_playwright import TwitterPlaywrightScraper
from .scrapers.openbb import OpenBBScraper
from .scrapers.ossinsight import OSSInsightScraper
from .scrapers.gdelt import GDELTScraper
from .scrapers.google_news import GoogleNewsScraper
from .ai.client import create_ai_client
from .ai.analyzer import ContentAnalyzer
from .ai.summarizer import DailySummarizer, generate_edition_overviews
from .ai.enricher import ContentEnricher
from .ai.prefilter import ContentPrefilter
from .ai.result_cache import AnalysisResultCache, split_cached
from .ai.tokens import get_usage_snapshot, reset_usage
from .event_pipeline import (
    EVENT_CATALOG_PATH,
    known_story_assignments,
    load_event_catalog,
    load_legacy_event_urls,
    save_event_catalog,
    update_events,
)
from .daily_feed import (
    DailyFeedState,
    analyzed_item_key,
    item_identity,
    items_for_local_date,
    load_daily_feed_state,
    local_date_for,
    merge_daily_items,
    save_daily_feed_state,
)
from .edition import (
    DEFAULT_STAGING_PATH,
    edition_window_for,
    edition_window_for_date,
    items_in_edition_window,
    items_in_supplemental_window,
    load_staging_state,
    merge_staged_items,
    save_staging_state,
)
from .api_output import (
    build_edition_payload,
    write_category_feeds,
    write_edition_api,
    write_editions_index,
    write_sitemap,
)
from .archive import (
    ArchiveRecord,
    build_records,
    load_recent_archive,
    save_edition_records,
)
from .editorial import (
    EditorialEntry,
    editorial_content_item,
    load_editorial_plan,
)
from .market_snapshot import MarketSnapshot, fetch_market_snapshot
from .site_pages import publish_archive_pages, publish_event_compatibility_pages
from .threads import (
    assign_threads,
    collect_entities,
    collect_threads,
    fingerprint,
    same_thread,
)
from .run_report import RunReport, save_run_report
from .web_feed import _top_level_category, render_web_feed


_TRACKING_QUERY_PARAMETERS = {
    "_ga",
    "dclid",
    "fbclid",
    "gclid",
    "igshid",
    "li_fat_id",
    "mc_cid",
    "mc_eid",
    "msclkid",
    "ttclid",
    "twclid",
    "vero_id",
}


def _deduplication_url_key(url: str) -> tuple[str, str, str, str, Optional[int], str, str]:
    """Return a conservative URL identity key for cross-source deduplication."""
    parsed = urlsplit(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if (scheme, port) in {("http", 80), ("https", 443)}:
        port = None

    path = parsed.path.rstrip("/") or "/"
    query_parts = []
    for part in parsed.query.split("&") if parsed.query else []:
        name = unquote_plus(part.partition("=")[0]).lower()
        if name.startswith("utm_") or name in _TRACKING_QUERY_PARAMETERS:
            continue
        query_parts.append(part)

    return (
        scheme,
        parsed.username or "",
        parsed.password or "",
        host,
        port,
        path,
        "&".join(query_parts),
    )


@dataclass
class BalancedDigestResult:
    """Items and selection statistics from balanced digest filtering."""

    items: List[ContentItem]
    enabled: bool = False
    group_counts: Dict[str, int] = field(default_factory=dict)
    group_limits: Dict[str, Optional[int]] = field(default_factory=dict)
    duplicate_categories: List[str] = field(default_factory=list)
    borrowed_count: int = 0
    category_limit_deferred: int = 0
    source_limit_deferred: int = 0
    minimum_fill_count: int = 0


@dataclass
class FilteringPipelineResult:
    """Items and statistics from score, topic, and digest filtering."""

    items: List[ContentItem]
    threshold_count: int
    topic_dedup_count: int
    topic_dedup_removed: int
    balanced_digest: BalancedDigestResult


@dataclass
class SourceFetchOutcome:
    """Result of fetching one configured source."""

    source_name: str
    status: Literal["success", "empty", "failure"]
    items: List[ContentItem] = field(default_factory=list)
    subsource_counts: Dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        result: Dict[str, object] = {
            "source": self.source_name,
            "status": self.status,
            "item_count": len(self.items),
            "subsource_counts": dict(self.subsource_counts),
        }
        if self.error is not None:
            result["error"] = self.error
        return result


@dataclass
class FetchReport:
    """Aggregate diagnostics for one fetch across configured sources."""

    outcomes: List[SourceFetchOutcome] = field(default_factory=list)

    @property
    def status(self) -> Literal["not_attempted", "success", "partial_failure", "failure"]:
        if not self.outcomes:
            return "not_attempted"
        if self.failed_count == len(self.outcomes):
            return "failure"
        if self.failed_count:
            return "partial_failure"
        return "success"

    @property
    def failed_count(self) -> int:
        return sum(outcome.status == "failure" for outcome in self.outcomes)

    @property
    def all_failed(self) -> bool:
        return bool(self.outcomes) and self.failed_count == len(self.outcomes)

    def failure_message(self) -> str:
        failures = "; ".join(
            f"{outcome.source_name}: {outcome.error or 'unknown error'}"
            for outcome in self.outcomes
            if outcome.status == "failure"
        )
        return f"All {len(self.outcomes)} attempted sources failed ({failures})"

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "attempted": len(self.outcomes),
            "successful": len(self.outcomes) - self.failed_count,
            "empty": sum(outcome.status == "empty" for outcome in self.outcomes),
            "failed": self.failed_count,
            "item_count": sum(len(outcome.items) for outcome in self.outcomes),
            "sources": [outcome.to_dict() for outcome in self.outcomes],
        }


class BMTNewsOrchestrator:
    """Orchestrates the complete workflow for content aggregation and analysis."""

    def __init__(self, config: Config, storage: StorageManager):
        """Initialize orchestrator.

        Args:
            config: Application configuration
            storage: Storage manager
        """
        self.config = config
        self.storage = storage
        self.console = Console()
        self.email_manager = EmailManager(config.email, console=self.console) if config.email else None
        self.webhook_notifier = (
            WebhookNotifier(config.webhook, console=self.console)
            if config.webhook and config.webhook.enabled
            else None
        )
        self.telegram_publisher = (
            TelegramEditionPublisher(
                config.telegram_delivery,
                console=self.console,
            )
            if config.telegram_delivery and config.telegram_delivery.enabled
            else None
        )
        self.x_publisher = (
            XEditionPublisher(config.x_delivery, console=self.console)
            if config.x_delivery and config.x_delivery.enabled
            else None
        )
        self.last_fetch_report: Optional[FetchReport] = None
        self.last_run_report: Optional[RunReport] = None
        self._analysis_cache: AnalysisResultCache | None = None

    def _result_cache(self) -> AnalysisResultCache | None:
        if not self.config.ai.result_cache_enabled:
            return None
        if self._analysis_cache is None:
            self._analysis_cache = AnalysisResultCache(
                Path(self.config.ai.result_cache_path),
                model=f"{self.config.ai.provider.value}:{self.config.ai.model}",
                ttl_days=self.config.ai.result_cache_ttl_days,
                max_entries=self.config.ai.result_cache_max_entries,
            )
        return self._analysis_cache

    def _set_timing(self, name: str, started: float) -> None:
        if self.last_run_report is not None:
            self.last_run_report.add_timing(name, time.perf_counter() - started)

    async def run(self, force_hours: int = None) -> None:
        """Execute the complete workflow.

        Args:
            force_hours: Optional override for time window in hours
        """
        self.console.print("[bold cyan]🌅 BMTNews - Starting aggregation...[/bold cyan]\n")

        daily_timezone = getattr(self.config.filtering, "daily_timezone", "UTC")
        run_started_at = datetime.now(timezone.utc)
        today = local_date_for(run_started_at, daily_timezone)
        run_report = RunReport.start(
            date=today,
            timezone_name=daily_timezone,
            started_at=run_started_at,
        )
        self.last_run_report = run_report
        try:
            # Check email subscriptions if configured
            if (
                self.email_manager
                and self.config.email
                and self.config.email.enabled
                and self.config.email.imap_enabled
            ):
                self.console.print("📧 Checking for new email subscriptions...")
                self.email_manager.check_subscriptions(self.storage)

            # 1. Determine time window
            since = self._determine_time_window(force_hours)
            self.console.print(f"📅 Fetching content since: {since.strftime('%Y-%m-%d %H:%M:%S')}\n")

            # 2. Fetch content from all sources
            all_items = await self.fetch_all_sources(since)
            run_report.set_metric("fetched_raw", len(all_items))
            run_report.attach_fetch_report(
                self.last_fetch_report.to_dict()
                if self.last_fetch_report is not None
                else None
            )
            self.console.print(f"📥 Fetched {len(all_items)} items from all sources\n")

            if self.last_fetch_report and self.last_fetch_report.all_failed:
                raise RuntimeError(self.last_fetch_report.failure_message())

            if not all_items:
                run_report.add_alert(
                    "info",
                    "no_new_content",
                    "本次采集没有返回新内容。",
                )
                self.console.print("[yellow]No new content found. Exiting.[/yellow]")
                return

            # 3. Merge cross-source duplicates (same URL from different sources)
            merged_items = self.merge_cross_source_duplicates(all_items)
            run_report.set_metric("unique_after_url_dedup", len(merged_items))
            if len(merged_items) < len(all_items):
                self.console.print(
                    f"🔗 Merged {len(all_items) - len(merged_items)} cross-source duplicates "
                    f"→ {len(merged_items)} unique items\n"
                )

            daily_state: Optional[DailyFeedState] = None
            if getattr(self.config.filtering, "preserve_daily_items", False):
                daily_state = load_daily_feed_state(today, daily_timezone)
                before_daily_filter = len(merged_items)
                merged_items = items_for_local_date(
                    merged_items,
                    today,
                    daily_timezone,
                )
                run_report.set_metric("current_day_items", len(merged_items))
                self.console.print(
                    f"🗓️  Kept {len(merged_items)}/{before_daily_filter} items "
                    f"published on {today} ({daily_timezone})\n"
                )
                if not merged_items and not daily_state.items:
                    self.console.print(
                        "[yellow]No content published in the current local day. Exiting.[/yellow]"
                    )
                    return
                analyzed_keys = set(daily_state.analyzed_keys)
                before_incremental_filter = len(merged_items)
                merged_items = [
                    item
                    for item in merged_items
                    if analyzed_item_key(item) not in analyzed_keys
                ]
                skipped_count = before_incremental_filter - len(merged_items)
                run_report.set_metric(
                    "skipped_already_analyzed",
                    skipped_count,
                )
                if skipped_count:
                    self.console.print(
                        f"⏭️  Skipped {skipped_count} items already analyzed today; "
                        f"{len(merged_items)} new items remain\n"
                    )
            else:
                run_report.set_metric("current_day_items", len(merged_items))

            # 4. Analyze with AI
            analyzed_items = (
                await self._analyze_content(merged_items)
                if merged_items
                else []
            )
            run_report.set_metric("analyzed_this_run", len(analyzed_items))
            self.console.print(f"🤖 Analyzed {len(analyzed_items)} items with AI\n")

            # 5. Filter, deduplicate, and balance the digest
            filtering_result = await self.filter_items(
                analyzed_items,
                apply_balance=False,
                dedup_context=(
                    [*daily_state.dedup_history, *daily_state.items]
                    if daily_state is not None
                    else None
                ),
            )
            important_items = filtering_result.items
            run_report.set_metric(
                "above_threshold",
                filtering_result.threshold_count,
            )
            run_report.set_metric(
                "topic_duplicates_removed",
                filtering_result.topic_dedup_removed,
            )

            # 5.5 Optional second-stage Twitter reply expansion + targeted re-analysis
            await self._expand_twitter_discussion(important_items)

            # 5.6 Apply digest limits after any targeted re-analysis changes scores.
            balanced_result = self.apply_balanced_digest(important_items)
            important_items = balanced_result.items
            run_report.set_metric(
                "balanced_digest_removed",
                filtering_result.topic_dedup_count - len(important_items),
            )

            # Show per-sub-source selection breakdown
            selected_counts: Dict[str, int] = defaultdict(int)
            for item in important_items:
                key = f"{item.source_type.value}/{self._sub_source_label(item)}"
                selected_counts[key] += 1
            for source_key, count in sorted(selected_counts.items()):
                self.console.print(f"      • {source_key}: {count}")
            self.console.print("")

            # 6. Search related stories + enrich with background knowledge (2nd AI pass)
            await self._enrich_important_items(important_items)

            analyzed_count = len(all_items)
            existing_display_identities: set[str] = set()
            if daily_state is not None:
                existing_display_identities = {
                    item_identity(item) for item in daily_state.items
                }
                important_items = merge_daily_items(
                    daily_state.items,
                    important_items,
                    today,
                    daily_timezone,
                )
                important_items = self.apply_balanced_digest(
                    important_items,
                    log=False,
                ).items
                daily_state.items = important_items
                daily_state.updated_at = run_started_at
                daily_state.analyzed_keys = sorted(
                    set(daily_state.analyzed_keys)
                    | {analyzed_item_key(item) for item in analyzed_items}
                )
                analyzed_count = len(daily_state.analyzed_keys)
                state_path = save_daily_feed_state(daily_state)
                self.console.print(
                    f"🧩 Retained {len(important_items)} selected items for {today}; "
                    f"saved state to {state_path}\n"
                )

            displayed_identities = {
                item_identity(item) for item in important_items
            }
            run_report.set_metric(
                "analyzed_today",
                analyzed_count if daily_state is not None else len(analyzed_items),
            )
            run_report.set_metric(
                "newly_displayed",
                len(displayed_identities - existing_display_identities),
            )
            run_report.set_metric("displayed_today", len(important_items))
            run_report.set_metric(
                "high_priority",
                sum((item.ai_score or 0) >= 9 for item in important_items),
            )
            if analyzed_items and not (
                displayed_identities - existing_display_identities
            ):
                run_report.add_alert(
                    "info",
                    "no_new_displayed_items",
                    "本次完成了 AI 分析，但没有新增条目进入页面展示。",
                )

            # 7. Generate and save daily summaries for each configured language
            await self._publish_outputs(
                important_items,
                date=today,
                total_candidates=analyzed_count,
                timezone_name=daily_timezone,
                run_report=run_report,
            )

            self.console.print("[bold green]✅ BMTNews completed successfully![/bold green]")
            usage = get_usage_snapshot()
            if usage.total_tokens > 0:
                self.console.print(
                    f"\n🧮 Token usage this run: "
                    f"{usage.total_tokens} tokens "
                    f"(input: {usage.total_input_tokens}, output: {usage.total_output_tokens})"
                )
                for provider, u in sorted(usage.per_provider.items()):
                    if u.total <= 0:
                        continue
                    self.console.print(
                        f"   • {provider}: {u.total} tokens "
                        f"(in: {u.input_tokens}, out: {u.output_tokens})"
                    )

        except Exception as e:
            run_report.fail(e)
            self.console.print(f"[bold red]❌ Error: {e}[/bold red]")

            # Send webhook failure notification if configured
            if self.webhook_notifier:
                await self.webhook_notifier.send_failure(
                    date=local_date_for(
                        datetime.now(timezone.utc),
                        daily_timezone,
                    ),
                    error_message=str(e),
                )

            raise
        finally:
            run_report.finish()
            try:
                report_path = save_run_report(run_report)
                self.console.print(f"\n📊 Saved run report to: {report_path}")
            except Exception as report_error:
                self.console.print(
                    f"[red]❌ Failed to save run report: {report_error}[/red]"
                )
                if run_report.status != "failure":
                    raise

    async def fetch_to_staging(
        self,
        force_hours: int | None = None,
        *,
        staging_path: Path = DEFAULT_STAGING_PATH,
        now: datetime | None = None,
    ) -> None:
        """Fetch source items and increment only the published event catalog.

        The daily edition boundary is unchanged.  When a migrated event
        catalog has been restored by the scheduled workflow, only genuinely
        new staged items are analyzed and considered for event updates.
        """
        timezone_name = self.config.filtering.daily_timezone
        run_started_at = now or datetime.now(timezone.utc)
        if run_started_at.tzinfo is None:
            run_started_at = run_started_at.replace(tzinfo=timezone.utc)
        run_report = RunReport.start(
            date=local_date_for(run_started_at, timezone_name),
            timezone_name=timezone_name,
            started_at=run_started_at,
            kind="staging_fetch",
        )
        self.last_run_report = run_report
        self.console.print(
            "[bold cyan]📥 BMTNews - Collecting items for the daily edition...[/bold cyan]\n"
        )

        try:
            hours = force_hours or self.config.filtering.time_window_hours
            since = run_started_at - timedelta(hours=hours)
            all_items = await self.fetch_all_sources(since)
            run_report.set_metric("fetched_raw", len(all_items))
            run_report.attach_fetch_report(
                self.last_fetch_report.to_dict()
                if self.last_fetch_report is not None
                else None
            )
            if self.last_fetch_report and self.last_fetch_report.all_failed:
                raise RuntimeError(self.last_fetch_report.failure_message())

            merged_items = self.merge_cross_source_duplicates(all_items)
            run_report.set_metric("unique_after_url_dedup", len(merged_items))
            staging_state = load_staging_state(staging_path)
            existing_identities = {
                item_identity(item) for item in staging_state.items
            }
            staged_items = merge_staged_items(
                staging_state.items,
                merged_items,
                now=run_started_at,
            )
            staged_identities = {
                item_identity(item) for item in staged_items
            }
            added_identities = staged_identities - existing_identities
            staged_added = len(added_identities)
            run_report.set_metric(
                "staged_added",
                staged_added,
            )
            run_report.set_metric("staged_total", len(staged_items))
            if EVENT_CATALOG_PATH.exists() and added_identities:
                new_items = [
                    item
                    for item in staged_items
                    if item_identity(item) in added_identities
                ]
                analyzed = await self._analyze_content(new_items)
                qualified = [
                    item
                    for item in analyzed
                    if item.ai_score is not None
                    and item.ai_score >= self.config.filtering.ai_score_threshold
                ]
                run_report.set_metric("event_analyzed", len(analyzed))
                run_report.set_metric("event_qualified", len(qualified))
                await self._update_event_timeline(qualified, run_report=run_report)
            # Commit the incoming staging batch only after event processing
            # succeeds. A failed classification run is therefore refetched,
            # not silently marked old and skipped forever.
            save_staging_state(
                staged_items,
                staging_path,
                updated_at=run_started_at,
            )
            self.console.print(
                f"✅ Added {staged_added} new unique items; "
                f"{len(staged_items)} retained in {staging_path}"
            )
        except Exception as exc:
            run_report.fail(exc)
            self.console.print(f"[bold red]❌ Collection failed: {exc}[/bold red]")
            raise
        finally:
            run_report.finish()
            save_run_report(run_report)

    async def run_daily_edition(
        self,
        force_hours: int | None = None,
        *,
        staging_path: Path = DEFAULT_STAGING_PATH,
        cutoff_hour: int = 8,
        edition_date: date_type | None = None,
        now: datetime | None = None,
        force_publish: bool = False,
    ) -> None:
        """Build one edition from the latest completed fixed cutoff window."""
        reset_usage()
        timezone_name = self.config.filtering.daily_timezone
        run_started_at = now or datetime.now(timezone.utc)
        if run_started_at.tzinfo is None:
            run_started_at = run_started_at.replace(tzinfo=timezone.utc)
        window = (
            edition_window_for_date(
                edition_date,
                timezone_name,
                cutoff_hour,
            )
            if edition_date is not None
            else edition_window_for(
                run_started_at,
                timezone_name,
                cutoff_hour,
            )
        )
        if (
            edition_date is not None
            and window.end.astimezone(timezone.utc)
            > run_started_at.astimezone(timezone.utc)
        ):
            raise ValueError(
                "edition_date cutoff has not completed in the configured timezone"
            )
        run_report = RunReport.start(
            date=window.date,
            timezone_name=timezone_name,
            started_at=run_started_at,
            kind="daily_publish",
            window_start=window.start,
            window_end=window.end,
        )
        cutoff_lag_minutes = max(
            0,
            int(
                (
                    run_started_at.astimezone(timezone.utc)
                    - window.end.astimezone(timezone.utc)
                ).total_seconds()
                // 60
            ),
        )
        run_report.set_metric("cutoff_lag_minutes", cutoff_lag_minutes)
        if cutoff_lag_minutes > 60:
            run_report.add_alert(
                "warning",
                "edition_started_late",
                f"日报在固定截止时间后 {cutoff_lag_minutes} 分钟才开始运行。",
            )
        self.last_run_report = run_report
        self.console.print(
            "[bold cyan]🗞️ BMTNews - Building the daily edition...[/bold cyan]\n"
        )
        self.console.print(
            f"🕗 Edition window: {window.start.isoformat()} "
            f"→ {window.end.isoformat()} (end exclusive)\n"
        )

        try:
            daily_state = load_daily_feed_state(
                window.date,
                timezone_name,
            )
            already_published = (
                daily_state.items
                and daily_state.updated_at.astimezone(timezone.utc)
                >= window.end.astimezone(timezone.utc)
            )
            if already_published and not force_publish:
                run_report.set_metric(
                    "displayed_today",
                    len(daily_state.items),
                )
                run_report.add_alert(
                    "info",
                    "edition_already_published",
                    "本期日报已经发布；跳过重复采集、AI 分析和页面生成。",
                )
                self.console.print(
                    "[green]This edition is already published; "
                    "skipping the duplicate run.[/green]"
                )
                return

            staging_exists = staging_path.exists()
            staging_state = load_staging_state(staging_path)
            run_report.set_metric(
                "staging_items_before",
                len(staging_state.items),
            )
            if not staging_exists:
                run_report.add_alert(
                    "warning",
                    "staging_cache_missing",
                    "未找到日内暂存缓存，日报将只使用最终补采结果。",
                )
            else:
                staging_age_minutes = max(
                    0,
                    int(
                        (
                            run_started_at.astimezone(timezone.utc)
                            - staging_state.updated_at.astimezone(timezone.utc)
                        ).total_seconds()
                        // 60
                    ),
                )
                run_report.set_metric(
                    "staging_age_minutes",
                    staging_age_minutes,
                )
                if staging_age_minutes > 14 * 60:
                    run_report.add_alert(
                        "warning",
                        "staging_cache_stale",
                        f"日内暂存缓存已 {staging_age_minutes} 分钟未更新。",
                    )
            filtering_config = self.config.filtering
            hours = force_hours or filtering_config.time_window_hours
            fallback_hours = filtering_config.fallback_window_hours
            fetch_hours = max(hours, fallback_hours or hours)
            fallback_start = (
                window.end.astimezone(timezone.utc)
                - timedelta(hours=fallback_hours)
                if fallback_hours is not None
                else window.start.astimezone(timezone.utc)
            )
            since = min(
                run_started_at - timedelta(hours=fetch_hours),
                fallback_start,
            )
            fetch_started = time.perf_counter()
            fresh_items = await self.fetch_all_sources(since)
            run_report.set_timing("fetch", time.perf_counter() - fetch_started)
            run_report.set_metric("fetched_raw", len(fresh_items))
            run_report.attach_fetch_report(
                self.last_fetch_report.to_dict()
                if self.last_fetch_report is not None
                else None
            )
            fresh_items = self.merge_cross_source_duplicates(fresh_items)
            fresh_identities = {
                item_identity(item) for item in fresh_items
            }
            run_report.set_metric(
                "unique_after_url_dedup",
                len(fresh_items),
            )
            staged_items = merge_staged_items(
                staging_state.items,
                fresh_items,
                now=run_started_at,
            )
            save_staging_state(
                staged_items,
                staging_path,
                updated_at=run_started_at,
            )
            run_report.set_metric("staged_total", len(staged_items))

            editorial_plan = load_editorial_plan(
                date_type.fromisoformat(window.date)
            )
            suppressed_keys = {
                _deduplication_url_key(url)
                for url in editorial_plan.suppressed_urls
            }

            candidates = self.merge_cross_source_duplicates(
                items_in_edition_window(staged_items, window)
            )
            if suppressed_keys:
                before_suppress = len(candidates)
                candidates = [
                    item
                    for item in candidates
                    if _deduplication_url_key(str(item.url))
                    not in suppressed_keys
                ]
                if before_suppress != len(candidates):
                    run_report.set_metric(
                        "suppressed_manual",
                        before_suppress - len(candidates),
                    )
            run_report.set_metric(
                "staging_only_candidates",
                sum(
                    item_identity(item) not in fresh_identities
                    for item in candidates
                ),
            )
            run_report.set_metric("edition_candidates", len(candidates))
            run_report.set_metric("current_day_items", len(candidates))
            candidate_source_counts: Dict[str, int] = defaultdict(int)
            for item in candidates:
                source_key = (
                    f"{item.source_type.value}/"
                    f"{self._sub_source_label(item)}"
                )
                candidate_source_counts[source_key] += 1
            run_report.set_breakdown(
                "candidate_sources",
                dict(sorted(candidate_source_counts.items())),
            )
            run_report.set_breakdown(
                "candidate_groups",
                self._group_breakdown(candidates),
            )
            minimum_candidates = filtering_config.minimum_candidate_items
            if (
                minimum_candidates is not None
                and len(candidates) < minimum_candidates
            ):
                run_report.add_alert(
                    "warning",
                    "candidate_shortage",
                    f"固定 24 小时候选只有 {len(candidates)}/"
                    f"{minimum_candidates} 条，已记录来源供给不足。",
                )
            self.console.print(
                f"📚 {len(candidates)} unique candidates fall inside this edition\n"
            )

            supplemental_candidates = (
                self.merge_cross_source_duplicates(
                    items_in_supplemental_window(
                        staged_items,
                        window,
                        fallback_hours,
                    )
                )
                if fallback_hours is not None
                else []
            )
            if suppressed_keys:
                supplemental_candidates = [
                    item
                    for item in supplemental_candidates
                    if _deduplication_url_key(str(item.url))
                    not in suppressed_keys
                ]

            final_fetch_failed = bool(
                self.last_fetch_report
                and self.last_fetch_report.all_failed
            )
            if (
                final_fetch_failed
                and not candidates
                and not supplemental_candidates
            ):
                if daily_state.items:
                    run_report.add_alert(
                        "warning",
                        "edition_retry_preserved",
                        "最终采集失败且无可用候选，保留已发布的本期内容。",
                    )
                    self.console.print(
                        "[yellow]No recoverable candidates; preserving the "
                        "already-published edition.[/yellow]"
                    )
                    return
                raise RuntimeError(self.last_fetch_report.failure_message())
            if final_fetch_failed:
                run_report.add_alert(
                    "warning",
                    "final_fetch_failed_using_staging",
                    "最终采集全部失败，已使用当日早前暂存内容继续出刊。",
                )
            if not candidates and not supplemental_candidates and daily_state.items:
                run_report.add_alert(
                    "info",
                    "edition_retry_preserved",
                    "本次没有恢复到候选内容，保留已发布的本期内容。",
                )
                self.console.print(
                    "[yellow]No candidates recovered; preserving the "
                    "already-published edition.[/yellow]"
                )
                return

            published_identities = {
                item_identity(item) for item in daily_state.dedup_history
            }
            before_history_filter = len(candidates)
            candidates = [
                item
                for item in candidates
                if item_identity(item) not in published_identities
            ]
            run_report.set_metric(
                "skipped_published_history",
                before_history_filter - len(candidates),
            )

            total_candidates_considered = before_history_filter
            analyzed_items = (
                await self._analyze_content(candidates)
                if candidates
                else []
            )

            filtering_result = await self.filter_items(
                analyzed_items,
                apply_balance=False,
                dedup_context=daily_state.dedup_history,
            )
            qualified_items = filtering_result.items
            threshold_count = filtering_result.threshold_count
            topic_duplicates_removed = filtering_result.topic_dedup_removed

            await self._expand_twitter_discussion(qualified_items)
            balanced_result = self.apply_balanced_digest(
                qualified_items,
                log=False,
            )
            minimum_display = filtering_config.minimum_display_items
            if (
                minimum_display is not None
                and len(balanced_result.items) < minimum_display
            ):
                balanced_result = self.apply_balanced_digest(
                    qualified_items,
                    allow_primary_borrowing=True,
                )

            fallback_used = bool(
                fallback_hours is not None
                and minimum_display is not None
                and len(balanced_result.items) < minimum_display
            )
            if fallback_used:
                total_candidates_considered += len(supplemental_candidates)
                run_report.set_metric(
                    "fallback_candidates",
                    len(supplemental_candidates),
                )
                fallback_source_counts: Dict[str, int] = defaultdict(int)
                for item in supplemental_candidates:
                    source_key = (
                        f"{item.source_type.value}/"
                        f"{self._sub_source_label(item)}"
                    )
                    fallback_source_counts[source_key] += 1
                run_report.set_breakdown(
                    "fallback_candidate_sources",
                    dict(sorted(fallback_source_counts.items())),
                )
                run_report.set_breakdown(
                    "fallback_candidate_groups",
                    self._group_breakdown(supplemental_candidates),
                )
                normal_identities = {
                    item_identity(item) for item in candidates
                }
                fallback_before_history = len(supplemental_candidates)
                supplemental_candidates = [
                    item
                    for item in supplemental_candidates
                    if item_identity(item) not in published_identities
                    and item_identity(item) not in normal_identities
                ]
                run_report.set_metric(
                    "skipped_published_history",
                    run_report.metrics.get("skipped_published_history", 0)
                    + fallback_before_history
                    - len(supplemental_candidates),
                )
                fallback_analyzed = (
                    await self._analyze_content(supplemental_candidates)
                    if supplemental_candidates
                    else []
                )
                analyzed_items.extend(fallback_analyzed)
                run_report.set_metric(
                    "fallback_analyzed",
                    len(fallback_analyzed),
                )
                fallback_filtering = await self.filter_items(
                    fallback_analyzed,
                    apply_balance=False,
                    dedup_context=[
                        *daily_state.dedup_history,
                        *qualified_items,
                    ],
                )
                threshold_count += fallback_filtering.threshold_count
                topic_duplicates_removed += (
                    fallback_filtering.topic_dedup_removed
                )
                fallback_qualified = fallback_filtering.items
                await self._expand_twitter_discussion(fallback_qualified)
                qualified_items = [*qualified_items, *fallback_qualified]
                balanced_result = self.apply_balanced_digest(
                    qualified_items,
                    allow_primary_borrowing=True,
                    fill_to_minimum=True,
                )
                run_report.add_alert(
                    "info",
                    "fallback_window_used",
                    f"固定窗口内容不足，已启用 {fallback_hours} 小时未发布内容保底；"
                    "评分阈值和历史去重保持不变。",
                )
            elif (
                minimum_display is not None
                and len(balanced_result.items) < minimum_display
            ):
                balanced_result = self.apply_balanced_digest(
                    qualified_items,
                    allow_primary_borrowing=True,
                    fill_to_minimum=True,
                )

            important_items = balanced_result.items
            low_signal_minimum = filtering_config.low_signal_minimum_items
            if (
                not important_items
                and analyzed_items
                and low_signal_minimum is not None
            ):
                important_items = self._rescue_low_signal_items(
                    analyzed_items,
                    limit=low_signal_minimum,
                )
                if important_items:
                    run_report.set_metric(
                        "low_signal_rescued",
                        len(important_items),
                    )
                    run_report.add_alert(
                        "warning",
                        "low_signal_edition",
                        f"没有内容达到 {filtering_config.ai_score_threshold:g} 分阈值；"
                        f"已按分数保底选取 {len(important_items)} 条发布，避免出空刊。",
                    )
                    self.console.print(
                        "[yellow]⚠️  Low-signal day: publishing the "
                        f"{len(important_items)} highest-scored items instead "
                        "of an empty edition.[/yellow]"
                    )
            run_report.set_metric("analyzed_this_run", len(analyzed_items))
            run_report.set_metric("analyzed_today", len(analyzed_items))
            run_report.set_metric("above_threshold", threshold_count)
            run_report.set_metric(
                "below_threshold",
                len(analyzed_items) - threshold_count,
            )
            run_report.set_metric(
                "topic_duplicates_removed",
                topic_duplicates_removed,
            )
            run_report.set_metric(
                "qualified_after_topic_dedup",
                len(qualified_items),
            )
            run_report.set_metric(
                "category_reclassified",
                sum(
                    item.metadata.get("source_category")
                    != item.metadata.get("category")
                    for item in analyzed_items
                    if "source_category" in item.metadata
                ),
            )
            run_report.set_metric(
                "quota_borrowed",
                balanced_result.borrowed_count,
            )
            run_report.set_metric(
                "category_limit_deferred",
                balanced_result.category_limit_deferred,
            )
            run_report.set_metric(
                "source_limit_deferred",
                balanced_result.source_limit_deferred,
            )
            run_report.set_metric(
                "minimum_fill_added",
                balanced_result.minimum_fill_count,
            )
            run_report.set_metric(
                "balanced_digest_removed",
                len(qualified_items) - len(important_items),
            )
            minimum_qualified = filtering_config.minimum_qualified_items
            if (
                minimum_qualified is not None
                and threshold_count < minimum_qualified
            ):
                run_report.add_alert(
                    "warning",
                    "qualified_content_shortage",
                    f"达到 {filtering_config.ai_score_threshold:g} 分的内容只有 "
                    f"{threshold_count}/{minimum_qualified} 条；未降低评分阈值。",
                )
            if (
                minimum_display is not None
                and len(important_items) < minimum_display
            ):
                run_report.add_alert(
                    "warning",
                    "short_edition",
                    f"本期最终只有 {len(important_items)}/{minimum_display} 条；"
                    "已发布短版，未复用历史内容或降低评分阈值。",
                )
            group_labels = {
                key: group.name or key
                for key, group in self.config.filtering.category_groups.items()
            }
            selected_groups = {
                group_labels.get(key, key): count
                for key, count in balanced_result.group_counts.items()
            }
            group_limits = {
                group_labels.get(key, key): limit
                for key, limit in balanced_result.group_limits.items()
                if limit is not None
            }
            run_report.set_breakdown("selected_groups", selected_groups)
            run_report.set_breakdown("group_limits", group_limits)
            run_report.set_breakdown(
                "qualified_groups",
                self._group_breakdown(qualified_items),
            )

            primary_groups = set(self.config.filtering.primary_groups)
            primary_selected = sum(
                balanced_result.group_counts.get(group, 0)
                for group in primary_groups
            )
            primary_required = (
                self.config.filtering.primary_group_min_items or 0
            )
            run_report.set_metric("primary_selected", primary_selected)
            run_report.set_metric("primary_required", primary_required)
            if primary_selected < primary_required:
                run_report.add_alert(
                    "warning",
                    "primary_quota_shortfall",
                    "Crypto 主轨只有 "
                    f"{primary_selected}/{primary_required} 条合格内容；"
                    "未用低分内容强行补足。",
                )

            selected_source_counts: Dict[str, int] = defaultdict(int)
            for item in important_items:
                source_key = (
                    f"{item.source_type.value}/"
                    f"{self._sub_source_label(item)}"
                )
                selected_source_counts[source_key] += 1
            run_report.set_breakdown(
                "selected_sources",
                dict(sorted(selected_source_counts.items())),
            )
            run_report.set_breakdown(
                "qualified_sources",
                self._source_breakdown(qualified_items),
            )
            await self._enrich_important_items(important_items)

            # Manual editor's picks are pinned ahead of the ranked stories.
            if editorial_plan.editorial:
                existing_urls = {
                    _deduplication_url_key(str(item.url))
                    for item in important_items
                }
                picks = []
                for entry in editorial_plan.editorial:
                    try:
                        pick = editorial_content_item(
                            entry,
                            date_type.fromisoformat(window.date),
                        )
                    except Exception as exc:
                        run_report.add_alert(
                            "warning",
                            "editorial_item_invalid",
                            f"编辑条目无效，已跳过：{exc}",
                        )
                        continue
                    if _deduplication_url_key(str(pick.url)) in existing_urls:
                        continue
                    picks.append(pick)
                if picks:
                    important_items = [*picks, *important_items]
                    run_report.set_metric("editorial_items", len(picks))
                    run_report.add_alert(
                        "info",
                        "editorial_items_added",
                        f"人工插入 {len(picks)} 条编辑精选。",
                    )
            if editorial_plan.sponsored:
                run_report.set_metric(
                    "sponsored_slots",
                    min(1, len(editorial_plan.sponsored)),
                )

            # Event membership is assigned before rendering and archiving so
            # both the human page and edition JSON point to the exact update.
            await self._update_event_timeline(
                important_items,
                run_report=run_report,
            )

            # Link continuing coverage to its thread before anything renders.
            self._apply_threads(important_items, edition_date=window.date)
            run_report.set_metric(
                "thread_continuations",
                sum(
                    1
                    for item in important_items
                    if (item.metadata.get("thread_day") or 1) > 1
                ),
            )

            existing_display_identities = {
                item_identity(item) for item in daily_state.items
            }
            daily_state.items = important_items
            daily_state.updated_at = run_started_at
            daily_state.analyzed_keys = sorted(
                analyzed_item_key(item) for item in analyzed_items
            )
            state_path = save_daily_feed_state(daily_state)
            self.console.print(
                f"🧩 Saved {len(important_items)} selected items to {state_path}\n"
            )

            displayed_identities = {
                item_identity(item) for item in important_items
            }
            run_report.set_metric(
                "newly_displayed",
                len(displayed_identities - existing_display_identities),
            )
            run_report.set_metric("displayed_today", len(important_items))
            run_report.set_metric(
                "high_priority",
                sum((item.ai_score or 0) >= 9 for item in important_items),
            )

            published = await self._publish_outputs(
                important_items,
                date=window.date,
                total_candidates=total_candidates_considered,
                timezone_name=timezone_name,
                run_report=run_report,
                window_start=window.start,
                window_end=window.end,
                sponsored=editorial_plan.sponsored,
                x_posted_languages=daily_state.x_posted_languages,
            )
            newly_posted = published.get("x_posted") or []
            if newly_posted:
                daily_state.x_posted_languages = sorted(
                    {*daily_state.x_posted_languages, *newly_posted}
                )
                save_daily_feed_state(daily_state)
            archive_started = time.perf_counter()
            self._publish_archive_artifacts(
                important_items,
                date=window.date,
                run_report=run_report,
                window_start=window.start,
                window_end=window.end,
                market=published.get("market"),
                overviews=published.get("overviews"),
            )
            # Legacy archive generation also writes the old thread index.
            # Re-render from the authoritative event catalog last so /threads/
            # always represents real event progression.
            self._publish_current_event_pages()
            run_report.set_timing(
                "archive_artifacts", time.perf_counter() - archive_started
            )
            self.console.print(
                "[bold green]✅ Daily edition completed successfully![/bold green]"
            )
        except Exception as exc:
            run_report.fail(exc)
            self.console.print(f"[bold red]❌ Edition failed: {exc}[/bold red]")
            if self.webhook_notifier:
                await self.webhook_notifier.send_failure(
                    date=window.date,
                    error_message=str(exc),
                )
            raise
        finally:
            usage = get_usage_snapshot()
            run_report.set_metric("ai_input_tokens", usage.total_input_tokens)
            run_report.set_metric("ai_output_tokens", usage.total_output_tokens)
            run_report.set_metric("ai_total_tokens", usage.total_tokens)
            cache = self._result_cache()
            if cache is not None:
                cache.save()
                run_report.set_metric("analysis_cache_entries", len(cache.entries))
            run_report.finish()
            save_run_report(run_report)

    async def run_x_slot(
        self,
        *,
        edition_date: date_type | None = None,
        kickoff_only: bool = False,
        now: datetime | None = None,
        state_path: Path | None = None,
    ) -> None:
        """Post the next pending story of the current edition to X.

        Called once per scheduled slot or immediately after publication.
        Posting is ordered rather than clock-matched, so a delayed or skipped
        slot shifts a story later instead of dropping or duplicating it. A
        kickoff-only call starts an untouched edition but never advances one
        whose queue has already begun.
        """
        from .services.x_delivery import build_story_post, compose_story_post
        from .x_queue import (
            DEFAULT_STATE_PATH,
            load_queue_state,
            next_pending_rank,
            save_queue_state,
            state_for_edition,
        )

        config = self.config.x_delivery
        timezone_name = self.config.filtering.daily_timezone
        run_started_at = now or datetime.now(timezone.utc)
        if run_started_at.tzinfo is None:
            run_started_at = run_started_at.replace(tzinfo=timezone.utc)
        date_str = (
            edition_date.isoformat()
            if edition_date is not None
            else local_date_for(run_started_at, timezone_name)
        )
        run_report = RunReport.start(
            date=date_str,
            timezone_name=timezone_name,
            started_at=run_started_at,
            kind="x_slot",
        )
        self.last_run_report = run_report
        path = state_path or DEFAULT_STATE_PATH

        try:
            publisher = getattr(self, "x_publisher", None)
            if not publisher or not config or not config.enabled:
                run_report.add_alert(
                    "info",
                    "x_slot_disabled",
                    "X 分发未启用，本次不发布。",
                )
                self.console.print("[yellow]X delivery is disabled.[/yellow]")
                return
            if config.mode != "drip":
                run_report.add_alert(
                    "info",
                    "x_slot_not_drip",
                    "X 分发处于 digest 模式，分时发布任务不执行。",
                )
                return

            daily_state = load_daily_feed_state(date_str, timezone_name)
            items = daily_state.items
            if not items:
                run_report.add_alert(
                    "info",
                    "x_slot_no_edition",
                    f"{date_str} 尚无已发布日报，跳过本时段。",
                )
                self.console.print(
                    f"[yellow]No published edition for {date_str}; nothing to post.[/yellow]"
                )
                return

            state = state_for_edition(load_queue_state(path), date_str)
            for language in config.languages:
                if kickoff_only and state.posted_ranks(language):
                    run_report.add_alert(
                        "info",
                        f"x_kickoff_already_started_{language}",
                        (
                            f"{date_str} 的 {language.upper()} 分时发布已启动，"
                            "本次发布后触发不再推进队列。"
                        ),
                    )
                    continue
                rank = next_pending_rank(
                    state,
                    language=language,
                    total_items=len(items),
                    limit=config.drip_items,
                )
                if rank is None:
                    run_report.add_alert(
                        "info",
                        f"x_slot_complete_{language}",
                        f"{date_str} 的 {language.upper()} 分时发布已全部完成。",
                    )
                    continue

                item = items[rank - 1]
                text = None
                if config.compose == "ai":
                    try:
                        text = await compose_story_post(
                            create_ai_client(self.config.ai),
                            item,
                            language=language,
                            limit=config.max_post_chars,
                        )
                    except Exception as exc:
                        self.console.print(
                            f"[yellow]⚠️  X composer unavailable: {exc}[/yellow]"
                        )
                    if text is None:
                        run_report.add_alert(
                            "info",
                            "x_compose_fallback",
                            "X 文案生成失败或不合格，已回落到模板拼装。",
                        )
                if text is None:
                    text = build_story_post(
                        item,
                        language=language,
                        site_url=config.site_url,
                        link_target=config.link_target,
                        limit=config.max_post_chars,
                        edition_date=date_str,
                    )
                result = await publisher.send_text(text)
                if result.status == XDeliveryStatus.SUCCESS:
                    state.mark_posted(language, rank)
                    save_queue_state(state, path)
                    run_report.set_metric(
                        "x_posts_sent",
                        run_report.metrics.get("x_posts_sent", 0) + 1,
                    )
                    run_report.set_metric("x_slot_rank", rank)
                    self.console.print(
                        f"🐦 Posted #{rank} of {date_str} ({language}) to X"
                    )
                elif result.status == XDeliveryStatus.SKIPPED:
                    run_report.add_alert(
                        "info",
                        "x_slot_skipped",
                        f"X 分时发布跳过：{result.detail}",
                    )
                else:
                    run_report.add_alert(
                        "warning",
                        "x_slot_failed",
                        result.detail,
                    )
                    if config.required:
                        raise RuntimeError(result.detail)
        except Exception as exc:
            run_report.fail(exc)
            self.console.print(f"[bold red]❌ X slot failed: {exc}[/bold red]")
            raise
        finally:
            run_report.finish()
            save_run_report(run_report)

    async def run_weekly_review(
        self,
        *,
        end_date: date_type | None = None,
        now: datetime | None = None,
        days: int = 7,
    ) -> None:
        """Publish the weekly digest and the scoring calibration review."""
        from .weekly import (
            build_weekly_context,
            generate_calibration_review,
            generate_weekly_digest,
            known_weeks,
            render_weekly_page,
            save_calibration_review,
            save_weekly_page,
            save_weeks_index_data,
        )

        timezone_name = self.config.filtering.daily_timezone
        run_started_at = now or datetime.now(timezone.utc)
        if run_started_at.tzinfo is None:
            run_started_at = run_started_at.replace(tzinfo=timezone.utc)
        end = end_date or date_type.fromisoformat(
            local_date_for(run_started_at, timezone_name)
        )
        run_report = RunReport.start(
            date=end.isoformat(),
            timezone_name=timezone_name,
            started_at=run_started_at,
            kind="weekly_review",
        )
        self.last_run_report = run_report
        self.console.print(
            "[bold cyan]🗓️ BMTNews - Building the weekly review...[/bold cyan]\n"
        )

        try:
            history = load_recent_archive(days * 2, today=end)
            context = build_weekly_context(history, end=end, days=days)
            run_report.set_metric("weekly_records", len(context.records))
            run_report.set_metric("weekly_threads", len(context.threads))
            if context.is_empty:
                run_report.add_alert(
                    "info",
                    "weekly_archive_empty",
                    "归档中没有本周内容，跳过周报生成。",
                )
                self.console.print(
                    "[yellow]No archived stories for this week; nothing to do.[/yellow]"
                )
                return

            ai_client = create_ai_client(self.config.ai)
            languages = list(self.config.ai.languages) or ["zh"]
            published_any = False
            first_failure: Exception | None = None
            for language in languages:
                normalized = (
                    "en" if str(language).lower().startswith("en") else "zh"
                )
                try:
                    body = await generate_weekly_digest(
                        ai_client,
                        context,
                        language=normalized,
                    )
                except Exception as exc:  # noqa: BLE001 - reported, not hidden
                    first_failure = first_failure or exc
                    body = None
                    detail = f"{normalized.upper()} 周报生成失败：{exc}"
                else:
                    detail = f"{normalized.upper()} 周报生成失败：模型未返回内容。"
                if not body:
                    # Carrying the provider's own message is the whole point:
                    # a generic "生成失败" is what made a 400 indistinguishable
                    # from a quiet model for two weeks. Alert text is passed
                    # through sanitize_diagnostic before it is written out.
                    run_report.add_alert(
                        "warning",
                        f"weekly_digest_failed_{normalized}",
                        detail,
                    )
                    continue
                path = save_weekly_page(
                    render_weekly_page(body, context, language=normalized),
                    end=end,
                    language=normalized,
                )
                published_any = True
                self.console.print(f"📝 Saved {normalized.upper()} weekly review to {path}")

            if published_any:
                weeks = sorted({*known_weeks(), end.isoformat()}, reverse=True)
                save_weeks_index_data(weeks)
                run_report.set_metric("weekly_pages", len(languages))

            try:
                calibration = await generate_calibration_review(
                    ai_client,
                    context,
                    high_threshold=max(
                        8.0, self.config.filtering.ai_score_threshold + 1.0
                    ),
                )
                calibration_detail = "本周评分校准复盘未生成。"
            except Exception as exc:  # noqa: BLE001 - reported, not hidden
                first_failure = first_failure or exc
                calibration = None
                calibration_detail = f"本周评分校准复盘失败：{exc}"
            if calibration:
                path = save_calibration_review(calibration, end=end)
                run_report.set_metric("calibration_reviews", 1)
                self.console.print(f"🎯 Saved scoring calibration review to {path}")
            else:
                run_report.add_alert(
                    "info",
                    "calibration_review_missing",
                    calibration_detail,
                )

            # A run that had a full week of archive and published nothing is a
            # broken run, not a quiet one. Failing here turns the workflow red
            # so it cannot go unnoticed for another fortnight.
            if not published_any:
                raise RuntimeError(
                    "周报生成失败，本周没有产出任何页面"
                    + (f"：{first_failure}" if first_failure else "。")
                )
        except Exception as exc:
            run_report.fail(exc)
            self.console.print(f"[bold red]❌ Weekly review failed: {exc}[/bold red]")
            raise
        finally:
            run_report.finish()
            save_run_report(run_report)

    async def _publish_outputs(
        self,
        items: List[ContentItem],
        *,
        date: str,
        total_candidates: int,
        timezone_name: str,
        run_report: RunReport,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        sponsored: List[EditorialEntry] | None = None,
        x_posted_languages: List[str] | None = None,
    ) -> Dict[str, object]:
        """Render configured languages and publish static-site artifacts.

        Returns the shared context (market snapshot, per-language overviews) so
        the caller can reuse it for the archive and JSON API without
        recomputing or re-prompting.
        """
        overviews: Dict[str, str] = {}
        overview_objects = {}
        publish_started = time.perf_counter()
        # Keep every reader-visible statistic on the same basis: the total
        # number of unique candidates considered for this edition.
        fetched_count = total_candidates

        market_snapshot = None
        overview_client = None
        if items:
            try:
                market_snapshot = await fetch_market_snapshot()
            except Exception as exc:
                self.console.print(
                    f"[yellow]⚠️  Market snapshot unavailable: {exc}[/yellow]"
                )
            if market_snapshot is None:
                run_report.add_alert(
                    "info",
                    "market_snapshot_unavailable",
                    "行情快照获取失败，本期页面省略行情条。",
                )
            try:
                overview_client = create_ai_client(self.config.ai)
            except Exception as exc:
                self.console.print(
                    f"[yellow]⚠️  Overview client unavailable: {exc}[/yellow]"
                )
            if overview_client is not None:
                overview_objects = await generate_edition_overviews(
                    overview_client,
                    items,
                    date=date,
                    languages=list(self.config.ai.languages),
                )
                for language, overview in overview_objects.items():
                    overviews[language] = overview.as_text()

        for lang in self.config.ai.languages:
            summarizer = DailySummarizer(display_timezone=timezone_name)
            summary = await summarizer.generate_summary(
                items,
                date,
                total_candidates,
                language=lang,
            )
            summary_path = self.storage.save_daily_summary(
                date,
                summary,
                language=lang,
            )
            self.console.print(
                f"💾 Saved {lang.upper()} summary to: {summary_path}\n"
            )
            run_report.record_summary(lang)

            try:
                post_filename = f"{date}-summary-{lang}.md"
                posts_dir = Path("docs/_posts")
                posts_dir.mkdir(parents=True, exist_ok=True)
                dest_path = safe_output_path(posts_dir, post_filename)
                fragment_dir = Path("docs/editions") / date
                fragment_dir.mkdir(parents=True, exist_ok=True)
                fragment_path = safe_output_path(fragment_dir, f"{lang}.html")
                fragment_url = f"/editions/{date}/{lang}.html"

                window_front_matter = ""
                if window_start is not None and window_end is not None:
                    window_front_matter = (
                        f'window_start: "{window_start.isoformat()}"\n'
                        f'window_end: "{window_end.isoformat()}"\n'
                    )
                front_matter = (
                    "---\n"
                    "layout: default\n"
                    f"title: \"BMTNews: {date} ({lang.upper()})\"\n"
                    f"date: {date}\n"
                    f"lang: {lang}\n"
                    f"fetched_count: {fetched_count}\n"
                    f'analyzed_count: {run_report.metrics.get("analyzed_today", 0)}\n'
                    f'selected_count: {run_report.metrics.get("displayed_today", 0)}\n'
                    f'critical_count: {run_report.metrics.get("high_priority", 0)}\n'
                    f'fragment_url: "{fragment_url}"\n'
                    f"{window_front_matter}"
                    "---\n\n"
                )
                run_stats = (
                    '<div class="run-stats" hidden '
                    f'data-fetched="{fetched_count}" '
                    f'data-analyzed="{run_report.metrics.get("analyzed_today", 0)}" '
                    f'data-selected="{run_report.metrics.get("displayed_today", 0)}" '
                    f'data-critical="{run_report.metrics.get("high_priority", 0)}">'
                    "</div>\n\n"
                )
                normalized_lang = "en" if lang.lower().startswith("en") else "zh"
                overview = overview_objects.get(normalized_lang)
                if overview is None and overview_client is not None:
                    run_report.add_alert(
                        "info",
                        f"edition_overview_missing_{lang}",
                        f"{lang.upper()} 版今日脉络生成失败，页面省略该模块。",
                    )
                web_content = render_web_feed(
                    items,
                    date=date,
                    total_fetched=total_candidates,
                    language=lang,
                    display_timezone=timezone_name,
                    overview=overview,
                    market=market_snapshot,
                    sponsored=sponsored,
                )
                _atomic_write_text(
                    dest_path,
                    front_matter + run_stats + web_content,
                )
                _atomic_write_text(
                    fragment_path,
                    (
                        '<div class="daily-feed-content" '
                        'data-feed-fragment="2" '
                        f'data-language="{lang}" data-date="{date}">'
                        f"{run_stats}{web_content}</div>\n"
                    ),
                )
                self.console.print(
                    f"📄 Copied {lang.upper()} summary to GitHub Pages: "
                    f"{dest_path} and {fragment_path}\n"
                )
            except Exception as exc:
                run_report.add_alert(
                    "warning",
                    f"page_summary_copy_failed_{lang}",
                    f"{lang.upper()} 页面摘要写入失败：{exc}",
                )
                self.console.print(
                    f"[yellow]⚠️  Failed to copy {lang.upper()} summary "
                    f"to docs/: {exc}[/yellow]\n"
                )

            if self.email_manager and self.config.email and self.config.email.enabled:
                self.console.print(f"📧 Sending {lang.upper()} email summary...")
                subscribers = self.storage.load_subscribers()
                subject = f"BMTNews ({lang.upper()}) - {date}"
                self.email_manager.send_daily_summary(
                    summary,
                    subject,
                    subscribers,
                )

            if self.webhook_notifier:
                await self.webhook_notifier.send_daily_summary(
                    summary=summary,
                    important_items=items,
                    all_items_count=total_candidates,
                    date=date,
                    lang=lang,
                    summarizer=summarizer,
                )

        await self._deliver_telegram_editions(
            items,
            date=date,
            total_candidates=total_candidates,
            run_report=run_report,
        )
        newly_posted: List[str] = []
        await self._deliver_x_editions(
            items,
            date=date,
            run_report=run_report,
            already_posted=x_posted_languages,
            on_posted=newly_posted.append,
        )
        run_report.set_timing("publish_outputs", time.perf_counter() - publish_started)
        return {
            "market": market_snapshot,
            "overviews": overviews,
            "x_posted": newly_posted,
        }

    async def _deliver_x_editions(
        self,
        items: List[ContentItem],
        *,
        date: str,
        run_report: RunReport,
        already_posted: List[str] | None = None,
        on_posted=None,
    ) -> None:
        """Post the top stories to X when the feature is explicitly enabled.

        An edition posts at most once per language for its lifetime:
        republishing it (an editorial edit, a manual rebuild, a retry) must
        not repeat the post.
        """
        publisher = getattr(self, "x_publisher", None)
        if not publisher:
            return
        config = self.config.x_delivery
        if config and config.mode == "drip":
            # The x-distribution workflow owns posting in drip mode.
            return
        posted = set(already_posted or [])
        for language in (config.languages if config else []):
            if language in posted:
                run_report.add_alert(
                    "info",
                    "x_delivery_already_posted",
                    f"本期 {language.upper()} 版已发过 X，重刊不再重复发布。",
                )
                continue
            result = await publisher.send_daily_edition(
                items,
                date=date,
                language=language,
            )
            if result.status == XDeliveryStatus.SUCCESS:
                run_report.set_metric(
                    "x_posts_sent",
                    run_report.metrics.get("x_posts_sent", 0) + result.posted,
                )
                if on_posted is not None:
                    on_posted(language)
            elif result.status == XDeliveryStatus.SKIPPED and result.detail:
                run_report.add_alert(
                    "info",
                    "x_delivery_skipped",
                    f"X 未发布：{result.detail}",
                )
                if config and config.required:
                    raise RuntimeError(result.detail)
            elif result.status == XDeliveryStatus.FAILURE:
                run_report.add_alert(
                    "warning",
                    "x_delivery_failed",
                    result.detail,
                )
                if config and config.required:
                    raise RuntimeError(result.detail)

    async def _deliver_telegram_editions(
        self,
        items: List[ContentItem],
        *,
        date: str,
        total_candidates: int,
        run_report: RunReport,
    ) -> None:
        """Deliver configured languages after every local output is ready."""
        telegram_publisher = getattr(self, "telegram_publisher", None)
        if not telegram_publisher:
            return

        telegram_config = self.config.telegram_delivery
        for language in self.config.ai.languages:
            telegram_result = await telegram_publisher.send_daily_edition(
                items,
                date=date,
                total_candidates=total_candidates,
                language=language,
            )
            if telegram_result.status == TelegramDeliveryStatus.SUCCESS:
                run_report.set_metric(
                    "telegram_messages_sent",
                    run_report.metrics.get("telegram_messages_sent", 0) + 1,
                )
                run_report.set_metric(
                    "telegram_message_chars",
                    run_report.metrics.get("telegram_message_chars", 0)
                    + telegram_result.message_length,
                )
            elif (
                telegram_result.status == TelegramDeliveryStatus.SKIPPED
                and telegram_result.detail
            ):
                run_report.add_alert(
                    "info",
                    "telegram_delivery_skipped",
                    f"Telegram 日报未发送：{telegram_result.detail}",
                )
                if telegram_config and telegram_config.required:
                    raise RuntimeError(telegram_result.detail)
            elif telegram_result.status == TelegramDeliveryStatus.FAILURE:
                run_report.add_alert(
                    "warning",
                    "telegram_delivery_failed",
                    telegram_result.detail,
                )
                if telegram_config and telegram_config.required:
                    raise RuntimeError(telegram_result.detail)

    def _determine_time_window(self, force_hours: int = None) -> datetime:
        if force_hours:
            since = datetime.now(timezone.utc) - timedelta(hours=force_hours)
        else:
            hours = self.config.filtering.time_window_hours
            since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return since

    async def fetch_all_sources(self, since: datetime) -> List[ContentItem]:
        """Fetch content from all configured sources.

        This is a stable stage entry point for integrations such as MCP.

        Args:
            since: Fetch items published after this time

        Returns:
            List[ContentItem]: All fetched items
        """
        self.last_fetch_report = None
        async with httpx.AsyncClient(timeout=30.0) as client:
            tasks = []

            # GitHub sources
            if self.config.sources.github:
                github_scraper = GitHubScraper(self.config.sources.github, client)
                tasks.append(self._fetch_with_progress("GitHub", github_scraper, since))

            # Hacker News
            if self.config.sources.hackernews.enabled:
                hn_scraper = HackerNewsScraper(self.config.sources.hackernews, client)
                tasks.append(self._fetch_with_progress("Hacker News", hn_scraper, since))

            # RSS feeds
            if self.config.sources.rss:
                from .extractors import ExtractorRegistry
                rss_scraper = RSSScraper(
                    self.config.sources.rss,
                    client,
                    ExtractorRegistry(self.config.extractors),
                )
                tasks.append(self._fetch_with_progress("RSS Feeds", rss_scraper, since))

            # Reddit
            if self.config.sources.reddit.enabled:
                reddit_scraper = RedditScraper(self.config.sources.reddit, client)
                tasks.append(self._fetch_with_progress("Reddit", reddit_scraper, since))

            # Telegram
            if self.config.sources.telegram.enabled:
                telegram_scraper = TelegramScraper(self.config.sources.telegram, client)
                tasks.append(self._fetch_with_progress("Telegram", telegram_scraper, since))

            # Twitter (Apify or Playwright mode)
            if self.config.sources.twitter and self.config.sources.twitter.enabled:
                tw_cfg = self.config.sources.twitter
                if tw_cfg.mode == "playwright":
                    twitter_scraper = TwitterPlaywrightScraper(tw_cfg)
                else:
                    twitter_scraper = TwitterScraper(tw_cfg, client)
                tasks.append(self._fetch_with_progress("Twitter", twitter_scraper, since))

            # OpenBB (financial news / filings via the OpenBB Platform SDK)
            if self.config.sources.openbb and self.config.sources.openbb.enabled:
                openbb_scraper = OpenBBScraper(self.config.sources.openbb, client)
                tasks.append(self._fetch_with_progress("OpenBB", openbb_scraper, since))

            # OSS Insight trending repos
            if self.config.sources.ossinsight and self.config.sources.ossinsight.enabled:
                oss_scraper = OSSInsightScraper(self.config.sources.ossinsight, client)
                tasks.append(self._fetch_with_progress("OSS Insight", oss_scraper, since))

            # GDELT 2.0 DOC API (key-less global news)
            if self.config.sources.gdelt and self.config.sources.gdelt.enabled:
                gdelt_scraper = GDELTScraper(self.config.sources.gdelt, client)
                tasks.append(self._fetch_with_progress("GDELT", gdelt_scraper, since))

            # Google News RSS (key-less news search)
            if self.config.sources.google_news and self.config.sources.google_news.enabled:
                gn_scraper = GoogleNewsScraper(self.config.sources.google_news, client)
                tasks.append(self._fetch_with_progress("Google News", gn_scraper, since))

            # Fetch all concurrently
            outcomes = await asyncio.gather(*tasks)
            self.last_fetch_report = FetchReport(outcomes=list(outcomes))

            # Flatten successful and empty outcomes; failures remain in the report.
            all_items: List[ContentItem] = []
            for outcome in outcomes:
                all_items.extend(outcome.items)

            return all_items

    async def _fetch_with_progress(
        self, name: str, scraper, since: datetime
    ) -> SourceFetchOutcome:
        """Fetch from a scraper with progress indication.

        Args:
            name: Source name for display
            scraper: Scraper instance
            since: Fetch items after this time

        Returns:
            SourceFetchOutcome: Named fetch result and diagnostics
        """
        self.console.print(f"🔍 Fetching from {name}...")
        try:
            items = await scraper.fetch(since)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.console.print(f"[red]   Failed to fetch {name}: {error}[/red]")
            return SourceFetchOutcome(
                source_name=name,
                status="failure",
                error=error,
            )

        self.console.print(f"   Found {len(items)} items from {name}")

        # Show per-sub-source breakdown when there are multiple sub-sources
        sub_counts: Dict[str, int] = defaultdict(int)
        for item in items:
            sub_counts[self._sub_source_label(item)] += 1
        if len(sub_counts) > 1:
            for sub, count in sorted(sub_counts.items()):
                self.console.print(f"      • {sub}: {count}")

        return SourceFetchOutcome(
            source_name=name,
            status="success" if items else "empty",
            items=items,
            subsource_counts=dict(sorted(sub_counts.items())),
        )

    @staticmethod
    def _sub_source_label(item: ContentItem) -> str:
        """Return a human-readable sub-source label for an item."""
        meta = item.metadata
        if meta.get("subreddit"):
            return f"r/{meta['subreddit']}"
        if meta.get("feed_name"):
            return meta["feed_name"]
        if meta.get("channel"):
            return f"@{meta['channel']}"
        if meta.get("period") and meta.get("repo"):
            return f"ossinsight:{meta.get('primary_language', 'all')}"
        if meta.get("repo"):
            return meta["repo"]
        if meta.get("watchlist"):
            return meta["watchlist"]
        if meta.get("source_name"):
            return meta["source_name"]
        if meta.get("gn_query"):
            return f"google_news:{meta['gn_query']}"
        if meta.get("domain"):
            return meta["domain"]
        return item.author or "unknown"

    def _apply_threads(
        self,
        items: List[ContentItem],
        *,
        edition_date: str,
        history_days: int = 30,
    ) -> None:
        """Tag items with their story thread, using the published archive.

        Fail-soft: any error leaves items unthreaded, which only costs the
        thread badge on the page.
        """
        if not items:
            return
        try:
            today = date_type.fromisoformat(edition_date)
            history = load_recent_archive(history_days, today=today)
            stories = [
                (
                    str(item.url),
                    fingerprint(
                        title_zh=str(item.metadata.get("title_zh") or item.title),
                        title_en=str(item.metadata.get("title_en") or item.title),
                        summary_zh=str(
                            item.metadata.get("whats_new_zh")
                            or item.ai_summary
                            or ""
                        ),
                        summary_en=str(
                            item.metadata.get("whats_new_en")
                            or item.ai_summary
                            or ""
                        ),
                        tags=item.ai_tags or [],
                    ),
                )
                for item in items
            ]
            assignments = assign_threads(
                stories,
                history,
                edition_date=edition_date,
            )
            for item in items:
                assignment = assignments.get(str(item.url))
                if assignment is None:
                    continue
                item.metadata["thread_id"] = assignment.thread_id
                item.metadata["thread_day"] = assignment.day
        except Exception as exc:
            self.console.print(
                f"[yellow]⚠️  Thread linking skipped: {exc}[/yellow]"
            )

    async def _update_event_timeline(
        self,
        items: List[ContentItem],
        *,
        run_report: RunReport,
    ) -> None:
        """Update the restored catalog with qualified, previously unseen stories."""
        if not items or not EVENT_CATALOG_PATH.exists():
            return
        metadata, events = load_event_catalog(EVENT_CATALOG_PATH)
        known = known_story_assignments(events)
        client = (
            create_ai_client(self.config.ai)
            if any(item.id not in known for item in items)
            else None
        )
        updated, result = await update_events(items, events, client=client)
        save_event_catalog(metadata, updated, EVENT_CATALOG_PATH)
        self._publish_current_event_pages(events=updated)
        for key, value in {
            "event_items_considered": result.considered,
            "event_items_reused": result.already_known,
            "event_candidate_calls": result.candidates_classified,
            "event_material_updates": result.material_updates,
            "event_duplicate_sources": result.duplicate_sources,
            "event_new_events": result.new_events,
            "event_classifier_errors": result.classifier_errors,
        }.items():
            run_report.set_metric(
                key, run_report.metrics.get(key, 0) + value
            )
        self.console.print(
            "🧭 Event timeline: "
            f"{result.material_updates} material updates, "
            f"{result.duplicate_sources} duplicate sources, "
            f"{result.new_events} new events\n"
        )

    def _publish_current_event_pages(
        self,
        *,
        events=None,
    ) -> None:
        """Regenerate bilingual event pages, index data, and JSON endpoints."""
        if not EVENT_CATALOG_PATH.exists():
            return
        if events is None:
            _, events = load_event_catalog(EVENT_CATALOG_PATH)
        redirects, retired = load_legacy_event_urls()
        publish_event_compatibility_pages(
            events,
            redirects,
            retired,
            list(self.config.ai.languages) or ["zh"],
        )

    def _publish_archive_artifacts(
        self,
        items: List[ContentItem],
        *,
        date: str,
        run_report: RunReport,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
        market: MarketSnapshot | None = None,
        overviews: Dict[str, str] | None = None,
    ) -> None:
        """Append to the archive and regenerate every derived artifact.

        Covers the JSON API, per-category feeds, and the thread and entity
        pages. Fail-soft: the edition itself is already published by the
        time this runs, so problems here become warnings, not failures.
        """
        try:
            records = build_records(
                items,
                date=date,
                top_category_of=_top_level_category,
            )
            save_edition_records(records, date=date)

            today = date_type.fromisoformat(date)
            history = load_recent_archive(120, today=today)
            languages = list(self.config.ai.languages) or ["zh"]

            payload = build_edition_payload(
                records,
                date=date,
                stats={
                    "candidates": run_report.metrics.get("edition_candidates", 0),
                    "analyzed": run_report.metrics.get("analyzed_today", 0),
                    "displayed": run_report.metrics.get("displayed_today", 0),
                    "high_priority": run_report.metrics.get("high_priority", 0),
                },
                window_start=window_start,
                window_end=window_end,
                market=market,
                overviews=overviews,
            )
            write_edition_api(payload, date=date)
            write_editions_index(history)
            write_category_feeds(history, languages)

            threads = collect_threads(history, minimum_days=2, limit=40)
            entities = collect_entities(history, minimum_mentions=3, limit=40)
            event_rows = []
            if EVENT_CATALOG_PATH.exists():
                _, event_rows = load_event_catalog(EVENT_CATALOG_PATH)
            write_sitemap(
                history,
                threads=threads,
                entities=entities,
                events=event_rows,
            )
            written = publish_archive_pages(threads, entities, languages)
            run_report.set_metric("archive_records", len(records))
            run_report.set_metric("archive_threads", len(threads))
            run_report.set_metric("archive_entities", len(entities))
            self.console.print(
                f"🗂️  Archived {len(records)} records; "
                f"{written['threads']} thread and {written['entities']} entity "
                "pages refreshed\n"
            )
        except Exception as exc:
            run_report.add_alert(
                "warning",
                "archive_artifacts_failed",
                f"归档与衍生页面生成失败：{exc}",
            )
            self.console.print(
                f"[yellow]⚠️  Archive artifacts skipped: {exc}[/yellow]"
            )

    def _rescue_low_signal_items(
        self,
        items: List[ContentItem],
        *,
        limit: int,
        max_per_source: int = 2,
    ) -> List[ContentItem]:
        """Pick the highest-scored analyzed items for a low-signal edition.

        Used only when nothing reached the score threshold, so the edition
        publishes a short ranked digest instead of an empty page. Diversity
        is kept with a small per-source cap.
        """
        scored = sorted(
            (item for item in items if item.ai_score is not None),
            key=lambda item: item.ai_score or 0,
            reverse=True,
        )
        rescued: List[ContentItem] = []
        per_source: Dict[str, int] = defaultdict(int)
        for item in scored:
            source_key = (
                f"{item.source_type.value}/{self._sub_source_label(item)}"
            )
            if per_source[source_key] >= max_per_source:
                continue
            rescued.append(item)
            per_source[source_key] += 1
            if len(rescued) >= limit:
                break
        return rescued

    def _source_breakdown(self, items: List[ContentItem]) -> Dict[str, int]:
        """Count items by the source key used by digest diversity limits."""
        counts: Dict[str, int] = defaultdict(int)
        for item in items:
            counts[
                f"{item.source_type.value}/{self._sub_source_label(item)}"
            ] += 1
        return dict(sorted(counts.items()))

    def _group_breakdown(self, items: List[ContentItem]) -> Dict[str, int]:
        """Count items by configured quota group using display labels."""
        groups = self.config.filtering.category_groups
        category_to_group: Dict[str, str] = {}
        for group_key, group in groups.items():
            for category in group.categories:
                category_to_group.setdefault(category, group_key)

        counts: Dict[str, int] = defaultdict(int)
        default_group = self.config.filtering.default_group
        for item in items:
            category = item.metadata.get("category")
            group_key = (
                category_to_group.get(category, default_group)
                if isinstance(category, str)
                else default_group
            )
            group = groups.get(group_key)
            label = group.name or group_key if group is not None else group_key
            counts[label] += 1
        return dict(sorted(counts.items()))

    def merge_cross_source_duplicates(self, items: List[ContentItem]) -> List[ContentItem]:
        """Merge items that point to the same URL from different sources.

        This is a stable stage helper for integrations such as MCP.

        Keeps the item with the richest content and combines metadata.

        Args:
            items: Items to deduplicate

        Returns:
            List[ContentItem]: Deduplicated items
        """
        # Group by normalized URL
        url_groups: Dict[tuple[str, str, str, str, Optional[int], str, str], List[ContentItem]] = {}
        for item in items:
            key = _deduplication_url_key(str(item.url))
            url_groups.setdefault(key, []).append(item)

        merged = []
        for group in url_groups.values():
            group_copies = [item.model_copy(deep=True) for item in group]
            if len(group) == 1:
                merged.append(group_copies[0])
                continue

            # Pick the item with the richest content as primary
            primary = max(group_copies, key=lambda x: len(x.content or ""))

            # Merge metadata and source info from other items
            all_sources: List[str] = []
            for item in group_copies:
                label = self._provenance_label(item)
                if label not in all_sources:
                    all_sources.append(label)
                # Merge metadata (engagement, discussion, etc.)
                for mk, mv in item.metadata.items():
                    if mk not in primary.metadata or not primary.metadata[mk]:
                        primary.metadata[mk] = mv

                # Append content (e.g., comments from another source)
                if item is not primary and item.content:
                    if primary.content and item.content not in primary.content:
                        primary.content = (primary.content or "") + f"\n\n--- From {item.source_type.value} ---\n" + item.content

            primary.metadata["merged_sources"] = all_sources
            merged.append(primary)

        return merged

    def _provenance_label(self, item: ContentItem) -> str:
        """Name the outlet behind an item, falling back to its source type."""
        label = self._sub_source_label(item)
        if not label or label == "unknown":
            return item.source_type.value
        return label

    def _record_confirming_source(
        self,
        primary: ContentItem,
        duplicate: ContentItem,
    ) -> None:
        """Add the duplicate's outlet to the primary's confirming sources."""
        sources = primary.metadata.get("merged_sources")
        if not isinstance(sources, list):
            sources = []
        merged = list(sources) or [self._provenance_label(primary)]
        for label in (
            duplicate.metadata.get("merged_sources")
            if isinstance(duplicate.metadata.get("merged_sources"), list)
            else [self._provenance_label(duplicate)]
        ):
            if label and label not in merged:
                merged.append(label)
        primary.metadata["merged_sources"] = merged

    async def merge_topic_duplicates(
        self,
        items: List[ContentItem],
        *,
        log: bool = True,
    ) -> List[ContentItem]:
        """Merge items covering the same topic using AI semantic deduplication.

        This is a stable stage helper for integrations such as MCP.

        Sends all item titles, tags, and summaries to AI in a single call.
        Items must already be sorted by ai_score descending so that the first
        item in each duplicate group is always the highest-scored one.
        Content (comments) from duplicate items is merged into the primary.

        Falls back to returning items unchanged if the AI call fails.
        """
        if len(items) <= 1:
            return items

        started = time.perf_counter()
        original_items = items
        prints = [
            fingerprint(
                title_zh=str(item.metadata.get("title_zh") or ""),
                title_en=str(item.metadata.get("title_en") or item.title),
                summary_zh=str(item.metadata.get("detailed_summary_zh") or ""),
                summary_en=str(item.ai_summary or ""),
                tags=item.ai_tags,
            )
            for item in items
        ]
        parent = list(range(len(items)))

        def find(index: int) -> int:
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        def union(left: int, right: int) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[right_root] = left_root

        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                if same_thread(prints[left], prints[right]):
                    union(left, right)
        group_sizes: Dict[int, int] = defaultdict(int)
        for index in range(len(items)):
            group_sizes[find(index)] += 1
        candidate_indices = [
            index for index in range(len(items)) if group_sizes[find(index)] > 1
        ]
        if not candidate_indices:
            self._set_timing("topic_dedup", started)
            return items
        items = [items[index] for index in candidate_indices]
        if self.last_run_report is not None:
            self.last_run_report.set_metric(
                "topic_dedup_ai_candidates", len(items)
            )

        from .ai.prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
        from .ai.utils import parse_json_response

        # Build the item list for the prompt
        lines = []
        for i, item in enumerate(items):
            tags = ", ".join(item.ai_tags) if item.ai_tags else "—"
            summary = item.ai_summary or "—"
            lines.append(f"[{i}] {item.title}\n    Tags: {tags}\n    Summary: {summary}")
        items_text = "\n\n".join(lines)

        try:
            ai_client = create_ai_client(self.config.ai)
            response = await ai_client.complete(
                system=TOPIC_DEDUP_SYSTEM,
                user=TOPIC_DEDUP_USER.format(items=items_text),
            )
            result = parse_json_response(response)
            if result is None:
                if log:
                    self.console.print("[yellow]  dedup: could not parse AI response, skipping[/yellow]")
                self._set_timing("topic_dedup", started)
                return original_items

            duplicate_groups = result.get("duplicates", [])
        except Exception as e:
            if log:
                self.console.print(f"[yellow]  dedup: AI call failed ({e}), skipping[/yellow]")
            self._set_timing("topic_dedup", started)
            return original_items

        if not duplicate_groups:
            self._set_timing("topic_dedup", started)
            return original_items

        # Build a set of indices to drop (all non-primary duplicates)
        drop_indices: set[int] = set()
        for group in duplicate_groups:
            if not isinstance(group, list) or len(group) < 2:
                continue
            primary_idx = group[0]
            if primary_idx < 0 or primary_idx >= len(items):
                continue
            primary = items[primary_idx]
            for dup_idx in group[1:]:
                if not isinstance(dup_idx, int) or dup_idx < 0 or dup_idx >= len(items):
                    continue
                if dup_idx == primary_idx:
                    continue
                dup = items[dup_idx]
                # Record that another outlet independently carried the story.
                # Most duplicates are the same event under different URLs, so
                # this — not URL-level dedup — is what makes the provenance
                # badge meaningful.
                self._record_confirming_source(primary, dup)
                # Merge comments/content from the duplicate into the primary
                if dup.content:
                    if not primary.content or dup.content not in primary.content:
                        label = dup.source_type.value
                        primary.content = (primary.content or "") + f"\n\n--- From {label} ---\n{dup.content}"
                if log:
                    self.console.print(
                        f"   [dim]dedup: keep [{primary_idx}] {primary.title}[/dim]\n"
                        f"   [dim]       drop [{dup_idx}] {dup.title}[/dim]"
                    )
                drop_indices.add(dup_idx)

        dropped_ids = {id(items[index]) for index in drop_indices}
        self._set_timing("topic_dedup", started)
        return [item for item in original_items if id(item) not in dropped_ids]

    async def filter_items(
        self,
        items: List[ContentItem],
        *,
        threshold: Optional[float] = None,
        topic_dedup: bool = True,
        apply_balance: bool = True,
        log: bool = True,
        dedup_context: Optional[List[ContentItem]] = None,
    ) -> FilteringPipelineResult:
        """Apply score thresholding, published-history dedup, and balancing."""
        effective_threshold = (
            threshold
            if threshold is not None
            else self.config.filtering.ai_score_threshold
        )
        threshold_items = [
            item
            for item in items
            if item.ai_score is not None and item.ai_score >= effective_threshold
        ]
        threshold_items.sort(key=lambda item: item.ai_score or 0, reverse=True)

        if log:
            self.console.print(
                f"⭐️ {len(threshold_items)} items scored ≥ {effective_threshold}\n"
            )

        deduped_items = threshold_items
        if topic_dedup and deduped_items:
            context_items = dedup_context or []
            if context_items:
                published_identities = {
                    item_identity(item) for item in context_items
                }
                deduped_items = [
                    item
                    for item in deduped_items
                    if item_identity(item) not in published_identities
                ]

                if deduped_items:
                    # Published context comes first so the existing topic
                    # deduplicator keeps the first publication of an event.
                    context_copies = [
                        item.model_copy(update={"ai_score": 11.0}, deep=True)
                        for item in context_items
                    ]
                    combined = [*context_copies, *deduped_items]
                    merged = await self.merge_topic_duplicates(
                        combined,
                        log=log,
                    )
                    survivors = {id(item) for item in merged}
                    deduped_items = [
                        item for item in deduped_items if id(item) in survivors
                    ]
            else:
                deduped_items = await self.merge_topic_duplicates(
                    deduped_items,
                    log=log,
                )
        topic_dedup_removed = len(threshold_items) - len(deduped_items)

        if log and topic_dedup_removed:
            self.console.print(
                f"🧹 Removed {topic_dedup_removed} topic duplicates "
                f"→ {len(deduped_items)} unique items\n"
            )

        balanced_digest = (
            self.apply_balanced_digest(deduped_items, log=log)
            if apply_balance
            else BalancedDigestResult(items=deduped_items)
        )
        return FilteringPipelineResult(
            items=balanced_digest.items,
            threshold_count=len(threshold_items),
            topic_dedup_count=len(deduped_items),
            topic_dedup_removed=topic_dedup_removed,
            balanced_digest=balanced_digest,
        )

    def apply_balanced_digest(
        self,
        items: List[ContentItem],
        *,
        log: bool = True,
        allow_primary_borrowing: bool = False,
        fill_to_minimum: bool = False,
    ) -> BalancedDigestResult:
        """Apply configured category quotas and the final item cap.

        Categories are read from ``item.metadata["category"]``. If a category
        appears in more than one configured group, the first group in config
        order wins.
        """
        filtering = self.config.filtering
        groups = filtering.category_groups
        max_items = filtering.max_items

        if not groups and max_items is None:
            return BalancedDigestResult(items=items)

        sorted_items = sorted(
            items,
            key=lambda item: item.ai_score or 0,
            reverse=True,
        )

        category_to_group: Dict[str, str] = {}
        duplicate_categories: List[str] = []
        for group_key, group in groups.items():
            for category in group.categories:
                if category in category_to_group:
                    if category_to_group[category] != group_key:
                        duplicate_categories.append(category)
                    continue
                category_to_group[category] = group_key

        if log:
            for category in sorted(set(duplicate_categories)):
                first_group = category_to_group[category]
                self.console.print(
                    f"[yellow]Warning: category '{category}' is configured in multiple "
                    f"groups; using '{first_group}'.[/yellow]"
                )

        selected: List[tuple[ContentItem, str]] = []
        selected_object_ids: set[int] = set()
        group_counts: Dict[str, int] = defaultdict(int)
        source_counts: Dict[str, int] = defaultdict(int)
        category_deferred_ids: set[int] = set()
        source_deferred_ids: set[int] = set()
        default_group = filtering.default_group

        def group_for(item: ContentItem) -> str:
            category = item.metadata.get("category")
            return (
                category_to_group.get(category, default_group)
                if isinstance(category, str)
                else default_group
            )

        def source_for(item: ContentItem) -> str:
            return (
                f"{item.source_type.value}/"
                f"{self._sub_source_label(item)}"
            )

        def select(
            item: ContentItem,
            group_key: str,
            *,
            group_limit: Optional[int] = None,
            enforce_group_limit: bool = True,
            enforce_source_limit: bool = True,
        ) -> bool:
            if id(item) in selected_object_ids:
                return False
            if max_items is not None and len(selected) >= max_items:
                return False
            if enforce_group_limit:
                limit = group_limit
                if limit is None:
                    if group_key in groups:
                        limit = groups[group_key].limit
                    else:
                        limit = filtering.default_group_limit

                if limit is not None and group_counts[group_key] >= limit:
                    category_deferred_ids.add(id(item))
                    return False

            source_key = source_for(item)
            source_limit = filtering.max_items_per_source
            if (
                enforce_source_limit
                and source_limit is not None
                and source_counts[source_key] >= source_limit
            ):
                source_deferred_ids.add(id(item))
                return False

            selected.append((item, group_key))
            selected_object_ids.add(id(item))
            group_counts[group_key] += 1
            source_counts[source_key] += 1
            return True

        primary_groups = set(filtering.primary_groups)
        primary_minimum = filtering.primary_group_min_items or 0
        if primary_groups and primary_minimum:
            for item in sorted_items:
                group_key = group_for(item)
                if group_key not in primary_groups:
                    continue
                select(item, group_key)
                selected_primary = sum(
                    group_counts[group] for group in primary_groups
                )
                if selected_primary >= primary_minimum:
                    break

        for item in sorted_items:
            select(item, group_for(item))

        borrowed_count = 0
        borrow_limit = filtering.primary_group_borrow_limit
        if allow_primary_borrowing and primary_groups and borrow_limit is not None:
            for item in sorted_items:
                if id(item) in selected_object_ids:
                    continue
                if max_items is not None and len(selected) >= max_items:
                    break
                group_key = group_for(item)
                if group_key not in primary_groups:
                    continue
                effective_limit = max(groups[group_key].limit, borrow_limit)
                if select(item, group_key, group_limit=effective_limit):
                    borrowed_count += 1

        minimum_fill_count = 0
        minimum_display = filtering.minimum_display_items
        if fill_to_minimum and minimum_display is not None:
            fill_target = (
                min(minimum_display, max_items)
                if max_items is not None
                else minimum_display
            )
            for item in sorted_items:
                if len(selected) >= fill_target:
                    break
                if id(item) in selected_object_ids:
                    continue
                group_key = group_for(item)
                # AI and policy caps are hard limits. Only the Crypto primary
                # track may exceed its normal/borrowed cap to avoid a short
                # edition, and every recovery item has already cleared score
                # and topic/history deduplication.
                recovery_limit: Optional[int] = None
                if group_key not in primary_groups:
                    if group_key in groups:
                        recovery_limit = groups[group_key].limit
                    else:
                        recovery_limit = filtering.default_group_limit
                    if (
                        recovery_limit is not None
                        and group_counts[group_key] >= recovery_limit
                    ):
                        category_deferred_ids.add(id(item))
                        continue
                if select(
                    item,
                    group_key,
                    group_limit=recovery_limit,
                    enforce_group_limit=group_key not in primary_groups,
                    enforce_source_limit=False,
                ):
                    minimum_fill_count += 1

        selected.sort(
            key=lambda pair: pair[0].ai_score or 0,
            reverse=True,
        )

        final_counts: Dict[str, int] = defaultdict(int)
        for _, group_key in selected:
            final_counts[group_key] += 1

        group_limits: Dict[str, Optional[int]] = {
            group_key: group.limit for group_key, group in groups.items()
        }
        if allow_primary_borrowing and borrow_limit is not None:
            for group_key in primary_groups:
                group_limits[group_key] = max(
                    groups[group_key].limit,
                    borrow_limit,
                )
        group_limits.setdefault(default_group, filtering.default_group_limit)

        if log:
            self.console.print(
                f"⚖️ Balanced digest selected {len(selected)}/{len(items)} items"
            )
            for group_key, group in groups.items():
                label = group.name or group_key
                effective_limit = group_limits[group_key]
                self.console.print(
                    f"      • {label}: "
                    f"{final_counts.get(group_key, 0)}/{effective_limit}"
                )
            if (
                final_counts.get(default_group, 0)
                or filtering.default_group_limit is not None
            ):
                limit_label = (
                    str(filtering.default_group_limit)
                    if filtering.default_group_limit is not None
                    else "unlimited"
                )
                self.console.print(
                    f"      • {default_group}: "
                    f"{final_counts.get(default_group, 0)}/{limit_label}"
                )
            self.console.print("")

        return BalancedDigestResult(
            items=[item for item, _ in selected],
            enabled=True,
            group_counts=dict(final_counts),
            group_limits=group_limits,
            duplicate_categories=sorted(set(duplicate_categories)),
            borrowed_count=borrowed_count,
            category_limit_deferred=len(category_deferred_ids),
            source_limit_deferred=len(source_deferred_ids),
            minimum_fill_count=minimum_fill_count,
        )

    async def _expand_twitter_discussion(self, items: List[ContentItem]) -> None:
        """Second-stage: fetch reply text for important Twitter items and re-analyze.

        Only runs when sources.twitter.fetch_reply_text is True.
        Bounded by max_tweets_to_expand to control cost.
        """
        tw_cfg = self.config.sources.twitter
        if not tw_cfg or not tw_cfg.enabled or not tw_cfg.fetch_reply_text:
            return

        from .models import SourceType

        twitter_items = [
            item for item in items
            if item.source_type == SourceType.TWITTER
        ][:tw_cfg.max_tweets_to_expand]

        if not twitter_items:
            return

        self.console.print(
            f"💬 Fetching reply text for {len(twitter_items)} Twitter items..."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            if tw_cfg.mode == "playwright":
                self.console.print(
                    "   [yellow]Reply expansion not yet supported in Playwright mode.[/yellow]"
                )
                return
            scraper = TwitterScraper(tw_cfg, client)
            expanded = []
            for item in twitter_items:
                try:
                    reply_lines = await scraper.fetch_replies_for_item(item)
                    if TwitterScraper.append_discussion_content(item, reply_lines):
                        expanded.append(item)
                        self.console.print(
                            f"   💬 {len(reply_lines)} replies added to: {item.title[:60]}"
                        )
                except Exception as exc:
                    self.console.print(
                        f"   [yellow]⚠️  Reply fetch failed for {item.id}: {exc}[/yellow]"
                    )

        if not expanded:
            return

        self.console.print(
            f"   Re-analyzing {len(expanded)} Twitter items with reply context...\n"
        )
        ai_client = create_ai_client(self.config.ai)
        analyzer = ContentAnalyzer(
            ai_client,
            allowed_categories=self._analysis_categories(),
        )
        await analyzer.analyze_batch(expanded)

    async def _enrich_important_items(self, items: List[ContentItem]) -> None:
        """Enrich items with background knowledge (2nd AI pass).

        For each item that passed the score threshold, call AI to generate
        background knowledge based on the item's actual content.

        Args:
            items: Important items to enrich (modified in-place)
        """
        if not items:
            return

        started = time.perf_counter()
        self.console.print("📚 Enriching with background knowledge...")
        cache = self._result_cache()
        cached: list[ContentItem] = []
        misses = items
        if cache is not None:
            cached, misses = split_cached(cache, items, stage="enrichment")
            if self.last_run_report is not None:
                report = self.last_run_report
                report.set_metric(
                    "enrichment_cache_hits",
                    report.metrics.get("enrichment_cache_hits", 0) + len(cached),
                )
                report.set_metric(
                    "enrichment_cache_misses",
                    report.metrics.get("enrichment_cache_misses", 0) + len(misses),
                )
        if not misses:
            self.console.print(f"   Reused enrichment for {len(cached)} items\n")
            self._set_timing("enrichment", started)
            return
        ai_client = create_ai_client(self.config.ai)
        enricher = ContentEnricher(ai_client)
        await enricher.enrich_batch(misses)
        if cache is not None:
            for item in misses:
                cache.store_enrichment(item)
            cache.save()
        self.console.print(
            f"   Enriched {len(misses)} items; reused {len(cached)}\n"
        )
        self._set_timing("enrichment", started)

    async def _analyze_content(self, items: List[ContentItem]) -> List[ContentItem]:
        """Analyze content items with AI.

        Args:
            items: Items to analyze

        Returns:
            List[ContentItem]: Analyzed items
        """
        started = time.perf_counter()
        self.console.print("🤖 Analyzing content with AI...")

        ai_client = create_ai_client(self.config.ai)
        selected = items
        if (
            self.config.ai.prefilter_enabled
            and len(items) > self.config.ai.prefilter_max_candidates
        ):
            prefilter_started = time.perf_counter()
            result = await ContentPrefilter(
                ai_client,
                batch_size=self.config.ai.prefilter_batch_size,
            ).select(
                items,
                maximum=self.config.ai.prefilter_max_candidates,
            )
            selected = result.items
            if self.last_run_report is not None:
                report = self.last_run_report
                report.set_metric(
                    "prefilter_evaluated",
                    report.metrics.get("prefilter_evaluated", 0) + result.evaluated,
                )
                report.set_metric(
                    "prefilter_removed",
                    report.metrics.get("prefilter_removed", 0) + result.removed,
                )
                report.set_metric(
                    "prefilter_failed_batches",
                    report.metrics.get("prefilter_failed_batches", 0)
                    + result.failed_batches,
                )
                report.add_timing(
                    "prefilter", time.perf_counter() - prefilter_started
                )
            self.console.print(
                f"   Prefilter kept {len(selected)}/{len(items)} candidates"
                f" ({result.failed_batches} fail-open batches)\n"
            )

        cache = self._result_cache()
        cached: list[ContentItem] = []
        misses = selected
        if cache is not None:
            cached, misses = split_cached(cache, selected, stage="analysis")
            if self.last_run_report is not None:
                report = self.last_run_report
                report.set_metric(
                    "analysis_cache_hits",
                    report.metrics.get("analysis_cache_hits", 0) + len(cached),
                )
                report.set_metric(
                    "analysis_cache_misses",
                    report.metrics.get("analysis_cache_misses", 0) + len(misses),
                )
        analyzer = ContentAnalyzer(
            ai_client,
            allowed_categories=self._analysis_categories(),
        )
        if misses:
            await analyzer.analyze_batch(misses)
            if cache is not None:
                for item in misses:
                    cache.store_analysis(item)
                cache.save()
        self._set_timing("analysis", started)
        return selected

    def _analysis_categories(self) -> List[str]:
        """Return the configured leaf categories accepted from AI analysis."""
        return sorted(
            {
                category
                for group in self.config.filtering.category_groups.values()
                for category in group.categories
            }
        )

    async def _generate_summary(
        self,
        items: List[ContentItem],
        date: str,
        total_fetched: int,
        language: str = "en",
    ) -> str:
        """Generate daily summary.

        Args:
            items: Important items to include (already enriched with background/related)
            date: Date string
            total_fetched: Total items fetched
            language: Output language ("en" or "zh")

        Returns:
            str: Markdown summary
        """
        self.console.print("📝 Generating daily summary...")

        summarizer = DailySummarizer()

        return await summarizer.generate_summary(items, date, total_fetched, language=language)
