"""Score deduplicated items: relevance, novelty, source_trust, engineering_value.

score = w_relevance * relevance
      + w_novelty * novelty
      + w_source_trust * source_trust
      + w_engineering_value * engineering_value

Input:  data/_work/deduped.json
Output: data/_work/scored.json
"""
from __future__ import annotations

from datetime import datetime, timezone

from common import (
    ARCHIVE_DIR, WORK_DIR, ensure_dirs, load_scoring, load_taxonomy,
    now_utc, parse_iso, read_json, write_json,
)

NOISE_PENALTY = 0.3
HYPE_PENALTY = 0.5
ENG_KEYWORD_STEP = 0.15
ENG_KEYWORD_BASE = 0.15
RELEVANCE_BASE = 0.25
RELEVANCE_KEYWORD_CAP = 5  # number of matched keywords needed to reach full relevance


def _load_seen_history(lookback_days: int) -> set[str]:
    """Collect canonical URLs / item ids seen in recent archive digests."""
    seen: set[str] = set()
    if not ARCHIVE_DIR.exists():
        return seen

    files = sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)[:lookback_days]
    for f in files:
        data = read_json(f, default={})
        for section in data.get("sections", []):
            for item in section.get("items", []):
                if item.get("id"):
                    seen.add(item["id"])
                if item.get("canonical_url"):
                    seen.add(item["canonical_url"])
    return seen


def _keyword_matches(text: str, keywords: list[str]) -> list[str]:
    return [kw for kw in keywords if kw.lower() in text]


def _compute_relevance(text: str, item_category: str, taxonomy: dict) -> tuple[float, str, list[str]]:
    """Return (relevance, best_category, matched_keywords)."""
    categories = taxonomy["categories"]
    best_category = item_category
    best_matches: list[str] = []
    best_ratio = 0.0

    for cat_id, cat_def in categories.items():
        if cat_id == "noise":
            continue
        matches = _keyword_matches(text, cat_def.get("keywords", []))
        ratio = min(len(matches), RELEVANCE_KEYWORD_CAP) / RELEVANCE_KEYWORD_CAP
        # Slight preference for the item's source-assigned category on ties.
        if ratio > best_ratio or (ratio == best_ratio and cat_id == item_category and best_category != item_category):
            best_ratio = ratio
            best_category = cat_id
            best_matches = matches

    relevance = min(1.0, RELEVANCE_BASE + (1 - RELEVANCE_BASE) * best_ratio)

    # Noise check
    noise_matches = _keyword_matches(text, categories.get("noise", {}).get("keywords", []))
    if noise_matches:
        relevance *= NOISE_PENALTY
        best_category = "noise"

    return relevance, best_category, best_matches


def _compute_novelty(item: dict, seen: set[str], half_life_days: float) -> float:
    if item["id"] in seen or item["canonical_url"] in seen:
        return 0.0
    try:
        published = parse_iso(item["published_at"])
    except (ValueError, KeyError):
        return 0.5
    age_days = max(0.0, (now_utc() - published).total_seconds() / 86400)
    return 0.5 ** (age_days / half_life_days)


def _compute_engineering_value(text: str, taxonomy: dict) -> float:
    eng_matches = _keyword_matches(text, taxonomy.get("engineering_keywords", []))
    hype_matches = _keyword_matches(text, taxonomy.get("hype_keywords", []))
    value = min(1.0, ENG_KEYWORD_BASE + ENG_KEYWORD_STEP * len(eng_matches))
    if hype_matches:
        value *= HYPE_PENALTY
    return value


def _why_it_matters(category_label: str, matched_keywords: list[str], engineering_value: float) -> str:
    if matched_keywords:
        kw_text = ", ".join(matched_keywords[:3])
        base = f"Relevant to {category_label} (matches: {kw_text})."
    else:
        base = f"Tagged under {category_label}."
    if engineering_value >= 0.5:
        base += " Likely useful for builders (code, benchmarks, or tooling implications)."
    return base


def score_items(items: list[dict], scoring_cfg: dict, taxonomy: dict) -> list[dict]:
    weights = scoring_cfg["weights"]
    half_life = scoring_cfg["novelty_half_life_days"]
    lookback = scoring_cfg["novelty_lookback_days"]
    max_age_days = scoring_cfg["max_item_age_days"]
    seen = _load_seen_history(lookback)

    categories = taxonomy["categories"]
    now = now_utc()
    scored = []

    for item in items:
        text = f"{item['title']} {item['summary']}".lower()

        try:
            published = parse_iso(item["published_at"])
            age_days = (now - published).total_seconds() / 86400
        except (ValueError, KeyError):
            age_days = 0

        if age_days > max_age_days:
            continue

        relevance, best_category, matched_keywords = _compute_relevance(text, item["category"], taxonomy)
        novelty = _compute_novelty(item, seen, half_life)
        engineering_value = _compute_engineering_value(text, taxonomy)
        source_trust = item["source_trust"]

        score = (
            weights["relevance"] * relevance
            + weights["novelty"] * novelty
            + weights["source_trust"] * source_trust
            + weights["engineering_value"] * engineering_value
        )

        result = dict(item)
        result["category"] = best_category
        result["relevance"] = round(relevance, 4)
        result["novelty"] = round(novelty, 4)
        result["engineering_value"] = round(engineering_value, 4)
        result["score"] = round(score, 4)

        category_label = categories.get(best_category, {}).get("label", best_category)
        result["why_it_matters"] = _why_it_matters(category_label, matched_keywords, engineering_value)

        tags = set(result.get("tags", []))
        tags.add(best_category)
        for cat_id, cat_def in categories.items():
            if cat_id in (best_category, "noise"):
                continue
            if _keyword_matches(text, cat_def.get("keywords", [])):
                tags.add(cat_id)
        result["tags"] = sorted(tags)

        scored.append(result)

    return scored


def main() -> None:
    ensure_dirs()
    items = read_json(WORK_DIR / "deduped.json", default=[])
    scoring_cfg = load_scoring()
    taxonomy = load_taxonomy()
    scored = score_items(items, scoring_cfg, taxonomy)
    scored.sort(key=lambda it: it["score"], reverse=True)
    write_json(WORK_DIR / "scored.json", scored)
    print(f"Scored {len(scored)} items (from {len(items)} candidates)")


if __name__ == "__main__":
    main()
