"""Deduplicate normalized items.

Strategy:
  1. Exact match on canonical_url -> merge into one item.
  2. Near-duplicate titles (SequenceMatcher ratio > threshold) -> cluster and
     keep the highest-trust representative.

Input:  data/_work/normalized.json
Output: data/_work/deduped.json
"""
from __future__ import annotations

from difflib import SequenceMatcher

from common import (
    WORK_DIR, ensure_dirs, load_scoring, normalize_title, read_json, write_json,
)


def _merge_group(items: list[dict]) -> dict:
    """Pick the highest-trust (then most recent) item as representative,
    merging tags/categories from the rest of the group."""
    representative = max(
        items,
        key=lambda it: (it["source_trust"], it["published_at"]),
    )
    merged_tags = set()
    other_sources = set()
    for it in items:
        merged_tags.update(it.get("tags", []))
        if it["source"] != representative["source"]:
            other_sources.add(it["source"])

    result = dict(representative)
    result["tags"] = sorted(merged_tags)
    if other_sources:
        result["also_reported_by"] = sorted(other_sources)
    return result


def dedupe_items(items: list[dict], title_sim_threshold: float) -> list[dict]:
    # Step 1: exact canonical URL match
    by_url: dict[str, list[dict]] = {}
    for item in items:
        by_url.setdefault(item["canonical_url"], []).append(item)
    merged_by_url = [_merge_group(group) for group in by_url.values()]

    # Step 2: near-duplicate titles
    n = len(merged_by_url)
    norm_titles = [normalize_title(it["title"]) for it in merged_by_url]
    visited = [False] * n
    clusters: list[list[dict]] = []

    for i in range(n):
        if visited[i]:
            continue
        cluster = [merged_by_url[i]]
        visited[i] = True
        for j in range(i + 1, n):
            if visited[j]:
                continue
            ratio = SequenceMatcher(None, norm_titles[i], norm_titles[j]).ratio()
            if ratio >= title_sim_threshold:
                cluster.append(merged_by_url[j])
                visited[j] = True
        clusters.append(cluster)

    return [_merge_group(cluster) if len(cluster) > 1 else cluster[0] for cluster in clusters]


def main() -> None:
    ensure_dirs()
    items = read_json(WORK_DIR / "normalized.json", default=[])
    scoring_cfg = load_scoring()
    threshold = scoring_cfg["title_similarity_threshold"]
    deduped = dedupe_items(items, threshold)
    write_json(WORK_DIR / "deduped.json", deduped)
    print(f"Deduped {len(items)} items -> {len(deduped)} items")


if __name__ == "__main__":
    main()
