"""Enrich digest items with a preview image (for social-style cards).

Most feed entries already carry an image (media:thumbnail/media:content) via
fetch_feeds.py. For items that don't, fetch the article page and pull the
og:image / twitter:image meta tag, same as link-preview cards on social media.

Results are cached in docs/data/preview_cache.json (keyed by canonical_url) so
repeat runs don't re-fetch the same pages.

Input/Output: data/_work/digest.json (items get "image_url" filled in-place)
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests

from common import DATA_DIR, WORK_DIR, ensure_dirs, now_utc, read_json, write_json

REQUEST_TIMEOUT = 8
MAX_BYTES = 200_000
USER_AGENT = "ai-engineering-radar/1.0 (+https://github.com/)"
CACHE_PATH = DATA_DIR / "preview_cache.json"
CACHE_MAX_AGE_DAYS = 30
MAX_FETCHES_PER_RUN = 40

_META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_META_RE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image(?::secure_url)?|twitter:image(?::src)?)["\']',
    re.IGNORECASE,
)


def _extract_og_image(html: str, base_url: str) -> str | None:
    match = _META_RE.search(html) or _META_RE_REVERSED.search(html)
    if not match:
        return None
    image_url = match.group(1).strip()
    if not image_url:
        return None
    return urljoin(base_url, image_url)


def fetch_og_image(url: str) -> str | None:
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT, stream=True,
        )
        resp.raise_for_status()
        chunk = resp.raw.read(MAX_BYTES, decode_content=True)
        html = chunk.decode(resp.encoding or "utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001 - preview is best-effort
        print(f"  [warn] preview fetch failed for {url}: {exc}", file=sys.stderr)
        return None
    return _extract_og_image(html, url)


def _load_cache() -> dict:
    return read_json(CACHE_PATH, default={})


def _prune_cache(cache: dict) -> dict:
    cutoff = now_utc().timestamp() - CACHE_MAX_AGE_DAYS * 86400
    pruned = {}
    for url, entry in cache.items():
        try:
            fetched = datetime.strptime(entry["fetched_at"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if fetched.timestamp() >= cutoff:
            pruned[url] = entry
    return pruned


def enrich_digest(digest: dict, cache: dict) -> tuple[dict, int]:
    today = now_utc().strftime("%Y-%m-%d")
    fetches = 0

    for section in digest.get("sections", []):
        for item in section.get("items", []):
            if item.get("category") == "people":
                continue  # people cards use avatars (or none); don't scrape profile pages
            if item.get("image_url"):
                continue

            canonical_url = item.get("canonical_url") or item.get("url")
            if not canonical_url:
                continue

            cached = cache.get(canonical_url)
            if cached is not None:
                item["image_url"] = cached.get("image_url")
                continue

            if fetches >= MAX_FETCHES_PER_RUN:
                continue

            image_url = fetch_og_image(item["url"])
            fetches += 1
            cache[canonical_url] = {"image_url": image_url, "fetched_at": today}
            item["image_url"] = image_url

    return digest, fetches


def main() -> None:
    ensure_dirs()
    digest = read_json(WORK_DIR / "digest.json", default=None)
    if digest is None:
        raise SystemExit("data/_work/digest.json not found - run build_digest.py first")

    cache = _prune_cache(_load_cache())
    digest, fetches = enrich_digest(digest, cache)
    write_json(WORK_DIR / "digest.json", digest)
    write_json(CACHE_PATH, cache)

    print(f"Fetched {fetches} preview images ({len(cache)} cached)")


if __name__ == "__main__":
    main()
