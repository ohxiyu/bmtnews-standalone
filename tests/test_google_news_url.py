"""Tests for Google News redirect link resolution."""

import base64

from src.scrapers.google_news_url import (
    canonicalize_entry_link,
    resolve_google_news_url,
)


def _make_token(url: str) -> str:
    payload = url.encode("utf-8")
    raw = b"\x08\x13\x22" + bytes([len(payload)]) + payload
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def test_resolves_decodable_article_token():
    article = "https://www.anthropic.com/news/some-announcement"
    link = f"https://news.google.com/rss/articles/{_make_token(article)}?oc=5"
    assert resolve_google_news_url(link) == article
    assert canonicalize_entry_link(link) == article


def test_resolves_non_rss_article_path():
    article = "https://example.com/story"
    link = f"https://news.google.com/articles/{_make_token(article)}"
    assert resolve_google_news_url(link) == article


def test_keeps_opaque_new_style_token():
    # New AU_yqL… tokens embed an opaque string, not a URL; the original
    # link must be preserved.
    link = (
        "https://news.google.com/rss/articles/"
        "CBMieEFVX3lxTE95RXUtcVFIR1hIbmVDRk5sRDZEVWZSRTlXNXRMU1RXQk1JdE1k"
        "RzBMR3RuOGhzOVRZdEs2bGRIX3JIa1ZZbjlCbGx5RzlZRGdQZ3RwLXVidjZyZUpX"
        "eU1sM0hYeTQ2QW0zOXlCWnJQenFhZ0dEUFNFUA?oc=5"
    )
    assert resolve_google_news_url(link) is None
    assert canonicalize_entry_link(link) == link


def test_ignores_non_google_hosts():
    assert resolve_google_news_url("https://example.com/articles/CBMi") is None


def test_rejects_embedded_google_news_url():
    nested = "https://news.google.com/foo"
    link = f"https://news.google.com/rss/articles/{_make_token(nested)}"
    assert resolve_google_news_url(link) is None


def test_handles_garbage_tokens():
    assert (
        resolve_google_news_url("https://news.google.com/rss/articles/!!!")
        is None
    )
    assert (
        resolve_google_news_url("https://news.google.com/rss/articles/AAAA")
        is None
    )
