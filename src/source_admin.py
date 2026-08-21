"""Apply maintainer-dispatched source changes to the production config."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .models import Config
from .url_security import UnsafeURLError, validate_http_url, validate_public_http_url


class SourceChangeError(ValueError):
    """Raised when a source change request is invalid or unsafe."""


@dataclass(frozen=True)
class SourceChangeRequest:
    """Normalized values parsed from GitHub Actions workflow inputs."""

    operation: str
    source_type: str
    source_key: str
    name: str
    endpoint: str
    category: str
    enabled: bool | None
    reason: str


@dataclass
class SourcePointer:
    """A mutable source item and its location inside the config."""

    key: str
    source_type: str
    item: dict[str, Any]
    collection: list[dict[str, Any]] | None = None
    removable: bool = False


OPERATIONS = {"add", "update", "pause", "resume", "remove"}
SOURCE_TYPES = {
    "rss",
    "telegram",
    "github",
    "reddit",
    "hackernews",
    "google_news",
    "gdelt",
    "ossinsight",
}
LIST_SOURCE_TYPES = {"rss", "telegram", "github", "reddit"}

_TELEGRAM_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")
_GITHUB_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REDDIT_RE = re.compile(r"^[A-Za-z0-9_]{2,64}$")
def parse_workflow_dispatch(event: dict[str, Any]) -> SourceChangeRequest:
    """Parse and validate ``workflow_dispatch`` inputs from a GitHub event."""
    inputs = event.get("inputs")
    if not isinstance(inputs, dict):
        raise SourceChangeError("Workflow event is missing dispatch inputs")

    def value(name: str) -> str:
        raw = inputs.get(name, "")
        return str(raw).strip() if raw is not None else ""

    operation = value("operation").lower()
    source_type = value("source_type").lower()
    category = value("category")
    if category == "unchanged":
        category = ""
    enabled_token = value("enabled").lower()
    if operation not in OPERATIONS:
        raise SourceChangeError(f"Unsupported operation: {operation}")
    if source_type not in SOURCE_TYPES:
        raise SourceChangeError(f"Unsupported source type: {source_type}")
    if enabled_token not in {"", "unchanged", "true", "false"}:
        raise SourceChangeError("Target state must be unchanged, true, or false")

    return SourceChangeRequest(
        operation=operation,
        source_type=source_type,
        source_key=value("source_key"),
        name=value("name"),
        endpoint=value("endpoint"),
        category=category,
        enabled=(
            None
            if enabled_token in {"", "unchanged"}
            else enabled_token == "true"
        ),
        reason=value("reason"),
    )


def _normalize_url(value: str) -> str:
    validate_http_url(value)
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    port = parsed.port
    default_port = (parsed.scheme.lower() == "https" and port == 443) or (
        parsed.scheme.lower() == "http" and port == 80
    )
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(
        (parsed.scheme.lower(), netloc, path, parsed.query, "")
    )


def _rss_key(url: str) -> str:
    return f"rss|{_normalize_url(url)}"


def _telegram_key(channel: str) -> str:
    return f"telegram|{channel.lstrip('@').lower()}"


def _github_key(source: dict[str, Any]) -> str:
    source_kind = str(source.get("type") or "repo_releases").lower()
    if source.get("owner") and source.get("repo"):
        identity = f"{source['owner']}/{source['repo']}".lower()
    else:
        identity = str(source.get("username") or "").lower()
    return f"github|{source_kind}|{identity}"


def _reddit_key(kind: str, identity: str) -> str:
    return f"reddit|{kind}|{identity.lower()}"


def _source_pointers(config: dict[str, Any]) -> dict[str, SourcePointer]:
    sources = config["sources"]
    pointers: dict[str, SourcePointer] = {}

    for item in sources.get("rss", []):
        key = _rss_key(str(item["url"]))
        pointers[key] = SourcePointer(key, "rss", item, sources["rss"], True)

    telegram = sources.get("telegram") or {}
    for item in telegram.get("channels", []):
        key = _telegram_key(str(item["channel"]))
        pointers[key] = SourcePointer(
            key, "telegram", item, telegram["channels"], True
        )

    for item in sources.get("github", []):
        key = _github_key(item)
        pointers[key] = SourcePointer(
            key, "github", item, sources["github"], True
        )

    reddit = sources.get("reddit") or {}
    for item in reddit.get("subreddits", []):
        key = _reddit_key("subreddit", str(item["subreddit"]))
        pointers[key] = SourcePointer(
            key, "reddit", item, reddit["subreddits"], True
        )

    for source_type in ("hackernews", "google_news", "gdelt", "ossinsight"):
        item = sources.get(source_type)
        if isinstance(item, dict):
            key = f"{source_type}|main"
            pointers[key] = SourcePointer(key, source_type, item)

    return pointers


def _allowed_categories(config: dict[str, Any]) -> set[str]:
    filtering = config.get("filtering") or {}
    categories: set[str] = set()
    for group in (filtering.get("category_groups") or {}).values():
        categories.update(group.get("categories") or [])
    return categories


def _validate_common(
    request: SourceChangeRequest, config: dict[str, Any]
) -> None:
    if len(request.name) > 120:
        raise SourceChangeError("Source name must be 120 characters or fewer")
    if len(request.endpoint) > 2048:
        raise SourceChangeError("Source endpoint is too long")
    if not 2 <= len(request.reason) <= 1200:
        raise SourceChangeError(
            "Change reason must be between 2 and 1200 characters"
        )

    allowed_categories = _allowed_categories(config)
    if request.category and request.category not in allowed_categories:
        raise SourceChangeError(
            f"Unknown category: {request.category}. "
            "Choose a category already configured in filtering.category_groups."
        )

    if request.operation == "add" and request.source_type not in LIST_SOURCE_TYPES:
        raise SourceChangeError(
            f"Adding {request.source_type} sources is not supported by the console"
        )
    if request.operation == "remove" and request.source_type not in LIST_SOURCE_TYPES:
        raise SourceChangeError(
            f"Removing {request.source_type} is not supported; pause it instead"
        )
    if request.operation != "add" and request.source_key == "new":
        raise SourceChangeError("An existing source key is required")
    if request.operation != "add" and not request.source_key:
        raise SourceChangeError("An existing source key is required")
    if request.operation == "add":
        if not request.endpoint:
            raise SourceChangeError("Endpoint is required when adding a source")
        if not request.category:
            raise SourceChangeError("Category is required when adding a source")
        if request.enabled is None:
            raise SourceChangeError("Target state is required when adding a source")
        if request.source_type == "rss" and not request.name:
            raise SourceChangeError("Name is required when adding an RSS source")
    if request.operation == "update" and not any(
        (
            request.name,
            request.endpoint,
            request.category,
            request.enabled is not None,
        )
    ):
        raise SourceChangeError("Provide at least one field to update")


def _normalize_endpoint(request: SourceChangeRequest) -> str:
    endpoint = request.endpoint.strip()
    if request.source_type == "rss":
        try:
            validate_http_url(endpoint)
        except UnsafeURLError as exc:
            raise SourceChangeError(str(exc)) from exc
        if "${" in endpoint:
            raise SourceChangeError(
                "The public source console cannot add secret-backed RSS URLs"
            )
        return endpoint

    if request.source_type == "telegram":
        channel = endpoint.removeprefix("https://t.me/").lstrip("@").strip("/")
        if not _TELEGRAM_RE.fullmatch(channel):
            raise SourceChangeError("Invalid Telegram channel username")
        return channel

    if request.source_type == "github":
        identity = endpoint.removeprefix("https://github.com/").strip("/")
        if not _GITHUB_RE.fullmatch(identity):
            raise SourceChangeError(
                "GitHub endpoint must use the owner/repository format"
            )
        return identity

    if request.source_type == "reddit":
        subreddit = endpoint.removeprefix("https://www.reddit.com/r/")
        subreddit = subreddit.removeprefix("https://reddit.com/r/")
        subreddit = subreddit.removeprefix("r/").strip("/")
        if not _REDDIT_RE.fullmatch(subreddit):
            raise SourceChangeError("Invalid Reddit subreddit name")
        return subreddit

    return endpoint


def _candidate_key(request: SourceChangeRequest, endpoint: str) -> str:
    if request.source_type == "rss":
        return _rss_key(endpoint)
    if request.source_type == "telegram":
        return _telegram_key(endpoint)
    if request.source_type == "github":
        owner, repo = endpoint.split("/", 1)
        return _github_key(
            {"type": "repo_releases", "owner": owner, "repo": repo}
        )
    if request.source_type == "reddit":
        return _reddit_key("subreddit", endpoint)
    return f"{request.source_type}|main"


def _add_source(
    request: SourceChangeRequest,
    config: dict[str, Any],
    endpoint: str,
    pointers: dict[str, SourcePointer],
) -> str:
    sources = config["sources"]
    candidate_key = _candidate_key(request, endpoint)
    if candidate_key in pointers:
        raise SourceChangeError("This source already exists")

    if request.source_type == "rss":
        sources["rss"].append(
            {
                "name": request.name,
                "url": endpoint,
                "enabled": bool(request.enabled),
                "category": request.category,
            }
        )
    elif request.source_type == "telegram":
        sources["telegram"]["channels"].append(
            {
                "channel": endpoint,
                "enabled": bool(request.enabled),
                "fetch_limit": 10,
                "category": request.category,
            }
        )
    elif request.source_type == "github":
        owner, repo = endpoint.split("/", 1)
        sources["github"].append(
            {
                "type": "repo_releases",
                "owner": owner,
                "repo": repo,
                "enabled": bool(request.enabled),
                "category": request.category,
            }
        )
    elif request.source_type == "reddit":
        sources["reddit"]["subreddits"].append(
            {
                "subreddit": endpoint,
                "enabled": bool(request.enabled),
                "sort": "hot",
                "time_filter": "day",
                "fetch_limit": 8,
                "min_score": 25,
                "category": request.category,
            }
        )
    else:
        raise SourceChangeError(
            f"Adding {request.source_type} is not supported"
        )
    return candidate_key


def _update_source(
    request: SourceChangeRequest,
    pointer: SourcePointer,
    endpoint: str | None,
    pointers: dict[str, SourcePointer],
) -> str:
    item = pointer.item
    candidate_key = (
        _candidate_key(request, endpoint)
        if endpoint is not None
        else pointer.key
    )
    if candidate_key != pointer.key and candidate_key in pointers:
        raise SourceChangeError("The updated source would duplicate another source")

    if request.source_type == "rss":
        if request.name:
            item["name"] = request.name
        if endpoint is not None:
            item["url"] = endpoint
    elif request.source_type == "telegram":
        if endpoint is not None:
            item["channel"] = endpoint
    elif request.source_type == "github":
        if endpoint is not None:
            owner, repo = endpoint.split("/", 1)
            item["owner"] = owner
            item["repo"] = repo
    elif request.source_type == "reddit":
        if endpoint is not None:
            item["subreddit"] = endpoint

    if request.category:
        item["category"] = request.category
    if request.enabled is not None:
        item["enabled"] = request.enabled
    return candidate_key


async def _validate_public_endpoint(
    request: SourceChangeRequest, endpoint: str | None
) -> None:
    if (
        endpoint is not None
        and request.source_type == "rss"
        and request.operation in {"add", "update"}
    ):
        try:
            await validate_public_http_url(endpoint)
        except UnsafeURLError as exc:
            raise SourceChangeError(str(exc)) from exc


def apply_source_change(
    config: dict[str, Any],
    request: SourceChangeRequest,
    *,
    validate_network: bool = True,
) -> dict[str, Any]:
    """Mutate and validate a config for one approved request."""
    _validate_common(request, config)
    endpoint = (
        _normalize_endpoint(request)
        if request.operation == "add"
        or (request.operation == "update" and request.endpoint)
        else None
    )
    pointers = _source_pointers(config)

    if validate_network:
        asyncio.run(_validate_public_endpoint(request, endpoint))

    resulting_key = request.source_key
    if request.operation == "add":
        assert endpoint is not None
        resulting_key = _add_source(
            request, config, endpoint, pointers
        )
    else:
        pointer = pointers.get(request.source_key)
        if pointer is None or pointer.source_type != request.source_type:
            raise SourceChangeError(
                "The source key no longer matches the current main configuration"
            )

        if request.operation == "update":
            resulting_key = _update_source(
                request, pointer, endpoint, pointers
            )
        elif request.operation == "pause":
            pointer.item["enabled"] = False
        elif request.operation == "resume":
            pointer.item["enabled"] = True
        elif request.operation == "remove":
            if not pointer.removable or pointer.collection is None:
                raise SourceChangeError(
                    "This source cannot be removed; pause it instead"
                )
            pointer.collection.remove(pointer.item)

    try:
        Config.model_validate(config)
    except Exception as exc:
        raise SourceChangeError(
            f"The resulting production config is invalid: {exc}"
        ) from exc

    result_pointer = _source_pointers(config).get(resulting_key)
    result_item = result_pointer.item if result_pointer is not None else {}
    return {
        "operation": request.operation,
        "source_type": request.source_type,
        "source_key": resulting_key,
        "name": request.name or str(result_item.get("name") or ""),
        "category": str(result_item.get("category") or request.category),
        "enabled": result_item.get("enabled"),
        "reason": request.reason,
    }


def _load_event_request(event_path: Path) -> SourceChangeRequest:
    try:
        event = json.loads(event_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise SourceChangeError("Could not read the GitHub workflow event") from exc
    if not isinstance(event, dict):
        raise SourceChangeError("GitHub workflow event must be an object")
    return parse_workflow_dispatch(event)


def _run_apply(args: argparse.Namespace) -> int:
    request = _load_event_request(args.event)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceChangeError("Could not read the production config") from exc

    result = apply_source_change(
        config,
        request,
        validate_network=not args.skip_network_validation,
    )
    args.config.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.result.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Validated {result['operation']} for "
        f"{result['source_type']} source {result['name']}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply a maintainer-dispatched BMTNews source change"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--event", type=Path, required=True)
    apply_parser.add_argument("--config", type=Path, required=True)
    apply_parser.add_argument("--result", type=Path, required=True)
    apply_parser.add_argument(
        "--skip-network-validation",
        action="store_true",
        help="Only for deterministic local tests",
    )
    apply_parser.set_defaults(func=_run_apply)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except SourceChangeError as exc:
        print(f"Source change rejected: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
