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
    ARCHIVE_DIR, WORK_DIR, ensure_dirs, load_profile, load_scoring, load_taxonomy,
    now_utc, parse_iso, read_json, write_json,
)

NOISE_PENALTY = 0.3
HYPE_PENALTY = 0.5
ENG_KEYWORD_STEP = 0.15
ENG_KEYWORD_BASE = 0.15
RELEVANCE_BASE = 0.25
RELEVANCE_KEYWORD_CAP = 5  # number of matched keywords needed to reach full relevance

# Bonus applied to relevance per matched "priority_keywords" entry (curator's stack/interests).
PRIORITY_BONUS_PER_MATCH = 0.08
PRIORITY_BONUS_CAP = 0.25

# ---- Hiring For You (job postings scored against config/profile.yaml) ----
JOB_CORE_SKILL_WEIGHT = 0.2
JOB_DOMAIN_WEIGHT = 0.15
JOB_GENERAL_SKILL_WEIGHT = 0.05
JOB_ENTRY_BONUS = 0.2
JOB_SENIOR_PENALTY_FACTOR = 0.25
JOB_SCORE_EXPERIENCE_WEIGHT = 0.75
JOB_SCORE_NOVELTY_WEIGHT = 0.25
JOB_PERSONAL_MATCH_THRESHOLD = 0.35

# ---- Recent Funding (startup funding news, incl. medtech) ----
FUNDING_RELEVANCE_BASE = 0.2
FUNDING_KEYWORD_STEP = 0.12
FUNDING_DOMAIN_STEP = 0.08


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


def _why_it_matters(
    category_label: str, matched_keywords: list[str], engineering_value: float,
    priority_matches: list[str],
) -> str:
    if matched_keywords:
        kw_text = ", ".join(matched_keywords[:3])
        base = f"Relevant to {category_label} (matches: {kw_text})."
    else:
        base = f"Tagged under {category_label}."
    if engineering_value >= 0.5:
        base += " Likely useful for builders (code, benchmarks, or tooling implications)."
    if priority_matches:
        base += f" Matches your stack: {', '.join(priority_matches[:3])}."
    return base


def _job_why_it_matters(skill_matches: list[str], domain_matches: list[str], entry_matches: list[str]) -> str:
    parts = []
    if skill_matches:
        parts.append(f"matches your skills ({', '.join(skill_matches[:3])})")
    if domain_matches:
        parts.append(f"matches your focus areas ({', '.join(domain_matches[:3])})")
    if entry_matches:
        parts.append("looks open to interns/entry-level candidates")
    if not parts:
        return "Job posting from a tracked board; no strong overlap with your profile yet."
    return "This role " + "; ".join(parts) + "."


def _funding_why_it_matters(funding_matches: list[str], domain_matches: list[str]) -> str:
    if domain_matches:
        return f"Startup funding news relevant to your focus areas: {', '.join(domain_matches[:3])}."
    if funding_matches:
        return "Startup funding news (" + ", ".join(funding_matches[:3]) + ")."
    return "Startup funding news."


def _score_job(item: dict, text: str, profile: dict, seen: set[str], half_life: float) -> dict:
    job_text = f"{text} {' '.join(item.get('job_tags', []))}".lower()

    core_matches = _keyword_matches(job_text, profile.get("core_skills", []))
    general_matches = _keyword_matches(job_text, profile.get("general_skills", []))
    domain_matches = _keyword_matches(job_text, profile.get("domain_keywords", []))
    entry_matches = _keyword_matches(job_text, profile.get("entry_level_keywords", []))
    senior_matches = _keyword_matches(job_text, profile.get("senior_only_keywords", []))
    skill_matches = core_matches + general_matches

    if not core_matches and not domain_matches:
        # No overlap with a distinctive skill or a focus domain - a hit on a generic
        # tool (Python, Docker, ...) or the entry-level bonus alone isn't a real match.
        experience_match = 0.0
    else:
        experience_match = (
            JOB_CORE_SKILL_WEIGHT * len(core_matches)
            + JOB_DOMAIN_WEIGHT * len(domain_matches)
            + JOB_GENERAL_SKILL_WEIGHT * len(general_matches)
        )
        if entry_matches:
            experience_match += JOB_ENTRY_BONUS
        experience_match = min(1.0, experience_match)
        if senior_matches and not entry_matches:
            experience_match *= JOB_SENIOR_PENALTY_FACTOR

    novelty = _compute_novelty(item, seen, half_life)
    score = JOB_SCORE_EXPERIENCE_WEIGHT * experience_match + JOB_SCORE_NOVELTY_WEIGHT * novelty

    result = dict(item)
    result["category"] = "jobs"
    result["relevance"] = round(experience_match, 4)
    result["novelty"] = round(novelty, 4)
    result["engineering_value"] = 0.0
    result["score"] = round(score, 4)
    result["experience_match"] = round(experience_match, 4)
    result["matched_skills"] = skill_matches
    result["matched_domains"] = domain_matches
    result["personal_match"] = experience_match >= JOB_PERSONAL_MATCH_THRESHOLD
    result["matched_stack_keywords"] = skill_matches + domain_matches
    result["why_it_matters"] = _job_why_it_matters(skill_matches, domain_matches, entry_matches)

    tags = set(result.get("tags", []))
    tags.add("jobs")
    if result["personal_match"]:
        tags.add("for_you")
    result["tags"] = sorted(tags)

    return result


