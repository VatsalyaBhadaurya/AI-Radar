"""Fetch raw entries from all configured sources (RSS/Atom, arXiv, GitHub releases).

Output: a list of raw entry dicts written to data/_work/raw_items.json
"""
from __future__ import annotations

import sys
import time
from calendar import timegm
from datetime import datetime, timezone

import feedparser
import requests

from common import (
    WORK_DIR, ensure_dirs, load_sources, write_json,
)

REQUEST_TIMEOUT = 20
USER_AGENT = "ai-engineering-radar/1.0 (+https://github.com/)"
MAX_ITEMS_PER_SOURCE = 25


def _entry_published(entry) -> str | None:
    for key in ("published_parsed", "updated_parsed"):
        struct = entry.get(key)
        if struct:
            dt = datetime.fromtimestamp(timegm(struct), tz=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return None


def _entry_image(entry) -> str | None:
    """Pull a preview image straight out of the feed entry, if present."""
    thumbs = entry.get("media_thumbnail")
    if thumbs:
        url = thumbs[0].get("url")
        if url:
            return url

    for content in entry.get("media_content", []):
        if content.get("medium") == "image" and content.get("url"):
            return content["url"]

    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("image/"):
            return link.get("href")

    return None


def fetch_source(source: dict) -> list[dict]:
    url = source["url"]
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:  # noqa: BLE001 - keep pipeline alive on any source failure
        print(f"  [warn] failed to fetch {source['id']} ({url}): {exc}", file=sys.stderr)
        return []

    items = []
    for entry in feed.entries[:MAX_ITEMS_PER_SOURCE]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        summary = entry.get("summary") or entry.get("description") or ""
        items.append({
            "source_id": source["id"],
            "source_name": source["name"],
            "category": source["category"],
            "source_trust": source["trust"],
            "type": source["type"],
            "title": title,
            "link": link,
            "summary": summary,
            "published_at": _entry_published(entry),
            "image_url": _entry_image(entry),
        })
    return items


def fetch_all(sources: list[dict]) -> list[dict]:
    all_items = []
    for source in sources:
        print(f"  fetching {source['id']} ({source['type']}) ...")
        items = fetch_source(source)
        print(f"    -> {len(items)} entries")
        all_items.extend(items)
        time.sleep(0.5)  # be polite to upstream hosts
    return all_items


def main() -> None:
    ensure_dirs()
    sources = load_sources()
    print(f"Fetching {len(sources)} sources...")
    items = fetch_all(sources)
    out_path = WORK_DIR / "raw_items.json"
    write_json(out_path, items)
    print(f"Wrote {len(items)} raw items to {out_path}")


if __name__ == "__main__":
    main()
