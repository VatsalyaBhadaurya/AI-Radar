"""Shared helpers for the AI Engineering Radar pipeline."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DOCS_DIR = ROOT / "docs"
DATA_DIR = DOCS_DIR / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
DIGEST_DIR = DOCS_DIR / "digest"
WORK_DIR = ROOT / "data" / "_work"

# Tracking params stripped during URL canonicalization.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "ref_src", "source", "fbclid", "gclid", "mc_cid", "mc_eid",
}


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources() -> list[dict]:
    return load_yaml(CONFIG_DIR / "sources.yaml")["sources"]


def load_taxonomy() -> dict:
    return load_yaml(CONFIG_DIR / "taxonomy.yaml")


def load_scoring() -> dict:
    return load_yaml(CONFIG_DIR / "scoring.yaml")


def load_profile() -> dict:
    return load_yaml(CONFIG_DIR / "profile.yaml")


def ensure_dirs() -> None:
    for d in (DATA_DIR, ARCHIVE_DIR, DIGEST_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)


def canonicalize_url(url: str) -> str:
    """Strip tracking params and fragments, normalize trailing slash."""
    if not url:
        return url
    parts = urlsplit(url)
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    ]
    path = parts.path.rstrip("/") or "/"
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(query), ""))


def make_id(canonical_url: str, title: str) -> str:
    h = hashlib.sha1()
    h.update((canonical_url or title).encode("utf-8"))
    return "item_" + h.hexdigest()[:12]


def normalize_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def to_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def clean_text(text: str, max_len: int = 400) -> str:
    if not text:
        return ""
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text