def _score_funding(
    item: dict, text: str, profile: dict, taxonomy: dict, scoring_cfg: dict, seen: set[str], half_life: float,
) -> dict:
    weights = scoring_cfg["weights"]

    funding_matches = _keyword_matches(text, taxonomy.get("funding_keywords", []))
    domain_matches = _keyword_matches(text, profile.get("domain_keywords", []))

    relevance = min(1.0, FUNDING_RELEVANCE_BASE
                    + FUNDING_KEYWORD_STEP * len(funding_matches)
                    + FUNDING_DOMAIN_STEP * len(domain_matches))

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
    result["category"] = "funding"
    result["relevance"] = round(relevance, 4)
    result["novelty"] = round(novelty, 4)
    result["engineering_value"] = round(engineering_value, 4)
    result["score"] = round(score, 4)
    result["personal_match"] = False
    result["matched_stack_keywords"] = []
    result["matched_domains"] = domain_matches
    result["why_it_matters"] = _funding_why_it_matters(funding_matches, domain_matches)

    tags = set(result.get("tags", []))
    if funding_matches:
        tags.add("funding")
    else:
        # Came from a funding-focused source but doesn't actually mention a
        # raise/round/acquisition - don't surface it in "Recent Funding".
        tags.discard("funding")
    result["tags"] = sorted(tags)

    return result


def score_items(items: list[dict], scoring_cfg: dict, taxonomy: dict, profile: dict | None = None) -> list[dict]:
    profile = profile or {}
    weights = scoring_cfg["weights"]
    half_life = scoring_cfg["novelty_half_life_days"]
    lookback = scoring_cfg["novelty_lookback_days"]
    max_age_days = scoring_cfg["max_item_age_days"]
    max_age_overrides = scoring_cfg.get("max_item_age_days_by_category", {})
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

        if age_days > max_age_overrides.get(item["category"], max_age_days):
            continue

        if item["category"] == "jobs":
            scored.append(_score_job(item, text, profile, seen, half_life))
            continue

        if item["category"] == "funding":
            scored.append(_score_funding(item, text, profile, taxonomy, scoring_cfg, seen, half_life))
            continue

        relevance, best_category, matched_keywords = _compute_relevance(text, item["category"], taxonomy)
        novelty = _compute_novelty(item, seen, half_life)
        engineering_value = _compute_engineering_value(text, taxonomy)
        source_trust = item["source_trust"]

        priority_matches = _keyword_matches(text, taxonomy.get("priority_keywords", []))
        if priority_matches:
            bonus = min(PRIORITY_BONUS_CAP, PRIORITY_BONUS_PER_MATCH * len(priority_matches))
            relevance = min(1.0, relevance + bonus)

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
        result["personal_match"] = bool(priority_matches)
        result["matched_stack_keywords"] = priority_matches

        category_label = categories.get(best_category, {}).get("label", best_category)
        result["why_it_matters"] = _why_it_matters(category_label, matched_keywords, engineering_value, priority_matches)

        tags = set(result.get("tags", []))
        tags.add(best_category)
        for cat_id, cat_def in categories.items():
            if cat_id in (best_category, "noise"):
                continue
            if _keyword_matches(text, cat_def.get("keywords", [])):
                tags.add(cat_id)
        if priority_matches:
            tags.add("for_you")
        result["tags"] = sorted(tags)

        scored.append(result)

    return scored


def main() -> None:
    ensure_dirs()
    items = read_json(WORK_DIR / "deduped.json", default=[])
    scoring_cfg = load_scoring()
    taxonomy = load_taxonomy()
    profile = load_profile()
    scored = score_items(items, scoring_cfg, taxonomy, profile)
    scored.sort(key=lambda it: it["score"], reverse=True)
    write_json(WORK_DIR / "scored.json", scored)
    print(f"Scored {len(scored)} items (from {len(items)} candidates)")


if __name__ == "__main__":
    main()
