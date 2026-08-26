"""Static and generated contracts that make the public site agent-readable."""

import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

from bs4 import BeautifulSoup


ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"


def test_immutable_public_assets_use_content_fingerprint() -> None:
    """Fail when long-lived assets change without a new cache key."""
    head = (DOCS / "_includes" / "head-custom.html").read_text(encoding="utf-8")
    headers = (DOCS / "_headers").read_text(encoding="utf-8")
    asset_cache_rule = headers.split("/assets/*", 1)[1].split("\n\n", 1)[0]
    assert "?v={{ site.asset_version }}" in head
    assert "immutable" in asset_cache_rule

    asset_root = DOCS / "assets"
    asset_paths = sorted(asset_root.glob("css/*.css")) + sorted(
        asset_root.glob("js/*.js")
    )
    digest = hashlib.sha256()
    for path in asset_paths:
        digest.update(path.relative_to(DOCS).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    expected = f"sha256-{digest.hexdigest()[:12]}"

    config = (DOCS / "_config.yml").read_text(encoding="utf-8")
    match = re.search(
        r'^asset_version:\s*["\']([^"\']+)["\']\s*$', config, re.M
    )

    assert match is not None
    assert match.group(1) == expected, (
        "Public CSS/JS files are cached as immutable. Update asset_version "
        f'to "{expected}" whenever one of them changes.'
    )


def test_openapi_is_typed_described_and_function_calling_friendly() -> None:
    spec = json.loads((DOCS / "openapi.json").read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.1"
    assert spec["servers"] == [
        {"url": "https://bmt.news", "description": "Production"}
    ]

    operations = []
    for path, path_item in spec["paths"].items():
        operation = path_item["get"]
        operations.append(operation)
        assert operation["operationId"]
        assert operation["description"]
        assert operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]
        for parameter in operation.get("parameters", []):
            assert parameter["description"]
            assert parameter["schema"]["type"]
        assert path.startswith("/")

    operation_ids = [operation["operationId"] for operation in operations]
    assert len(operation_ids) == len(set(operation_ids))
    assert "ErrorResponse" in spec["components"]["schemas"]


def test_llms_txt_follows_the_required_discovery_shape() -> None:
    body = (DOCS / "llms.txt").read_text(encoding="utf-8")
    lines = body.splitlines()
    assert lines[0] == "# BMTNews"
    assert next(line for line in lines[1:] if line.strip()).startswith("> ")
    assert "## When to use BMTNews" in body
    assert "[OpenAPI specification](https://bmt.news/openapi.json)" in body
    assert "[BMTNews API and agent documentation]" in body


def test_home_template_and_metadata_are_present_without_javascript() -> None:
    feed_home = (DOCS / "_includes" / "feed-home.html").read_text(encoding="utf-8")
    layout = (DOCS / "_layouts" / "default.html").read_text(encoding="utf-8")
    head = (DOCS / "_includes" / "head-custom.html").read_text(encoding="utf-8")

    assert '<h1 class="visually-hidden">' in feed_home
    assert '<html lang="' in layout
    assert '<link rel="canonical"' in layout
    assert '<meta property="og:type"' in layout
    assert '<meta property="og:image"' in layout
    assert '/developers/' in layout
    assert 'rel="describedby"' in head
    assert 'type="text/markdown"' in head


def test_json_ld_describes_the_real_site_identity_and_contact_route() -> None:
    head = (DOCS / "_includes" / "head-custom.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(head, "html.parser")
    structured = soup.find("script", {"type": "application/ld+json"})
    assert structured is not None
    payload = json.loads(structured.string)
    graph = payload["@graph"]
    organization = next(item for item in graph if item["@type"] == "Organization")
    website = next(item for item in graph if item["@type"] == "WebSite")
    assert organization["name"] == "BMTNews"
    assert organization["contactPoint"][0]["url"] == "https://bmt.news/contact/"
    assert website["publisher"]["@id"] == organization["@id"]


def test_custom_404_worker_and_cloudflare_output_are_included() -> None:
    root_config = (ROOT / "_config.yml").read_text(encoding="utf-8")
    config = (DOCS / "_config.yml").read_text(encoding="utf-8")
    not_found = (DOCS / "404.html").read_text(encoding="utf-8")
    worker = (DOCS / "_worker.js").read_text(encoding="utf-8")
    assert "source: docs" in root_config
    assert (ROOT / "Gemfile").read_text(encoding="utf-8") == (
        DOCS / "Gemfile"
    ).read_text(encoding="utf-8")
    assert '- "_worker.js"' in config
    assert "permalink: /404.html" in not_found
    assert "status: 404" in worker
    assert "application/json; charset=utf-8" in worker
    assert "text/markdown; charset=utf-8" in worker
    assert "Accept-Encoding" in worker


def test_sitemap_and_robots_are_valid_and_discoverable() -> None:
    tree = ElementTree.parse(DOCS / "sitemap.xml")
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = tree.findall("s:url", namespace)
    assert len(urls) >= 10
    assert all(url.find("s:loc", namespace) is not None for url in urls)
    assert all(url.find("s:lastmod", namespace) is not None for url in urls)
    robots = (DOCS / "robots.txt").read_text(encoding="utf-8")
    assert "Sitemap: https://bmt.news/sitemap.xml" in robots


def test_trust_and_developer_pages_are_substantive() -> None:
    for relative in [
        "about/index.md",
        "contact/index.md",
        "developers/index.md",
        "legal/index.md",
    ]:
        body = (DOCS / relative).read_text(encoding="utf-8")
        _, content = body.split("---\n\n", 1)
        assert len(content) >= 500
    developer_body = (DOCS / "developers" / "index.md").read_text(encoding="utf-8")
    assert "/api/latest.json" in developer_body
    assert "/openapi.json" in developer_body
    assert "404" in developer_body
