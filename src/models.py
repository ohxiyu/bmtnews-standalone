"""Core data models for BMTNews."""

from datetime import datetime, timezone
from enum import Enum
import re
from typing import Annotated, Literal, Optional, List, Dict, Any, NamedTuple, Union
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, HttpUrl, Field, field_validator, model_validator


class SourceType(str, Enum):
    """Supported information source types."""

    GITHUB = "github"
    HACKERNEWS = "hackernews"
    RSS = "rss"
    REDDIT = "reddit"
    TELEGRAM = "telegram"
    TWITTER = "twitter"
    OPENBB = "openbb"
    OSSINSIGHT = "ossinsight"
    GDELT = "gdelt"
    GOOGLE_NEWS = "google_news"
    EDITORIAL = "editorial"


class SourceDefinition(NamedTuple):
    """How a top-level source is represented in SourcesConfig."""

    config_field: str
    config_is_list: bool = False
    item_fields: tuple[str, ...] = ()


SOURCE_REGISTRY = {
    SourceType.GITHUB.value: SourceDefinition("github", config_is_list=True),
    SourceType.HACKERNEWS.value: SourceDefinition("hackernews"),
    SourceType.RSS.value: SourceDefinition("rss", config_is_list=True),
    SourceType.REDDIT.value: SourceDefinition("reddit", item_fields=("subreddits", "users")),
    SourceType.TELEGRAM.value: SourceDefinition("telegram", item_fields=("channels",)),
    SourceType.TWITTER.value: SourceDefinition("twitter", item_fields=("users",)),
    SourceType.OPENBB.value: SourceDefinition("openbb", item_fields=("watchlists",)),
    SourceType.OSSINSIGHT.value: SourceDefinition("ossinsight"),
    SourceType.GDELT.value: SourceDefinition("gdelt"),
    SourceType.GOOGLE_NEWS.value: SourceDefinition("google_news"),
}


class ContentItem(BaseModel):
    """Unified content item model from any source."""

    id: str  # Format: {source}:{subtype}:{native_id}
    source_type: SourceType
    title: str
    url: HttpUrl
    content: Optional[str] = None
    author: Optional[str] = None
    published_at: datetime
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # AI analysis results
    ai_score: Optional[float] = None  # 0-10 importance score
    ai_reason: Optional[str] = None
    ai_summary: Optional[str] = None
    ai_tags: List[str] = Field(default_factory=list)


