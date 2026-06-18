"""Run the full AI Engineering Radar pipeline end-to-end.

fetch -> normalize -> dedupe -> score -> build_digest -> people_radar
      -> fetch_previews -> export_pages
"""
from __future__ import annotations

import time

import build_digest
import build_people
import dedupe
import export_pages
import fetch_feeds
import fetch_people
import fetch_previews
import normalize
import score
from common import (
    DATA_DIR, WORK_DIR, ensure_dirs, load_people_config, load_profile, load_scoring,
    load_sources, load_taxonomy, now_utc, read_json, to_iso, write_json,
)

# Insert "People Radar" right after the hiring section so it sits near the top.
PEOPLE_SECTION_AFTER = "hiring_for_you"


def _insert_section(digest: dict, section: dict, after_id: str) -> None:
    sections = digest["sections"]
    idx = next((i for i, s in enumerate(sections) if s["id"] == after_id), len(sections) - 1)
    sections.insert(idx + 1, section)


def main() -> None:
    ensure_dirs()
    sources = load_sources()
    scoring_cfg = load_scoring()
    taxonomy = load_taxonomy()
    profile = load_profile()

    t0 = time.time()
    print("== 1/8 fetch_feeds ==")
    raw_items = fetch_feeds.fetch_all(sources)
    write_json(WORK_DIR / "raw_items.json", raw_items)
    print(f"  {len(raw_items)} raw items")

    print("== 2/8 normalize ==")
    normalized = normalize.normalize_items(raw_items)
    write_json(WORK_DIR / "normalized.json", normalized)
    print(f"  {len(normalized)} normalized items")

    print("== 3/8 dedupe ==")
    deduped = dedupe.dedupe_items(normalized, scoring_cfg["title_similarity_threshold"])
    write_json(WORK_DIR / "deduped.json", deduped)
    print(f"  {len(deduped)} deduped items")

    print("== 4/8 score ==")
    scored = score.score_items(deduped, scoring_cfg, taxonomy, profile)
    scored.sort(key=lambda it: it["score"], reverse=True)
    write_json(WORK_DIR / "scored.json", scored)
    print(f"  {len(scored)} scored items")

    print("== 5/8 build_digest ==")
    digest = build_digest.build_digest(scored, scoring_cfg, taxonomy)
    total_surfaced = sum(len(s["items"]) for s in digest["sections"])
    print(f"  {total_surfaced} items surfaced across {len(digest['sections'])} sections")

    print("== 6/8 people_radar ==")
    people_cfg = load_people_config()
    raw_people = fetch_people.fetch_all(people_cfg)
    write_json(WORK_DIR / "people_raw.json", raw_people)
    people_section, full_people = build_people.build_section(raw_people, people_cfg, profile, taxonomy)
    _insert_section(digest, people_section, after_id=PEOPLE_SECTION_AFTER)
    write_json(WORK_DIR / "digest.json", digest)
    write_json(DATA_DIR / "people.json", {"generated_at": to_iso(now_utc()), "people": full_people})
    print(f"  {len(people_section['items'])} people surfaced "
          f"({sum(1 for p in people_section['items'] if p['region'] == 'India')} India-affiliated)")

    print("== 7/8 fetch_previews ==")
    fetch_previews.main()

    print("== 8/8 export_pages ==")
    export_pages.main()

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
