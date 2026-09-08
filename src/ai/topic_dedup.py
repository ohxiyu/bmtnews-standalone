"""Bounded semantic comparisons; never silently publish an unchecked batch."""

from itertools import combinations

from .prompts import TOPIC_DEDUP_SYSTEM, TOPIC_DEDUP_USER
from .utils import parse_json_response


async def duplicate_groups(client, items, clusters, *, system=TOPIC_DEDUP_SYSTEM):
    groups = []

    async def compare(indices):
        lines = []
        for local, index in enumerate(indices):
            item = items[index]
            lines.append(
                f"[{local}] {item.title[:300]}\n"
                f"    Tags: {', '.join(item.ai_tags or [])[:300]}\n"
                f"    Summary: {(item.ai_summary or '')[:1200]}"
            )
        for attempt in range(2):
            try:
                response = await client.complete(
                    system=system,
                    user=TOPIC_DEDUP_USER.format(items="\n\n".join(lines)),
                )
                payload = parse_json_response(response)
                if not isinstance(payload, dict) or not isinstance(payload.get("duplicates"), list):
                    raise ValueError("invalid dedup response")
                validated = []
                for group in payload["duplicates"]:
                    if not isinstance(group, list) or len(group) < 2 or any(
                        type(index) is not int or not 0 <= index < len(indices)
                        for index in group
                    ):
                        raise ValueError("invalid duplicate indices")
                    validated.append(sorted({indices[index] for index in group}))
                groups.extend(validated)
                return
            except Exception:
                if attempt == 1:
                    raise RuntimeError(
                        "Semantic dedup unavailable: refusing to publish unchecked content"
                    ) from None

    for cluster in clusters:
        # Six-item blocks, compared in pairs, cover every pair even when a
        # transitive local topic cluster is large. No prompt exceeds 12 items.
        blocks = [cluster[start:start + 6] for start in range(0, len(cluster), 6)]
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
