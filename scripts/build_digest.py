"""Build the daily digest structure from scored items.

Input:  data/_work/scored.json
Output: data/_work/digest.json  (matches docs/data/latest.json schema)
"""
from __future__ import annotations

from common import (
    WORK_DIR, ensure_dirs, load_scoring, load_taxonomy, now_utc, read_json, write_json,
)

# section_id -> (label, category filter, limit key in scoring.yaml digest_limits)
# category_filter == "personal" is a sentinel meaning "items with personal_match=True"
SECTION_DEFS = [
    ("for_you", "Matches Your Stack", "personal", "for_you"),
    ("top_stories", "Top Stories", None, "top_stories"),
    ("build_today", "Build Today: Project Picks", "source_tag:projects", "build_today"),
    ("model_tooling", "Model & Tooling Updates", {"model_releases", "infra_tooling"}, "model_tooling"),
    ("robotics_vla", "Robotics & Embodied AI", {"robotics_vla"}, "robotics_vla"),
    ("vlm_multimodal", "VLM & Multimodal", {"vlm_multimodal"}, "vlm_multimodal"),
    ("papers", "Papers & Benchmarks", {"papers_benchmarks"}, "papers"),
    ("repos", "Repo Watch", {"repos"}, "repos"),
    ("industry", "Industry Moves", {"industry"}, "industry"),
]


def _public_item(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item["title"],
        "source": item["source"],
        "url": item["url"],
        "canonical_url": item["canonical_url"],
        "published_at": item["published_at"],
        "summary": item["summary"],
        "image_url": item.get("image_url"),
        "why_it_matters": item["why_it_matters"],
        "tags": item["tags"],
        "category": item["category"],
        "score": item["score"],
        "personal_match": item.get("personal_match", False),
        **({"also_reported_by": item["also_reported_by"]} if "also_reported_by" in item else {}),
    }


def _build_summary(top_items: list[dict], total_items: int) -> tuple[str, str]:
    today = now_utc().strftime("%Y-%m-%d")
    headline = "Today's AI engineering radar"
    if not top_items:
        return headline, f"No items cleared the relevance threshold today out of {total_items} scanned."

    lead = top_items[0]
    category_counts: dict[str, int] = {}
    for it in top_items:
        category_counts[it["category"]] = category_counts.get(it["category"], 0) + 1
    top_cats = sorted(category_counts, key=category_counts.get, reverse=True)[:3]

    summary = (
        f"Today's lead story: \"{lead['title']}\" ({lead['source']}). "
        f"Coverage spans {', '.join(top_cats)} with {total_items} items scanned and "
        f"{len(top_items)} surfaced across sections."
    )
    return f"{headline} — {today}", summary


def build_digest(scored_items: list[dict], scoring_cfg: dict, taxonomy: dict) -> dict:
    min_threshold = scoring_cfg["min_score_threshold"]
    top_story_min = scoring_cfg["top_story_min_score"]
    limits = scoring_cfg["digest_limits"]

    eligible = [it for it in scored_items if it["score"] >= min_threshold]
    used_ids: set[str] = set()
    sections = []
    surfaced: list[dict] = []

    for section_id, label, category_filter, limit_key in SECTION_DEFS:
        limit = limits.get(limit_key, 5)
        candidates = [it for it in eligible if it["id"] not in used_ids]

        if category_filter is None:  # top_stories: best overall, above top_story_min
            candidates = [it for it in candidates if it["score"] >= top_story_min]
        elif category_filter == "personal":
            candidates = [it for it in candidates if it.get("personal_match")]
        elif isinstance(category_filter, str) and category_filter.startswith("source_tag:"):
            source_tag = category_filter.split(":", 1)[1]
            candidates = [it for it in candidates if source_tag in it.get("tags", [])]
        else:
            candidates = [it for it in candidates if it["category"] in category_filter]

        chosen = candidates[:limit]  # eligible/scored_items already sorted by score desc
        for it in chosen:
            used_ids.add(it["id"])
            surfaced.append(it)

        sections.append({
            "id": section_id,
            "name": label,
            "items": [_public_item(it) for it in chosen],
        })

    headline, summary = _build_summary(surfaced[:5] if surfaced else [], len(scored_items))

    digest = {
        "date": now_utc().strftime("%Y-%m-%d"),
        "generated_at": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "headline": headline,
        "summary": summary,
        "sections": sections,
    }
    return digest


def main() -> None:
    ensure_dirs()
    scored_items = read_json(WORK_DIR / "scored.json", default=[])
    scoring_cfg = load_scoring()
    taxonomy = load_taxonomy()
    digest = build_digest(scored_items, scoring_cfg, taxonomy)
    write_json(WORK_DIR / "digest.json", digest)

    total_surfaced = sum(len(s["items"]) for s in digest["sections"])
    print(f"Built digest for {digest['date']}: {total_surfaced} items across {len(digest['sections'])} sections")


if __name__ == "__main__":
    main()
