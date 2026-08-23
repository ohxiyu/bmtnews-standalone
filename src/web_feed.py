"""Static HTML rendering for the public daily feed."""

from __future__ import annotations

from datetime import timezone
import html
from typing import Iterable
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from .editorial import EditorialEntry
from .market_snapshot import MarketSnapshot
from .models import ContentItem
from .overview import EditionOverview


_URL_SAFE_CHARS = ":/?#[]@!$&'*,;=~%+"
_CATEGORY_ORDER = ("crypto", "technology", "policy")
_LABELS = {
    "zh": {
        "all": "全部",
        "crypto": "Crypto",
        "technology": "AI 科技",
        "policy": "政策",
        "selection": "本期重要资讯按影响力排序，前三条为本期重点。",
        "ranking": "排行榜",
        "priority": "本期重点",
        "more": "背景、讨论与参考资料",
        "background": "背景",
        "discussion": "社区讨论",
        "references": "参考链接",
        "tags": "标签",
        "empty": "今日暂无达到展示阈值的重要资讯。",
        "editorial": "编辑精选",
        "sponsored": "广告",
        "thread_day": "事件线 · 第 {day} 天",
        "sources_confirmed": "{count} 源确认",
        "single_source": "单一来源",
        "market_impact": "市场影响",
        "overview": "今日脉络",
        "overview_rank": "查看第 {rank} 条",
    },
    "en": {
        "all": "All",
        "crypto": "Crypto",
        "technology": "AI & Tech",
        "policy": "Policy",
        "selection": "Stories are ranked by impact; the first three are the edition highlights.",
        "ranking": "Ranking",
        "priority": "Edition highlight",
        "more": "Background, discussion, and references",
        "background": "Background",
        "discussion": "Discussion",
        "references": "References",
        "tags": "Tags",
        "empty": "No stories met today’s publication threshold.",
        "editorial": "Editor's Pick",
        "sponsored": "Sponsored",
        "thread_day": "Thread · day {day}",
        "sources_confirmed": "{count} sources",
        "single_source": "Single source",
        "market_impact": "Market impact",
        "overview": "Today at a glance",
        "overview_rank": "View story {rank}",
    },
}


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _safe_url(value: object) -> str | None:
    raw = str(value).strip()
    if not raw or any(ord(char) < 32 or ord(char) == 127 for char in raw):
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        parsed.port
    except (TypeError, ValueError):
        return None
    return html.escape(quote(raw, safe=_URL_SAFE_CHARS), quote=True)


def _overview_html(
    overview: EditionOverview | str | None,
    *,
    language: str,
    date: str,
    item_count: int,
) -> str:
    """Render a static orientation section with optional story anchors."""
    if overview is None:
        return ""
    if isinstance(overview, str):
        headline = overview.strip()
        signals = ()
    else:
        headline = overview.headline.strip()
        signals = overview.signals
    if not headline:
        return ""

    labels = _LABELS[language]
    signal_items: list[str] = []
    for signal in signals:
        if signal.item_rank < 1 or signal.item_rank > item_count:
            continue
        target = f"{language}-{date}-item-{signal.item_rank}"
        rank = f"#{signal.item_rank:02d}"
        signal_items.append(
            '<li class="edition-overview-signal">'
            f'<span class="edition-overview-signal-label">{_escape(signal.label)}</span>'
            f'<span class="edition-overview-signal-text">{_escape(signal.text)}</span>'
            f'<a class="edition-overview-rank" href="#{_escape(target)}" '
            f'aria-label="{_escape(labels["overview_rank"].format(rank=rank))}">'
            f"{rank}</a></li>"
        )
    signals_html = (
        '<ul class="edition-overview-signals">'
        f'{"".join(signal_items)}</ul>'
        if signal_items
        else ""
    )
    return (
        '<section class="edition-overview" aria-label="'
        f'{_escape(labels["overview"])}">'
        f'<h2 class="edition-overview-title">{_escape(labels["overview"])}</h2>'
        f'<p class="edition-overview-headline">{_escape(headline)}</p>'
        f"{signals_html}</section>"
    )


def _top_level_category(item: ContentItem) -> str:
    category = str(item.metadata.get("category") or "").strip().lower()
    if (
        category.startswith(("ai-", "tech-"))
        or category in {"ai", "technology", "tech-community"}
    ):
        return "technology"
    if (
        "regulation" in category
        or category.startswith(("macro-", "policy"))
        or category == "policy"
    ):
        return "policy"
    return "crypto"


