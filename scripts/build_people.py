"""Merge, score, and rank discovered people into the "People Radar" section.

Input:  data/_work/people_raw.json (from fetch_people.py)
Output: data/_work/people_section.json  (a single digest section dict)
        docs/data/people.json           (the full ranked people list, for the site)

Scoring (all components normalized to [0, 1]):
    score = w_domain * domain_match
          + w_influence * influence
          + w_recency * recency

"meaningfully good" is judged by:
  - domain_match: overlap with your profile.yaml skills/domains + priority stack
  - influence:    citations / h-index / GitHub stars / HF likes (log-scaled)
  - recency:      how recently the person has been active
Geography mix: India-affiliated people are guaranteed a minimum number of slots.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from common import (
    DATA_DIR, WORK_DIR, ensure_dirs, load_people_config, load_profile,
    load_taxonomy, read_json, write_json,
)

# Log-scaling ceilings: the signal value that maps to ~full influence (1.0).
INFLUENCE_SCALES = {
    "citations": 5000,
    "h_index": 60,
    "github_stars": 20000,
    "hf_likes": 2000,
}
DOMAIN_MATCH_CAP = 6  # matched keywords needed to reach full domain_match

# Source precedence when merging the same person across APIs (richer profiles win).
SOURCE_RANK = {"Semantic Scholar": 3, "GitHub": 2, "Hugging Face": 1, "arXiv": 0}


def _normalize_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^a-z0-9\s]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _person_text(person: dict) -> str:
    parts = [
        person.get("name", ""),
        person.get("affiliation", ""),
        person.get("location", ""),
        person.get("bio", ""),
        " ".join(person.get("topics", [])),
        " ".join(w.get("title", "") for w in person.get("recent_work", [])),
    ]
    return " ".join(parts).lower()


def _keyword_matches(text: str, keywords: list) -> list:
    return [kw for kw in keywords if kw.lower() in text]


def _merge(a: dict, b: dict) -> dict:
    """Merge two records for the same person; keep the richer profile."""
    primary, secondary = (a, b) if SOURCE_RANK.get(a["source"], 0) >= SOURCE_RANK.get(b["source"], 0) else (b, a)
    merged = dict(primary)

    merged_sources = set(primary.get("found_via", [primary["source"]])) | set(
        secondary.get("found_via", [secondary["source"]])
    )
    merged["found_via"] = sorted(merged_sources)

    for field in ("affiliation", "location", "bio"):
        if not merged.get(field) and secondary.get(field):
            merged[field] = secondary[field]
    merged["topics"] = sorted(set(primary.get("topics", [])) | set(secondary.get("topics", [])))

    # Merge signals (max wins for each metric).
    signals = dict(primary.get("signals", {}))
    for k, v in secondary.get("signals", {}).items():
        signals[k] = max(signals.get(k, 0), v)
    merged["signals"] = signals

    # Collect cross-source profile links.
    links = dict(primary.get("profiles", {primary["source"]: primary["profile_url"]}))
    links.setdefault(secondary["source"], secondary["profile_url"])
    merged["profiles"] = links

    work = (primary.get("recent_work", []) + secondary.get("recent_work", []))[:4]
    merged["recent_work"] = work

    la = [d for d in (primary.get("last_active"), secondary.get("last_active")) if d]
    merged["last_active"] = max(la) if la else None
    merged["avatar_url"] = primary.get("avatar_url") or secondary.get("avatar_url")
    return merged


def merge_people(raw: list) -> list:
    by_name: dict = {}
    for person in raw:
        person.setdefault("found_via", [person["source"]])
        person.setdefault("profiles", {person["source"]: person["profile_url"]})
        key = _normalize_name(person.get("name", ""))
        if not key:
            continue
        if key in by_name:
            by_name[key] = _merge(by_name[key], person)
        else:
            by_name[key] = person
    return list(by_name.values())


def _influence(signals: dict) -> float:
    best = 0.0
    for metric, scale in INFLUENCE_SCALES.items():
        value = signals.get(metric, 0) or 0
        if value <= 0:
            continue
        norm = math.log10(1 + value) / math.log10(1 + scale)
        best = max(best, min(1.0, norm))
    return round(best, 4)


def _recency(last_active: str, half_life_days: float) -> float:
    if not last_active:
        return 0.5
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(last_active, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    else:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    return round(0.5 ** (age_days / half_life_days), 4)


def _is_india(person: dict, india_keywords: list) -> bool:
    text = f"{person.get('affiliation','')} {person.get('location','')} {person.get('bio','')}".lower()
    return bool(_keyword_matches(text, india_keywords))


def _why(matched: list, signals: dict, region: str, recent_work: list) -> str:
    parts = []
    if matched:
        parts.append(f"works on {', '.join(matched[:3])}")
    bits = []
    if signals.get("citations"):
        bits.append(f"{signals['citations']:,} citations")
    if signals.get("h_index"):
        bits.append(f"h-index {signals['h_index']}")
    if signals.get("github_stars"):
        bits.append(f"{signals['github_stars']:,}★ on GitHub")
    if signals.get("hf_likes"):
        bits.append(f"{signals['hf_likes']:,} HF likes")
    sentence = "This person " + (parts[0] if parts else "is active in your field")
    if bits:
        sentence += f" ({'; '.join(bits)})"
    sentence += f". {region}-based/affiliated." if region == "India" else "."
    if recent_work and recent_work[0].get("title"):
        sentence += f" Recent: {recent_work[0]['title']}."
    return sentence


def score_people(raw: list, cfg: dict, profile: dict, taxonomy: dict) -> list:
    weights = cfg["weights"]
    half_life = cfg.get("recency_half_life_days", 45)
    threshold = cfg.get("personal_match_threshold", 0.45)
    india_keywords = cfg.get("india_affiliation_keywords", [])

    domain_vocab = (
        profile.get("core_skills", [])
        + profile.get("domain_keywords", [])
        + taxonomy.get("priority_keywords", [])
    )
    # De-duplicate while preserving case for display.
    seen = set()
    vocab = []
    for kw in domain_vocab:
        low = kw.lower()
        if low not in seen:
            seen.add(low)
            vocab.append(kw)

    merged = merge_people(raw)
    scored = []
    for person in merged:
        text = _person_text(person)
        matched = _keyword_matches(text, vocab)
        domain_match = min(1.0, len(set(m.lower() for m in matched)) / DOMAIN_MATCH_CAP)
        influence = _influence(person.get("signals", {}))
        recency = _recency(person.get("last_active"), half_life)

        score = (
            weights["domain"] * domain_match
            + weights["influence"] * influence
            + weights["recency"] * recency
        )
        region = "India" if _is_india(person, india_keywords) else "International"
        person.update({
            "domain_match": round(domain_match, 4),
            "influence": influence,
            "recency": recency,
            "score": round(score, 4),
            "matched": sorted(set(matched), key=lambda m: text.find(m.lower())),
            "region": region,
            "personal_match": domain_match >= threshold,
        })
        scored.append(person)

    scored.sort(key=lambda p: p["score"], reverse=True)
    return scored


def _public_person(person: dict) -> dict:
    profiles = person.get("profiles", {})
    profile_links = [{"label": label, "url": url} for label, url in profiles.items() if url]
    primary_url = (
        person.get("discovery_url")
        or (profile_links[0]["url"] if profile_links else person.get("profile_url"))
    )
    tags = sorted(set(person.get("found_via", [person["source"]]) + [person["region"]]))
    if person["personal_match"]:
        tags.append("for_you")
    return {
        "id": "person_" + _normalize_name(person["name"]).replace(" ", "_")[:40],
        "category": "people",
        "name": person["name"],
        "title": person["name"],
        "url": primary_url,
        "source": person["source"],
        "affiliation": person.get("affiliation", ""),
        "region": person["region"],
        "summary": person.get("bio", "") or (", ".join(person.get("topics", [])[:6])),
        "why_it_matters": _why(person["matched"], person.get("signals", {}), person["region"], person.get("recent_work", [])),
        "score": person["score"],
        "personal_match": person["personal_match"],
        "tags": tags,
        "image_url": person.get("avatar_url"),
        "profiles": profile_links,
        "recent_work": [w for w in person.get("recent_work", []) if w.get("title") and w.get("url")][:3],
        "matched_skills": person.get("matched", [])[:6],
        "found_via": person.get("found_via", [person["source"]]),
    }


def select_with_geography_mix(scored: list, cfg: dict) -> list:
    """Top-N by score, but guarantee at least `min_india` India-affiliated people
    (if that many are eligible) by reserving slots for the best India entries."""
    limit = cfg["limits"]["people_radar"]
    min_india = cfg["limits"].get("min_india", 0)
    min_score = cfg.get("min_score", 0.0)

    eligible = [p for p in scored if p["score"] >= min_score]  # already sorted by score desc
    india = [p for p in eligible if p["region"] == "India"]

    forced = india[: min(min_india, limit)]
    forced_ids = {id(p) for p in forced}
    fill = [p for p in eligible if id(p) not in forced_ids]

    chosen = forced + fill[: max(0, limit - len(forced))]
    chosen.sort(key=lambda p: p["score"], reverse=True)
    return chosen


def build_section(raw: list, cfg: dict, profile: dict, taxonomy: dict) -> tuple[dict, list]:
    scored = score_people(raw, cfg, profile, taxonomy)
    chosen = select_with_geography_mix(scored, cfg)
    public = [_public_person(p) for p in chosen]
    section = {"id": "people_radar", "name": "People Radar", "items": public}
    return section, [_public_person(p) for p in scored]


def main() -> None:
    ensure_dirs()
    raw = read_json(WORK_DIR / "people_raw.json", default=[])
    cfg = load_people_config()
    profile = load_profile()
    taxonomy = load_taxonomy()

    section, full_list = build_section(raw, cfg, profile, taxonomy)
    write_json(WORK_DIR / "people_section.json", section)
    write_json(DATA_DIR / "people.json", {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "people": full_list,
    })
    india = sum(1 for it in section["items"] if it["region"] == "India")
    print(f"People Radar: {len(section['items'])} surfaced "
          f"({india} India-affiliated) from {len(raw)} raw records")


if __name__ == "__main__":
    main()