class AIProvider(str, Enum):
    """Supported AI providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    AZURE = "azure"
    ALI = "ali"
    GEMINI = "gemini"
    DOUBAO = "doubao"
    MINIMAX = "minimax"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"


# Provider-specific defaults used by setup and provider-chain expansion.
AI_PROVIDER_DEFAULTS = {
    AIProvider.ANTHROPIC: {
        "model": "claude-3-5-sonnet-20241022",
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": None,
    },
    AIProvider.OPENAI: {
        "model": "gpt-4",
        "api_key_env": "OPENAI_API_KEY",
        "base_url": None,
    },
    AIProvider.AZURE: {
        "model": "gpt-4",
        "api_key_env": "AZURE_OPENAI_API_KEY",
        "base_url": None,
        "azure_endpoint_env": "AZURE_OPENAI_ENDPOINT",
        "api_version": "2024-10-21",
    },
    AIProvider.ALI: {
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    AIProvider.GEMINI: {
        "model": "gemini-1.5-flash",
        "api_key_env": "GOOGLE_API_KEY",
        "base_url": None,
    },
    AIProvider.DOUBAO: {
        "model": "doubao-pro-32k",
        "api_key_env": "DOUBAO_API_KEY",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
    },
    AIProvider.MINIMAX: {
        "model": "MiniMax-M3",
        "api_key_env": "MINIMAX_API_KEY",
        "base_url": "https://api.minimax.io/v1",
    },
    AIProvider.DEEPSEEK: {
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
    },
    AIProvider.OLLAMA: {
        "model": "llama3.1",
        "api_key_env": "",
        "base_url": "http://localhost:11434/v1",
    },
}


class AIConfig(BaseModel):
    """AI client configuration."""

    provider: AIProvider
    provider_chain: Optional[str] = None
    model: str
    base_url: Optional[str] = None
    api_key_env: str
    temperature: float = 0.3
    max_tokens: int = 4096
    throttle_sec: float = 0.0
    analysis_concurrency: int = 1
    enrichment_concurrency: int = 1
    languages: List[str] = Field(default_factory=lambda: ["en"])
    # Azure OpenAI specific; required when provider == AZURE
    azure_endpoint_env: Optional[str] = None
    api_version: Optional[str] = None

    @field_validator("languages")
    @classmethod
    def validate_languages(cls, languages: List[str]) -> List[str]:
        """Allow conventional language tags while excluding path syntax."""
        language_tag = re.compile(r"^[A-Za-z]{2,8}(?:[-_][A-Za-z0-9]{1,8})*$")
        invalid = [language for language in languages if not language_tag.fullmatch(language)]
        if invalid:
            raise ValueError(f"invalid language code: {invalid[0]!r}")
        return languages


class GitHubSourceConfig(BaseModel):
    """GitHub source configuration."""

    type: str  # "user_events", "repo_releases", etc.
    username: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    enabled: bool = True
    category: Optional[str] = None


class HackerNewsConfig(BaseModel):
    """Hacker News configuration."""

    enabled: bool = True
    fetch_top_stories: int = 30
    min_score: int = 100
    category: Optional[str] = None


class ExtractorType(str, Enum):
    TRAFILATURA = "trafilatura"


class TrafilaturaExtractorConfig(BaseModel):
    type: Literal[ExtractorType.TRAFILATURA] = ExtractorType.TRAFILATURA
    favor_precision: bool = False
    favor_recall: bool = False


ExtractorConfig = Annotated[
    Union[TrafilaturaExtractorConfig],
    Field(discriminator="type"),
]


class RSSSourceConfig(BaseModel):
    """RSS feed source configuration."""

    name: str
    url: HttpUrl
    enabled: bool = True
    category: Optional[str] = None
    content_extractor: Optional[str] = None


class RedditSubredditConfig(BaseModel):
    """Configuration for monitoring a specific subreddit."""

    subreddit: str
    enabled: bool = True
    sort: str = "hot"  # hot, new, top, rising
    time_filter: str = (
        "day"  # hour, day, week, month, year, all (only for top/controversial)
    )
    fetch_limit: int = 25
    min_score: int = 10
    category: Optional[str] = None


class RedditUserConfig(BaseModel):
    """Configuration for monitoring a specific Reddit user."""

    username: str  # without u/ prefix
    enabled: bool = True
    sort: str = "new"
    fetch_limit: int = 10
    category: Optional[str] = None


class RedditConfig(BaseModel):
    """Reddit source configuration."""

    enabled: bool = True
    subreddits: List[RedditSubredditConfig] = Field(default_factory=list)
    users: List[RedditUserConfig] = Field(default_factory=list)
    fetch_comments: int = 5  # top comments per post, 0 to disable


class TelegramChannelConfig(BaseModel):
    """Configuration for monitoring a specific Telegram channel."""

    channel: str  # channel username, e.g. "zaihuapd"
    enabled: bool = True
    fetch_limit: int = 20
    category: Optional[str] = None


class TelegramConfig(BaseModel):
    """Telegram source configuration."""

    enabled: bool = True
    channels: List[TelegramChannelConfig] = Field(default_factory=list)


class TwitterConfig(BaseModel):
    """Twitter source configuration.

    Two modes are supported:
    - "apify": Use Apify scweet actor (requires APIFY_TOKEN, more reliable)
    - "playwright": Use Playwright + browser cookies (free, no token needed)
    """

    enabled: bool = True
    mode: str = "apify"  # "apify" or "playwright"
    users: List[str] = Field(default_factory=list)
    fetch_limit: int = 10
    category: Optional[str] = None
    fetch_reply_text: bool = False
    max_replies_per_tweet: int = 3
    max_tweets_to_expand: int = 10
    reply_min_likes: int = 0
    # Apify settings (used when mode == "apify")
    apify_token_env: str = "APIFY_TOKEN"
    actor_id: str = "altimis~scweet"
    # Playwright settings (used when mode == "playwright")
    cookie_dir: str = "data"
    cookie_file_pattern: str = "x_cookies_*.json"


class OpenBBWatchlist(BaseModel):
    """A named watchlist of tickers fetched from one OpenBB provider.

    Each watchlist produces one news.company() call per run, so group
    symbols by provider rather than creating one watchlist per symbol.
    """

    name: str
    symbols: List[str] = Field(default_factory=list)
    enabled: bool = True
    provider: str = "yfinance"
    fetch_limit: int = 20
    category: Optional[str] = None


class OpenBBConfig(BaseModel):
    """OpenBB Platform source configuration.

    Uses the installed `openbb` SDK to fetch news and filings for a set of
    tickers. The SDK is an optional dependency; if it is not installed the
    scraper will no-op with a console warning rather than crash the run.

    Provider credentials (FMP, Benzinga, Polygon, Intrinio, Tiingo, etc.)
    are resolved by openbb from environment variables / its own user
    settings file, so BMTNews does not need to pass them explicitly.
    """

    enabled: bool = True
    watchlists: List[OpenBBWatchlist] = Field(default_factory=list)
    fetch_filings: bool = False
    filings_provider: str = "sec"


class OSSInsightConfig(BaseModel):
    """OSS Insight trending repos source configuration.

    Pulls top star-gain repositories from the OSS Insight public API and
    emits them as ContentItems. Optional `keywords` filter limits results
    to repos whose description, repo name, or collection names contain at
    least one of the listed substrings (case-insensitive). Leave
    `keywords` empty to ingest everything trending in the configured
    languages.
    """

    enabled: bool = False
    period: str = "past_24_hours"  # past_24_hours, past_28_days
    languages: List[str] = Field(
        default_factory=lambda: ["All", "Python", "TypeScript"]
    )
    keywords: List[str] = Field(default_factory=list)
    min_stars: int = 5
    max_items: int = 30
    category: Optional[str] = None


class GDELTConfig(BaseModel):
    """GDELT 2.0 DOC API source configuration.

    Queries the key-less GDELT DOC API
    (https://api.gdeltproject.org/api/v2/doc/doc) for recent news articles
    matching a search query and emits them as ContentItems. No API key is
    required. The DOC API caps results at 250 records per request, so keep
    `max_records` modest.
    """

    enabled: bool = False
    query: str = "artificial intelligence"
    mode: str = "ArtList"
    max_records: int = 75  # GDELT DOC API caps at 250; keep modest
    timespan: Optional[str] = None  # e.g. "24h"; overrides since-derived window
    language: Optional[str] = None  # sourcelang filter, e.g. "english"; None = no filter
    country: Optional[str] = None  # sourcecountry filter; None = no filter
    category: Optional[str] = None  # BMTNews category label for downstream grouping


class GoogleNewsConfig(BaseModel):
    """Google News RSS search source configuration.

    Builds Google News RSS search URLs
    (https://news.google.com/rss/search) for a query and parses the
    resulting feed via feedparser. No API key is required.
    """

    enabled: bool = False
    query: str = "artificial intelligence"
    language: str = "en"  # hl
    country: str = "US"  # gl
    ceid: Optional[str] = None  # when None scraper derives it as "{country}:{language}"
    max_results: int = 100  # cap ~100
    category: Optional[str] = None


class SourcesConfig(BaseModel):
    """All sources configuration."""

    github: List[GitHubSourceConfig] = Field(default_factory=list)
    hackernews: HackerNewsConfig = Field(default_factory=HackerNewsConfig)
    rss: List[RSSSourceConfig] = Field(default_factory=list)
    reddit: RedditConfig = Field(default_factory=RedditConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    twitter: Optional[TwitterConfig] = None
    openbb: Optional[OpenBBConfig] = None
    ossinsight: OSSInsightConfig = Field(default_factory=OSSInsightConfig)
    gdelt: Optional[GDELTConfig] = None
    google_news: Optional[GoogleNewsConfig] = None


class WebhookConfig(BaseModel):
    """Webhook notification configuration."""

    url_env: Optional[str] = (
        None  # Environment variable name containing the webhook URL
    )
    request_body: Optional[Union[str, dict, list]] = (
        None  # POST body: real JSON object or string with #{key} placeholders; if empty, will use GET
    )
    headers: Optional[str] = None  # Custom headers, "Key: Value" per line
    delivery: str = "summary"  # summary, or summary_and_items
    overview_position: str = "first"  # For summary_and_items: first, or last
    platform: str = "generic"  # generic, feishu, lark, dingtalk, slack, discord
    layout: str = "markdown"  # markdown, or collapsible
    fallback_layout: str = (
        "markdown"  # Layout to use when the requested layout is unsupported
    )
    languages: Optional[List[str]] = (
        None  # Optional language filter for webhook delivery; defaults to all AI languages
    )
    enabled: bool = False

    @field_validator("delivery")
    @classmethod
    def validate_delivery(cls, v: str) -> str:
        allowed = {"summary", "summary_and_items"}
        if v not in allowed:
            raise ValueError(f"webhook.delivery must be one of {allowed}, got '{v}'")
        return v

    @field_validator("platform")
    @classmethod
    def validate_platform(cls, v: str) -> str:
        allowed = {"generic", "feishu", "lark", "dingtalk", "slack", "discord"}
        if v not in allowed:
            raise ValueError(f"webhook.platform must be one of {allowed}, got '{v}'")
        return v

    @field_validator("layout")
    @classmethod
    def validate_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(f"webhook.layout must be one of {allowed}, got '{v}'")
        return v

    @field_validator("fallback_layout")
    @classmethod
    def validate_fallback_layout(cls, v: str) -> str:
        allowed = {"markdown", "collapsible"}
        if v not in allowed:
            raise ValueError(
                f"webhook.fallback_layout must be one of {allowed}, got '{v}'"
            )
        return v

    @field_validator("overview_position")
    @classmethod
    def validate_overview_position(cls, v: str) -> str:
        allowed = {"first", "last"}
        if v not in allowed:
            raise ValueError(
                f"webhook.overview_position must be one of {allowed}, got '{v}'"
            )
        return v


class EmailConfig(BaseModel):
    """Email configuration for updates/subscriptions."""

    imap_server: str
    imap_port: int = 993
    imap_enabled: bool = True
    smtp_server: str
    smtp_port: int = 465
    smtp_username: Optional[str] = None
    email_address: str
    password_env: str = "EMAIL_PASSWORD"
    sender_name: str = "BMTNews"
    subscribe_keyword: str = "SUBSCRIBE"
    unsubscribe_keyword: str = "UNSUBSCRIBE"
    enabled: bool = False


class TelegramDeliveryConfig(BaseModel):
    """Telegram Bot API delivery configuration for published editions."""

    enabled: bool = False
    bot_token_env: str = "TELEGRAM_BOT_TOKEN"
    channel_id_env: str = "TELEGRAM_CHANNEL_ID"
    languages: List[str] = Field(default_factory=lambda: ["zh"])
    site_url: str = "https://bmt.news/"
    required: bool = False
    max_message_chars: int = Field(default=3900, ge=512, le=4096)
    featured_items: int = Field(default=3, ge=0, le=10)
    max_items: int = Field(default=10, ge=1, le=20)

    @field_validator("site_url")
    @classmethod
    def validate_site_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("telegram_delivery.site_url must be an HTTP(S) URL")
        return value

    @model_validator(mode="after")
    def validate_item_limits(self) -> "TelegramDeliveryConfig":
        if self.featured_items > self.max_items:
            raise ValueError(
                "telegram_delivery.featured_items must not exceed max_items"
            )
        return self


class XDeliveryConfig(BaseModel):
    """X (Twitter) distribution for published editions.

    Disabled by default. Posting also requires all four OAuth 1.0a
    credentials in the environment, so enabling the flag alone never
    results in an outward-facing post.
    """

    enabled: bool = False
    consumer_key_env: str = "X_CONSUMER_KEY"
    consumer_secret_env: str = "X_CONSUMER_SECRET"
    access_token_env: str = "X_ACCESS_TOKEN"
    access_secret_env: str = "X_ACCESS_SECRET"
    languages: List[str] = Field(default_factory=lambda: ["zh"])
    site_url: str = "https://bmt.news/"
    max_items: int = Field(default=3, ge=1, le=5)
    required: bool = False
    # "digest" posts one round-up when the edition publishes.
    # "drip" posts the top stories one at a time across the day, driven by
    # the x-distribution workflow; the publish step then posts nothing.
    mode: Literal["digest", "drip"] = "digest"
    drip_items: int = Field(default=4, ge=1, le=8)
    # Where a drip post sends the reader. "none" posts no link at all, which
    # is what X's ranking favours; "site" keeps readers in the briefing and
    # "source" credits the outlet directly.
    link_target: Literal["none", "site", "source"] = "none"
    # "ai" writes each post in the account's voice; "template" assembles it
    # from the stored title and summary without an extra model call. AI
    # composition always falls back to the template on failure.
    compose: Literal["ai", "template"] = "ai"
    # Weighted characters, counted the way X does (CJK counts double).
    # 280 is the standard-account cap; Premium accounts post far longer.
    # The compact brief targets 90-150 Chinese characters. The configured
    # ceiling leaves headroom for Latin names and numbers within that range.
    max_post_chars: int = Field(default=400, ge=280, le=25000)

    @field_validator("site_url")
    @classmethod
    def validate_site_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("x_delivery.site_url must be an HTTP(S) URL")
        return value


class CategoryGroupConfig(BaseModel):
    """A quota group containing one or more source categories."""

    name: Optional[str] = None
    limit: int = Field(gt=0)
    categories: List[str] = Field(min_length=1)


class FilteringConfig(BaseModel):
    """Content filtering configuration."""

    ai_score_threshold: float = 7.0
    time_window_hours: int = 24
    daily_timezone: str = "UTC"
    preserve_daily_items: bool = False
    max_items: Optional[int] = Field(default=None, gt=0)
    category_groups: Dict[str, CategoryGroupConfig] = Field(default_factory=dict)
    default_group: str = "other"
    default_group_limit: Optional[int] = Field(default=None, gt=0)
    primary_groups: List[str] = Field(default_factory=list)
    primary_group_min_items: Optional[int] = Field(default=None, gt=0)
    minimum_candidate_items: Optional[int] = Field(default=None, gt=0)
    minimum_qualified_items: Optional[int] = Field(default=None, gt=0)
    minimum_display_items: Optional[int] = Field(default=None, gt=0)
    low_signal_minimum_items: Optional[int] = Field(default=None, gt=0)
    fallback_window_hours: Optional[int] = Field(default=None, gt=0)
    primary_group_borrow_limit: Optional[int] = Field(default=None, gt=0)
    max_items_per_source: Optional[int] = Field(default=None, gt=0)

    @field_validator("daily_timezone")
    @classmethod
    def validate_daily_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value

    @model_validator(mode="after")
    def validate_primary_group(self) -> "FilteringConfig":
        if (
            self.primary_group_min_items is not None
            or self.primary_group_borrow_limit is not None
        ) and not self.primary_groups:
            raise ValueError(
                "primary_groups is required when a primary group target or "
                "borrow limit is set"
            )
        missing = [
            group
            for group in self.primary_groups
            if group not in self.category_groups
        ]
        if missing:
            raise ValueError(
                "primary_groups must name configured category groups"
            )
        if self.primary_group_min_items is not None:
            capacity = sum(
                self.category_groups[group].limit
                for group in self.primary_groups
            )
            if self.primary_group_min_items > capacity:
                raise ValueError(
                    "primary_group_min_items cannot exceed primary group capacity"
                )
            if (
                self.max_items is not None
                and self.primary_group_min_items > self.max_items
            ):
                raise ValueError("primary_group_min_items cannot exceed max_items")
        if (
            self.minimum_display_items is not None
            and self.max_items is not None
            and self.minimum_display_items > self.max_items
        ):
            raise ValueError("minimum_display_items cannot exceed max_items")
        if (
            self.low_signal_minimum_items is not None
            and self.max_items is not None
            and self.low_signal_minimum_items > self.max_items
        ):
            raise ValueError("low_signal_minimum_items cannot exceed max_items")
        if (
            self.fallback_window_hours is not None
            and self.fallback_window_hours <= max(24, self.time_window_hours)
        ):
            raise ValueError(
                "fallback_window_hours must exceed the 24-hour edition window "
                "and time_window_hours"
            )
        return self


class Config(BaseModel):
    """Main configuration model."""

    version: str = "1.0"
    ai: AIConfig
    sources: SourcesConfig
    filtering: FilteringConfig
    extractors: Dict[str, ExtractorConfig] = Field(default_factory=dict)
    email: Optional[EmailConfig] = None
    webhook: Optional[WebhookConfig] = None
    telegram_delivery: Optional[TelegramDeliveryConfig] = None
    x_delivery: Optional[XDeliveryConfig] = None
