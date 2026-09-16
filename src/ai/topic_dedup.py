"""Bounded semantic comparisons; never silently publish an unchecked batch."""

from itertools import combinations
import hashlib
import json
import logging

from .prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
from .utils import parse_json_response

logger = logging.getLogger(__name__)


class DedupResponseError(ValueError):
    """Only locally generated, allowlisted schema codes may be logged."""

    def __init__(self, code):
        self.code = code
        super().__init__("invalid dedup response")


def validate_duplicates(payload, size):
    if not isinstance(payload, dict):
        raise DedupResponseError("not_object_or_invalid_json")
    if not isinstance(payload.get("duplicates"), list):
        raise DedupResponseError("duplicates_not_list")
    for group in payload["duplicates"]:
        if not isinstance(group, list):
            raise DedupResponseError("group_not_list")
        if len(group) < 2:
            raise DedupResponseError("group_too_short")
        if any(type(index) is not int for index in group):
            raise DedupResponseError("index_not_integer")
        if any(not 0 <= index < size for index in group):
            raise DedupResponseError("index_out_of_range")
        if len(set(group)) != len(group):
            raise DedupResponseError("repeated_index")
    return payload["duplicates"]


def response_shape(payload):
    """Only types/counts; never values, arbitrary keys or model prose."""
    def kind(value):
        return {dict: "object", list: "array", str: "string", int: "integer",
                float: "number", bool: "boolean", type(None): "null_or_parse_failure"}.get(type(value), "other")
    result = {"root": kind(payload)}
    if isinstance(payload, list):
        result.update(length=len(payload), element_types=sorted({kind(v) for v in payload}),
                      group_sizes=[len(v) for v in payload[:24] if isinstance(v, list)])
    return result


async def duplicate_groups(client, items, clusters, *, system=TOPIC_DEDUP_SYSTEM, cache=None):
    groups = []

    async def compare(indices):
        lines = []
        for local, index in enumerate(indices):
            item = items[index]
            lines.append(
                f"[{local}] {item.title[:300]}\n"
                f"    Published: {item.published_at.isoformat()}\n"
                f"    Tags: {', '.join(item.ai_tags or [])[:300]}\n"
                f"    Summary: {(item.ai_summary or '')[:1200]}"
            )
        user = TOPIC_DEDUP_USER.format(items="\n\n".join(lines))
        cached = cache.get_comparison(system, user) if cache is not None else None
        for attempt in range(2):
            payload = None
            try:
                payload = cached
                if payload is None:
                    response = await client.complete(system=system, user=user)
                    payload = parse_json_response(response)
                validated = []
                for group in validate_duplicates(payload, len(indices)):
                    validated.append(sorted({indices[index] for index in group}))
                groups.extend(validated)
                if cache is not None and cached is None:
                    cache.store_comparison(system, user, {"duplicates": payload["duplicates"]})
                return
            except Exception as exc:
                cached = None
                # Never log raw provider/model text: it can contain secrets or
                # untrusted input. Permanent account errors cannot heal on retry.
                status = getattr(exc, "status_code", None)
                status = status if type(status) is int and 100 <= status <= 599 else None
                reason = {402: "insufficient_balance", 401: "authentication_failed",
                          403: "permission_denied", 429: "rate_limited"}.get(status)
                reason = reason or ("invalid_response" if isinstance(exc, ValueError)
                                    else "provider_error")
                detail = exc.code if type(exc) is DedupResponseError else "unclassified"
                logger.warning("dedup_diagnostic %s", json.dumps({
                    "reason": reason, "detail": detail, "status": status,
                    "attempt": attempt + 1, "batch_size": len(indices),
                    "batch_id": hashlib.sha256((system + user).encode()).hexdigest()[:16],
                    "shape": response_shape(payload),
                }, sort_keys=True))
                if attempt == 1 or status in {401, 402, 403}:
                    raise RuntimeError(
                        "Semantic dedup unavailable: refusing to publish unchecked content "
                        f"(reason={reason}, detail={detail}, status={status})"
                    ) from None

    for cluster in clusters:
        if len(cluster) < 2:
            continue
        # One normal 14-story ranking fits in a single comparison instead of
        # three overlapping calls. Larger clusters still cover EVERY pair.
        # Input excerpts are unchanged; no prompt exceeds 24 items.
        if len(cluster) <= 24:
            await compare(cluster)
            continue
        blocks = [cluster[start:start + 12] for start in range(0, len(cluster), 12)]
        batches = [blocks[0]] if len(blocks) == 1 else [a + b for a, b in combinations(blocks, 2)]
        for batch in batches:
            await compare(batch)

    # Transitive, overlapping model groups must have one stable representative.
    parents = list(range(len(items)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for group in groups:
        for index in group[1:]:
            left, right = root(group[0]), root(index)
            parents[max(left, right)] = min(left, right)
    merged = {}
    for index in range(len(items)):
        merged.setdefault(root(index), []).append(index)
    return [group for group in merged.values() if len(group) > 1]
