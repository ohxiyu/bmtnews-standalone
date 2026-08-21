"""Story threads and entity extraction derived from the archive.

A *thread* groups coverage of one continuing event across days ("Bybit
hacked" → "Bybit sues North Korea"), so a reader can follow a story instead
of seeing disconnected daily items. Matching is deterministic and offline:
it compares normalized tag and title tokens, with no extra AI calls.

An *entity* is a recurring tag (Binance, Lazarus Group, SEC, ...). Entities
with enough mentions get their own aggregated page.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta
from typing import Dict, Iterable, List, Optional, Sequence

from .archive import ArchiveRecord


def _as_date(value: str) -> Optional[date_type]:
    try:
        return date_type.fromisoformat(value)
    except (TypeError, ValueError):
        return None

# Tokens that carry no discriminating power for thread matching.
_STOPWORDS = {
    "about", "after", "against", "amid", "announce", "announced",
    "announcement", "another", "over", "with", "from", "into", "that",
    "this", "their", "there", "these", "those", "will", "would", "could",
    "have", "has", "been", "being", "more", "most", "than", "then", "they",
    "what", "when", "where", "which", "while", "your", "news", "report",
    "reports", "update", "updates", "says", "said", "new", "now",
    "crypto", "cryptocurrency", "blockchain", "market", "markets",
}

# Tags too generic to deserve an entity page.
_GENERIC_TAGS = {
    "ai", "ai-safety", "blockchain", "crypto", "cryptocurrency", "defi",
    "engineering", "exchange", "exchange-announcements",
    "exchange-operations", "crypto-markets", "crypto-protocols",
    "crypto-regulation", "macro-regulation", "markets", "news", "onchain",
    "regulation", "security", "stablecoin", "technology", "trading",
}

# Capitalized words and acronyms are the closest thing to a named entity
# available without an NER model, and Chinese copy keeps brand names in
# Latin script ("Bybit 被盗"), so the same extraction works on both.
_ACRONYM = re.compile(r"[A-Z]{2,}[0-9]*")
_CAPITALIZED = re.compile(r"[A-Z][A-Za-z0-9]{2,}")
_SENTENCE_SPLIT = re.compile(r"[.!?;:\n。！？；]\s*")
_EDGE_PUNCTUATION = "\"'“”‘’()[]{}<>,、·—–-"

# Capitalized words that name no one: sentence openers, months, and the
# domain vocabulary that appears in most headlines here.
_ANCHOR_STOPWORDS = {
    "after", "amid", "and", "another", "back", "but", "could", "days",
    "first", "for", "from", "has", "have", "how", "into", "its", "last",
    "more", "most", "new", "news", "next", "not", "now", "over", "report",
    "reports", "said", "says", "than", "that", "the", "their", "then",
    "these", "this", "those", "top", "update", "updates", "what", "when",
    "where", "which", "while", "who", "why", "will", "with", "would",
    "your",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
    "ai", "altcoin", "altcoins", "bitcoin", "blockchain", "billion",
    "btc", "capital", "ceo", "cfo", "chain", "coin", "coins", "company",
    "crypto", "cryptocurrency", "cto", "dao", "data", "defi", "eth",
    "ether", "ethereum", "etf", "etfs", "exchange", "exchanges",
    "exploit", "exploits", "fund", "funds", "hack", "hacked", "hacker",
    "hackers", "inc", "launch", "launches", "llc", "ltd", "market",
    "markets", "million", "model", "models", "network", "nft", "nfts",
    "onchain", "policy", "price", "prices", "protocol", "regulation",
    "regulator", "regulators", "security", "stablecoin", "stablecoins",
    "team", "technology", "token", "tokens", "trader", "traders",
    "trading", "usd", "usdc", "usdt", "users", "wallet", "wallets",
    "web3",
    "eu", "uk", "us", "usa",
}

_CJK = re.compile(r"[一-鿿㐀-䶿]{2,}")
_WORD = re.compile(r"[a-z0-9]+")


def clean_label(tag: str) -> str:
    """Sanitize a model-generated tag for display.

    Entity labels reach page front matter and therefore the raw ``<title>``
    element, so markup characters are stripped at the source rather than
    relying on every downstream renderer to escape them.
    """
    text = unicodedata.normalize("NFKC", str(tag or "")).strip().lstrip("#")
    text = re.sub(r"[<>\"'&`]", "", text)
    text = re.sub(r"\s+", " ", text).strip()[:60]
    # Tags arrive as lowercase slugs ("lazarus-group"), which reads as a
    # machine label rather than a name once it is a page heading.
    if text and text == text.lower() and re.fullmatch(r"[a-z0-9 -]+", text):
        text = " ".join(
            word.capitalize() for word in text.replace("-", " ").split()
        )
    return text


def normalize_tag(tag: str) -> str:
    """Lowercase, ASCII-fold, and hyphenate a tag into a stable slug."""
    text = unicodedata.normalize("NFKC", str(tag or "")).strip().lstrip("#")
    text = text.lower()
    text = re.sub(r"[\s_/]+", "-", text)
    text = re.sub(r"[^a-z0-9一-鿿-]", "", text)
    return re.sub(r"-{2,}", "-", text).strip("-")


def _title_tokens(title: str) -> set[str]:
    tokens = {
        word
        for word in _WORD.findall(title.lower())
        if len(word) >= 4 and word not in _STOPWORDS
    }
    for run in _CJK.findall(title):
        tokens.update(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def _is_title_case(words: Sequence[str]) -> bool:
    """Whether a run of words is a Title Case headline rather than prose.

    "Bybit Wins US Court Order Freezing Assets" capitalizes everything, so
    capitalization there says nothing about which words are names.
    """
    candidates = [word for word in words if len(word) >= 3 and word[:1].isalpha()]
    if len(candidates) < 4:
        return False
    capitalized = sum(1 for word in candidates if word[:1].isupper())
    return capitalized / len(candidates) >= 0.6


def _proper_nouns(text: str, *, skip_sentence_initial: bool) -> set[str]:
    """Capitalized words that plausibly name something.

    English prose capitalizes the first word of every sentence, so those are
    skipped there — that is where "According", "Following" and friends come
    from. Chinese copy has no such rule and routinely opens with the brand
    ("Bybit 遭盗窃"), so the first word counts there.

    Title Case sentences contribute only their acronyms; the names in a
    headline are recovered from the sentence-case summary instead.
    """
    names: set[str] = set()
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        words = [
            word
            for word in (
                raw.strip(_EDGE_PUNCTUATION) for raw in sentence.split()
            )
            if word
        ]
        title_case = _is_title_case(words)
        for index, word in enumerate(words):
            for possessive in ("'s", "’s"):
                if word.endswith(possessive):
                    word = word[: -len(possessive)]
            if _ACRONYM.fullmatch(word):
                names.add(word.lower())
                continue
            if title_case:
                continue
            if skip_sentence_initial and index == 0:
                continue
            if _CAPITALIZED.fullmatch(word):
                names.add(word.lower())
    return names


def _anchor_names(text_en: str, text_zh: str, tags: set[str]) -> set[str]:
    """Named actors in a story: companies, protocols, regulators, people.

    Anchors are what makes "Bybit hacked" and "Bybit sues Lazarus" the same
    thread. Token overlap alone cannot see it — one shared brand name is
    diluted to nothing by a dozen unrelated tokens — so the names are pulled
    out and compared separately.
    """
    anchors = _proper_nouns(text_en, skip_sentence_initial=True)
    anchors |= _proper_nouns(text_zh, skip_sentence_initial=False)
    anchors = {
        word for word in anchors if word not in _ANCHOR_STOPWORDS and len(word) >= 2
    }

    # A tag counts as an anchor only when a headline actually names it, which
    # separates entity tags ("coldcard") from descriptive ones ("market-
    # shakeout") without needing a curated list of either.
    compact_zh = re.sub(r"\s+", "", text_zh or "")
    for slug in tags:
        if _CJK.search(slug):
            # A Chinese-named entity ("美联储") has no Latin form to match, so
            # it is confirmed against the Chinese text directly.
            if slug in compact_zh:
                anchors.add(slug)
            continue
        parts = [part for part in slug.split("-") if len(part) >= 3]
        if parts and all(part in anchors for part in parts):
            anchors.add(slug)
    return anchors


@dataclass
class StoryFingerprint:
    """Comparable token sets for one story."""

    tags: set[str] = field(default_factory=set)
    tokens: set[str] = field(default_factory=set)
    anchors: set[str] = field(default_factory=set)
    #: Anchors named in the headline. A story that is genuinely about an
    #: actor says so in the title; an actor mentioned only in passing in the
    #: body ("... much like Hyperliquid") is not what the story is about.
    lead_anchors: set[str] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        return not (self.tags or self.tokens)


def fingerprint(
    *,
    title_zh: str = "",
    title_en: str = "",
    summary_zh: str = "",
    summary_en: str = "",
    tags: Iterable[str] = (),
) -> StoryFingerprint:
    """Build the comparable token sets for one story.

    Summaries are folded in alongside titles because a headline alone is too
    thin to link continuing coverage: day two of an event is usually written
    with an entirely different headline, and only the summary still mentions
    what happened on day one.
    """
    normalized_tags = {
        slug for slug in (normalize_tag(tag) for tag in tags) if slug
    }
    text_en = " ".join(filter(None, (title_en, summary_en)))
    text_zh = " ".join(filter(None, (title_zh, summary_zh)))
    tokens = set(normalized_tags)
    tokens |= _title_tokens(text_en)
    tokens |= _title_tokens(text_zh)
    anchors = _anchor_names(text_en, text_zh, normalized_tags)
    return StoryFingerprint(
        tags=normalized_tags,
        tokens=tokens,
        anchors=anchors,
        lead_anchors=_anchor_names(title_en, title_zh, normalized_tags) & anchors,
    )


def fingerprint_of_record(record: ArchiveRecord) -> StoryFingerprint:
    return fingerprint(
        title_zh=record.title_zh,
        title_en=record.title_en,
        summary_zh=record.summary_zh,
        summary_en=record.summary_en,
        tags=record.tags,
    )


def _overlap(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def common_tokens(
    fingerprints: Sequence[StoryFingerprint],
    *,
    document_ratio: float = 0.25,
    minimum_documents: int = 12,
) -> set[str]:
    """Tokens so common in the corpus that sharing one means nothing.

    Every story in this feed mentions 美元, 代币, protocol, token. Chinese is
    tokenized into bigrams, which makes the problem worse: two unrelated
    crypto stories reliably share a dozen of them. Rather than curate a
    stoplist in two languages, the corpus is asked directly which tokens are
    everywhere — the archive is right there, and it adapts as coverage
    shifts.

    Below ``minimum_documents`` the corpus is too small to estimate this, so
    nothing is suppressed.
    """
    if len(fingerprints) < minimum_documents:
        return set()
    counts: Dict[str, int] = {}
    for print_ in fingerprints:
        for token in print_.tokens:
            counts[token] = counts.get(token, 0) + 1
    ceiling = max(2, int(len(fingerprints) * document_ratio))
    return {token for token, count in counts.items() if count > ceiling}


def thread_affinity(
    left: StoryFingerprint,
    right: StoryFingerprint,
    *,
    strong_tag_matches: int = 2,
    strong_threshold: float = 0.30,
    loose_threshold: float = 0.55,
    pair_context: int = 2,
    single_context: int = 6,
    ignore: Optional[set[str]] = None,
) -> float:
    """Score how strongly two stories continue the same event; 0 means no.

    Four independent signals, any one of which links the stories: two shared
    named actors plus a little shared context, one shared named actor plus
    substantial shared context, several shared tags with moderate token
    overlap, or high token overlap on its own. Only actors named in *both*
    headlines count, because an actor mentioned once in a body paragraph is
    not what either story is about. ``ignore`` carries the corpus
    tokens from :func:`common_tokens`, without which "shared context" is
    mostly boilerplate every crypto story has in common.

    The anchor rules exist because the ratio-based rules never fire on real
    continuing coverage: day two is worded differently, so a headline pair
    shares little beyond the name, and the ratio is dominated by the tokens
    that differ. Counting *shared context* — tokens in common that are not
    themselves the shared name — separates "Bybit hacked → Bybit recovers
    funds" (same event, much shared detail) from "Coinbase revenue →
    Coinbase listings" (same company, nothing else in common), which no
    threshold on a ratio can do.

    The returned score only ranks candidates against each other; the
    thresholds, not the score, decide whether there is a link at all.
    """
    if left.is_empty or right.is_empty:
        return 0.0
    # At least one shared actor has to be named in both headlines; once that
    # holds, actors named anywhere in either story count towards the total.
    # Without the headline gate, one passing mention in a body paragraph
    # ("... much like Hyperliquid") links two unrelated stories; with it as
    # the only rule, a second-day headline that drops a name loses evidence
    # the summary still carries.
    shared_anchors = (
        len(left.anchors & right.anchors)
        if left.lead_anchors & right.lead_anchors
        else 0
    )
    shared_tags = len(left.tags & right.tags)
    overlap = _overlap(left.tokens, right.tokens)
    context = (left.tokens & right.tokens) - left.anchors - right.anchors
    if ignore:
        context -= ignore
    context_size = len(context)

    linked = (
        (shared_anchors >= 2 and context_size >= pair_context)
        or (shared_anchors >= 1 and context_size >= single_context)
        or (shared_tags >= strong_tag_matches and overlap >= strong_threshold)
        or overlap >= loose_threshold
    )
    if not linked:
        return 0.0
    return shared_anchors + 0.5 * shared_tags + overlap


def same_thread(
    left: StoryFingerprint,
    right: StoryFingerprint,
    **thresholds: float,
) -> bool:
    """Whether two stories continue the same event.

    Deliberately conservative on every signal: a missed link only costs a
    badge, while a wrong link merges two unrelated stories into one page.
    """
    return thread_affinity(left, right, **thresholds) > 0.0


def thread_id_for(seed_url: str) -> str:
    """Stable thread id derived from the first story's URL."""
    digest = hashlib.sha256(seed_url.encode("utf-8")).hexdigest()[:10]
    return f"t{digest}"