def _score_value(item: ContentItem) -> float:
    return float(item.ai_score or 0)


def _score_tier(score: float) -> str:
    if score >= 9:
        return "high"
    if score >= 7:
        return "good"
    if score >= 5:
        return "mid"
    return "low"


def _localized_text(item: ContentItem, key: str, language: str) -> str:
    metadata = item.metadata
    return str(
        metadata.get(f"{key}_{language}")
        or metadata.get(key)
        or ""
    ).strip()


def _localized_title(item: ContentItem, language: str) -> str:
    return str(
        item.metadata.get(f"title_{language}")
        or item.title
    ).strip()


def _source_html(
    item: ContentItem,
    *,
    language: str,
    display_timezone: ZoneInfo,
) -> str:
    labels = _LABELS[language]
    metadata = item.metadata
    source_name = (
        metadata.get("feed_name")
        or (
            f"r/{metadata['subreddit']}"
            if metadata.get("subreddit")
            else None
        )
        or item.author
        or "unknown"
    )
    story_url = _safe_url(item.url)
    source_label = _escape(source_name)
    if story_url:
        source_label = (
            f'<a class="source-link" href="{story_url}" '
            'target="_blank" rel="noopener noreferrer">'
            f"{source_label}</a>"
        )

    published_at = item.published_at
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    published_at = published_at.astimezone(display_timezone)
    if language == "zh":
        published_label = (
            f"{published_at.month}月{published_at.day}日 "
            f"{published_at:%H:%M}"
        )
    else:
        day = published_at.strftime("%d").lstrip("0")
        published_label = published_at.strftime(f"%b {day}, %H:%M")

    parts = [
        _escape(item.source_type.value),
        source_label,
        (
            f'<time datetime="{_escape(published_at.isoformat())}">'
            f"{_escape(published_label)}</time>"
        ),
    ]
    discussion_url = metadata.get("discussion_url")
    safe_discussion_url = _safe_url(discussion_url) if discussion_url else None
    if (
        safe_discussion_url
        and str(discussion_url) != str(item.url)
    ):
        parts.append(
            f'<a href="{safe_discussion_url}" target="_blank" '
            f'rel="noopener noreferrer">{labels["discussion"]}</a>'
        )
    return " · ".join(parts)


def _references_html(item: ContentItem, language: str) -> str:
    references = item.metadata.get("sources") or []
    if not references:
        return ""
    entries: list[str] = []
    for reference in references:
        title = _escape(reference.get("title") or reference.get("url") or "")
        url = _safe_url(reference.get("url") or "")
        if url:
            entries.append(
                f'<li><a href="{url}" target="_blank" '
                f'rel="noopener noreferrer">{title}</a></li>'
            )
        elif title:
            entries.append(f"<li>{title}</li>")
    if not entries:
        return ""
    return (
        f'<section><h3>{_LABELS[language]["references"]}</h3>'
        f'<ul>{"".join(entries)}</ul></section>'
    )


def _provenance_html(item: ContentItem, language: str) -> str:
    """Show how many independent sources carried the same story."""
    labels = _LABELS[language]
    merged = item.metadata.get("merged_sources")
    names = [str(name) for name in merged if name] if isinstance(merged, list) else []
    count = len(names)
    if count > 1:
        text = labels["sources_confirmed"].format(count=count)
        # The outlet names make the claim checkable rather than a bare number.
        title = _escape(" · ".join(names[:6]))
        return (
            f'<span class="provenance is-confirmed" title="{title}">'
            f"{_escape(text)}</span>"
        )
    return (
        f'<span class="provenance">{_escape(labels["single_source"])}</span>'
    )


def _thread_html(item: ContentItem, language: str) -> str:
    """Link a continuing story to its thread page."""
    thread_id = item.metadata.get("thread_id")
    day = item.metadata.get("thread_day") or 1
    if not thread_id or not isinstance(day, int) or day < 2:
        return ""
    labels = _LABELS[language]
    prefix = "" if language == "zh" else "/en"
    text = labels["thread_day"].format(day=day)
    return (
        f'<a class="thread-pill" href="{prefix}/threads/{_escape(thread_id)}/">'
        f"{_escape(text)}</a>"
    )


