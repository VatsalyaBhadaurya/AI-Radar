"""Run the full AI Engineering Radar pipeline end-to-end.

fetch -> normalize -> dedupe -> score -> build_digest -> export_pages
"""
from __future__ import annotations

import time

import build_digest
import dedupe
import export_pages
import fetch_feeds
import normalize
import score
from common import WORK_DIR, ensure_dirs, load_scoring, load_sources, load_taxonomy, read_json, write_json


def main() -> None:
    ensure_dirs()
    sources = load_sources()
    scoring_cfg = load_scoring()
    taxonomy = load_taxonomy()

    t0 = time.time()
    print("== 1/6 fetch_feeds ==")
    raw_items = fetch_feeds.fetch_all(sources)
    write_json(WORK_DIR / "raw_items.json", raw_items)
    print(f"  {len(raw_items)} raw items")

    print("== 2/6 normalize ==")
    normalized = normalize.normalize_items(raw_items)
    write_json(WORK_DIR / "normalized.json", normalized)
    print(f"  {len(normalized)} normalized items")

    print("== 3/6 dedupe ==")
    deduped = dedupe.dedupe_items(normalized, scoring_cfg["title_similarity_threshold"])
    write_json(WORK_DIR / "deduped.json", deduped)
    print(f"  {len(deduped)} deduped items")

    print("== 4/6 score ==")
    scored = score.score_items(deduped, scoring_cfg, taxonomy)
    scored.sort(key=lambda it: it["score"], reverse=True)
    write_json(WORK_DIR / "scored.json", scored)
    print(f"  {len(scored)} scored items")

    print("== 5/6 build_digest ==")
    digest = build_digest.build_digest(scored, scoring_cfg, taxonomy)
    write_json(WORK_DIR / "digest.json", digest)
    total_surfaced = sum(len(s["items"]) for s in digest["sections"])
    print(f"  {total_surfaced} items surfaced across {len(digest['sections'])} sections")

    print("== 6/6 export_pages ==")
    export_pages.main()

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