@dataclass
class ThreadAssignment:
    """Thread membership computed for one story."""

    thread_id: str
    day: int
    previous_dates: List[str] = field(default_factory=list)

    @property
    def is_continuation(self) -> bool:
        return self.day > 1


def assign_threads(
    stories: Sequence[tuple[str, StoryFingerprint]],
    history: Sequence[ArchiveRecord],
    *,
    edition_date: str,
    max_gap_days: int = 14,
) -> Dict[str, ThreadAssignment]:
    """Map each story key to its thread, linking into archived coverage.

    ``stories`` is a sequence of ``(key, fingerprint)`` pairs where ``key``
    identifies the story (its URL). ``history`` should already be limited
    to a recent window by the caller; ``max_gap_days`` additionally stops a
    long-dormant story from being resurrected into today's thread.
    """
    cutoff: Optional[date_type] = None
    today = _as_date(edition_date)
    if today is not None:
        cutoff = today - timedelta(days=max_gap_days)

    history_prints = [
        (record, fingerprint_of_record(record))
        for record in history
        if record.date != edition_date
        and (cutoff is None or (record.date_value or cutoff) >= cutoff)
    ]
    # Estimated over the whole corpus in play, so the boilerplate every
    # crypto story shares stops counting as evidence of a shared story.
    ignore = common_tokens(
        [print_ for _, print_ in history_prints]
        + [print_ for _, print_ in stories]
    )

    # Existing threads: id -> dates already published under it.
    thread_dates: Dict[str, set[str]] = {}
    for record in history:
        if record.thread_id:
            thread_dates.setdefault(record.thread_id, set()).add(record.date)

    assignments: Dict[str, ThreadAssignment] = {}
    for key, print_ in stories:
        if print_.is_empty:
            continue
        matched_id: Optional[str] = None
        matched_dates: set[str] = set()

        # Take the strongest archived match, not merely the most recent one:
        # a weak same-day-adjacent link used to win over the story this is
        # actually a continuation of.
        best: Optional[tuple[float, str, ArchiveRecord]] = None
        for record, record_print in history_prints:
            score = thread_affinity(print_, record_print, ignore=ignore)
            if score <= 0.0:
                continue
            if best is None or (score, record.date) > (best[0], best[1]):
                best = (score, record.date, record)
        if best is not None:
            record = best[2]
            matched_id = record.thread_id or thread_id_for(record.url)
            matched_dates = set(thread_dates.get(matched_id, set()))
            matched_dates.add(record.date)

        # Otherwise join a same-edition sibling so one event stays one thread.
        if matched_id is None:
            sibling_best: Optional[tuple[float, str]] = None
            for other_key, other_print in stories:
                if other_key == key or other_key not in assignments:
                    continue
                score = thread_affinity(print_, other_print, ignore=ignore)
                if score <= 0.0:
                    continue
                if sibling_best is None or score > sibling_best[0]:
                    sibling_best = (score, other_key)
            if sibling_best is not None:
                sibling = assignments[sibling_best[1]]
                matched_id = sibling.thread_id
                matched_dates = set(sibling.previous_dates)

        if matched_id is None:
            matched_id = thread_id_for(key)

        previous = sorted(date for date in matched_dates if date != edition_date)
        assignments[key] = ThreadAssignment(
            thread_id=matched_id,
            day=len(previous) + 1,
            previous_dates=previous,
        )
    return assignments