def _details_html(item: ContentItem, language: str) -> str:
    labels = _LABELS[language]
    sections: list[str] = []
    background = _localized_text(item, "background", language)
    discussion = _localized_text(item, "community_discussion", language)
    market_impact = _localized_text(item, "market_impact", language)
    if market_impact:
        sections.append(
            f'<section><h3>{labels["market_impact"]}</h3>'
            f"<p>{_escape(market_impact)}</p></section>"
        )
    if background:
        sections.append(
            f'<section><h3>{labels["background"]}</h3>'
            f"<p>{_escape(background)}</p></section>"
        )
    if discussion:
        sections.append(
            f'<section><h3>{labels["discussion"]}</h3>'
            f"<p>{_escape(discussion)}</p></section>"
        )
    references = _references_html(item, language)
    if references:
        sections.append(references)
    if item.ai_tags:
        tags = "".join(
            f"<code>#{_escape(tag)}</code>"
            for tag in item.ai_tags
        )
        sections.append(
            f'<section class="tag-line"><h3>{labels["tags"]}</h3>'
            f"<p>{tags}</p></section>"
        )
    if not sections:
        return ""
    return (
        '<details class="story-more">'
        f"<summary>{labels['more']}</summary>"
        f'<div class="story-more-content">{"".join(sections)}</div>'
        "</details>"
    )


def _render_article(
    item: ContentItem,
    *,
    index: int,
    date: str,
    language: str,
    display_timezone: ZoneInfo,
) -> tuple[str, str]:
    labels = _LABELS[language]
    category = _top_level_category(item)
    score = _score_value(item)
    score_label = f"{score:.1f}" if item.ai_score is not None else "—"
    title = _escape(_localized_title(item, language))
    story_url = _safe_url(item.url)
    title_html = title
    if story_url:
        title_html = (
            f'<a href="{story_url}" target="_blank" '
            f'rel="noopener noreferrer">{title}</a>'
        )
    summary = (
        _localized_text(item, "detailed_summary", language)
        or str(item.ai_summary or "").strip()
    )
    article_id = f"{language}-{date}-item-{index}"
    priority = ""
    priority_class = ""
    if item.metadata.get("editorial"):
        priority = (
            f'<span class="editorial-pill">{labels["editorial"]}</span>'
        )
        priority_class = " is-priority"
    elif index <= 3:
        priority = f'<span class="priority-pill">{labels["priority"]}</span>'
        priority_class = " is-priority"

    article = (
        f'<article class="digest-item{priority_class}" id="{article_id}" '
        f'data-category="{category}" data-score="{score:.1f}">'
        '<div class="digest-item-rail">'
        f"<strong>#{index:02d}</strong>"
        f'<time datetime="{date}">{_escape(date[5:].replace("-", "."))}</time>'
        "</div>"
        '<div class="digest-item-content">'
        '<div class="digest-item-meta"><div>'
        f'<span class="category-pill" data-category="{category}">'
        f"{labels[category]}</span>{priority}"
        f"{_thread_html(item, language)}</div>"
        f'<span class="score-badge" data-tier="{_score_tier(score)}" '
        f'aria-label="Score {score_label} out of 10">{score_label}</span>'
        "</div>"
        f"<h2>{title_html}</h2>"
        f'<p class="story-summary-body">{_escape(summary)}</p>'
        f'<p class="source-line">'
        f"{_source_html(item, language=language, display_timezone=display_timezone)}"
        f" · {_provenance_html(item, language)}</p>"
        f"{_details_html(item, language)}"
        "</div>"
        "</article>"
    )
    headline = (
        f'<li data-category="{category}">'
        f'<a href="#{article_id}">{title}</a>'
        f'<span class="score-badge" data-tier="{_score_tier(score)}">'
        f"{score_label}</span></li>"
    )
    return article, headline


def _market_snapshot_html(
    market: MarketSnapshot | None,
    language: str,
) -> str:
    if market is None:
        return ""

    def _asset(symbol: str, price: float, change: float | None) -> str:
        change_html = ""
        if change is not None:
            direction = "up" if change >= 0 else "down"
            change_html = (
                f' <span class="market-change" data-direction="{direction}">'
                f"{change:+.1f}%</span>"
            )
        return (
            '<span class="market-asset">'
            f"<strong>{symbol}</strong> ${price:,.0f}{change_html}</span>"
        )

    parts = [
        _asset("BTC", market.btc_price, market.btc_change_24h),
        _asset("ETH", market.eth_price, market.eth_change_24h),
    ]
    if market.fear_greed_value is not None:
        fg_name = "恐惧贪婪" if language == "zh" else "Fear & Greed"
        label = market.fear_greed_label_for(language)
        label_html = f" {_escape(label)}" if label else ""
        parts.append(
            '<span class="market-asset">'
            f"<strong>{fg_name}</strong> {market.fear_greed_value}"
            f"{label_html}</span>"
        )
    return (
        '<div class="market-snapshot" role="note">'
        + "".join(parts)
        + "</div>"
    )


