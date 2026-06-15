"""Normalize raw fetched items into the common item schema.

Input:  data/_work/raw_items.json (from fetch_feeds.py)
Output: data/_work/normalized.json
"""
from __future__ import annotations

from common import (
    WORK_DIR, ensure_dirs, canonicalize_url, make_id, clean_text,
    to_iso, now_utc, read_json, write_json,
)


def normalize_items(raw_items: list[dict]) -> list[dict]:
    normalized = []
    fallback_published = to_iso(now_utc())

    for raw in raw_items:
        url = (raw.get("link") or "").strip()
        if not url:
            continue
        canonical_url = canonicalize_url(url)
        title = clean_text(raw.get("title", ""), max_len=200)
        if not title:
            continue
        summary = clean_text(raw.get("summary", ""), max_len=500)
        published_at = raw.get("published_at") or fallback_published

        item = {
            "id": make_id(canonical_url, title),
            "title": title,
            "source": raw["source_name"],
            "source_id": raw["source_id"],
            "url": url,
            "canonical_url": canonical_url,
            "published_at": published_at,
            "summary": summary,
            "category": raw["category"],
            "source_trust": raw["source_trust"],
            "tags": [raw["category"]],
            "image_url": raw.get("image_url"),
        }
        if raw.get("company"):
            item["company"] = raw["company"]
        if raw.get("location"):
            item["location"] = raw["location"]
        if raw.get("job_tags"):
            item["job_tags"] = raw["job_tags"]
        normalized.append(item)

    return normalized


def main() -> None:
    ensure_dirs()
    raw_items = read_json(WORK_DIR / "raw_items.json", default=[])
    normalized = normalize_items(raw_items)
    write_json(WORK_DIR / "normalized.json", normalized)
    print(f"Normalized {len(raw_items)} raw items -> {len(normalized)} items")


if __name__ == "__main__":
    main()