@dataclass
class EntitySummary:
    """Aggregated mentions of one recurring entity."""

    slug: str
    label: str
    count: int
    records: List[ArchiveRecord] = field(default_factory=list)


def collect_entities(
    records: Sequence[ArchiveRecord],
    *,
    # Two mentions is the point at which a name stops being a one-off. At
    # three, an index over ~10 stories a day takes the better part of a week
    # to show anything, which reads as broken rather than as selective.
    minimum_mentions: int = 2,
    limit: int = 60,
) -> List[EntitySummary]:
    """Group archive records by recurring named actor.

    A tag only counts when a headline of that story actually names it. That
    is what separates an entity ("Coldcard", "Bybit") from a descriptive tag
    the model attached ("exploits", "hardware-wallet"): the index is meant to
    answer "what has been written about this company" and a topic word
    quietly turns it back into a tag cloud.
    """
    buckets: Dict[str, EntitySummary] = {}
    for record in records:
        named = fingerprint_of_record(record).lead_anchors
        seen: set[str] = set()
        for tag in record.tags:
            slug = normalize_tag(tag)
            if not slug or slug in _GENERIC_TAGS or len(slug) < 3:
                continue
            if slug not in named:
                continue
            if slug in seen:
                continue
            seen.add(slug)
            entity = buckets.get(slug)
            if entity is None:
                entity = EntitySummary(
                    slug=slug,
                    label=clean_label(tag) or slug,
                    count=0,
                )
                buckets[slug] = entity
            entity.count += 1
            entity.records.append(record)

    entities = [
        entity for entity in buckets.values() if entity.count >= minimum_mentions
    ]
    entities.sort(key=lambda entity: (-entity.count, entity.slug))
    for entity in entities:
        entity.records.sort(key=lambda record: (record.date, record.rank), reverse=True)
    return entities[:limit]


def collect_threads(
    records: Sequence[ArchiveRecord],
    *,
    minimum_days: int = 2,
    limit: int = 80,
) -> List[tuple[str, List[ArchiveRecord]]]:
    """Return multi-day threads, newest activity first."""
    buckets: Dict[str, List[ArchiveRecord]] = {}
    for record in records:
        if record.thread_id:
            buckets.setdefault(record.thread_id, []).append(record)

    threads = []
    for thread_id, thread_records in buckets.items():
        if len({record.date for record in thread_records}) < minimum_days:
            continue
        thread_records.sort(key=lambda record: (record.date, record.rank))
        threads.append((thread_id, thread_records))
    threads.sort(key=lambda pair: pair[1][-1].date, reverse=True)
    return threads[:limit]