def _render_sponsored(entry: EditorialEntry, language: str) -> str:
    """Render one clearly-labeled ad slot outside the ranking."""
    labels = _LABELS[language]
    title = _escape(entry.best_title(language))
    summary = entry.best_summary(language)
    url = _safe_url(entry.url)
    title_html = title
    if url:
        title_html = (
            f'<a href="{url}" target="_blank" '
            f'rel="noopener noreferrer sponsored">{title}</a>'
        )
    summary_html = (
        f'<p class="sponsored-summary">{_escape(summary)}</p>' if summary else ""
    )
    return (
        f'<aside class="sponsored-slot" aria-label="{labels["sponsored"]}">'
        f'<span class="sponsored-label">{labels["sponsored"]}</span>'
        '<div class="sponsored-body">'
        f"<h2>{title_html}</h2>"
        f"{summary_html}"
        "</div></aside>"
    )


def render_web_feed(
    items: Iterable[ContentItem],
    *,
    date: str,
    total_fetched: int,
    language: str,
    display_timezone: str,
    overview: EditionOverview | str | None = None,
    market: MarketSnapshot | None = None,
    sponsored: Iterable[EditorialEntry] | None = None,
) -> str:
    """Render the final feed markup so browsers do not rebuild the DOM."""
    normalized_language = "en" if language.lower().startswith("en") else "zh"
    labels = _LABELS[normalized_language]
    feed_items = list(items)
    if not feed_items:
        return (
            '<div class="feed-rendered-static empty-state" '
            'data-feed-render-version="2">'
            f"{labels['empty']}</div>\n"
        )

    timezone_info = ZoneInfo(display_timezone)
    categories = [_top_level_category(item) for item in feed_items]
    counts = {
        category: categories.count(category)
        for category in _CATEGORY_ORDER
    }
    filter_buttons = [
        (
            '<button class="active" type="button" data-category="all" '
            'aria-pressed="true">'
            f'{labels["all"]}<span>{len(feed_items)}</span></button>'
        )
    ]
    for category in _CATEGORY_ORDER:
        if not counts[category]:
            continue
        filter_buttons.append(
            '<button type="button" '
            f'data-category="{category}" aria-pressed="false">'
            f'{labels[category]}<span>{counts[category]}</span></button>'
        )

    articles: list[str] = []
    headlines: list[str] = []
    for index, item in enumerate(feed_items, start=1):
        article, headline = _render_article(
            item,
            index=index,
            date=date,
            language=normalized_language,
            display_timezone=timezone_info,
        )
        articles.append(article)
        headlines.append(headline)

    # At most one labeled ad slot, outside the ranking and the filters.
    sponsored_entries = list(sponsored or [])[:1]
    for entry in sponsored_entries:
        slot_html = _render_sponsored(entry, normalized_language)
        position = entry.position if entry.position and entry.position > 0 else 4
        articles.insert(min(position - 1, len(articles)), slot_html)

    selection_note = labels["selection"]
    if normalized_language == "zh":
        selection_note += f" 本期从 {total_fetched} 条候选中展示 {len(feed_items)} 条。"
    else:
        selection_note += (
            f" This edition displays {len(feed_items)} of "
            f"{total_fetched} candidates."
        )
    display_date = date.replace("-", ".")
    overview_html = _overview_html(
        overview,
        language=normalized_language,
        date=date,
        item_count=len(feed_items),
    )
    return (
        '<div class="feed-toolbar feed-rendered-static" '
        'data-feed-render-version="2">'
        f"{_market_snapshot_html(market, normalized_language)}"
        f"{overview_html}"
        f'<p class="feed-selection-note">{_escape(selection_note)}</p>'
        '<div class="digest-filter-host">'
        '<div class="category-filters" data-static-filters>'
        f'{"".join(filter_buttons)}'
        "</div></div></div>"
        '<div class="daily-feed-layout">'
        f'<div class="daily-story-stream">{"".join(articles)}</div>'
        f'<aside class="headline-rail" aria-label="{labels["ranking"]}">'
        '<details class="headline-index" open>'
        f'<summary><span>{display_date} {labels["ranking"]}</span>'
        f"<small>{len(feed_items)}</small></summary>"
        f'<ol class="headline-list">{"".join(headlines)}</ol>'
        "</details></aside></div>\n"
    )
