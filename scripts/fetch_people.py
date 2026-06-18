"""Discover people (researchers + builders) doing domain-relevant work.

Pulls from four legitimate, bot-friendly public APIs:

  - arXiv API            -> researchers (authors of recent papers)
  - GitHub Search API    -> builders shipping repos
  - Hugging Face API     -> people publishing models
  - Semantic Scholar API -> author profiles + citation signals

This intentionally does NOT touch LinkedIn (auth-walled, ToS-forbidden, blocks
the CI's datacenter IPs). Every source here is public and rate-limit friendly,
and each failure is swallowed so one bad source never breaks the pipeline.

Output: a list of raw person records written to data/_work/people_raw.json
Each record (before merge/score in build_people.py) looks like:
    {
      "name", "source", "profile_url", "affiliation", "location", "bio",
      "topics": [...], "recent_work": [{"title","url","date"}],
      "signals": {"citations","h_index","github_stars","hf_likes"},
      "last_active": iso|None, "avatar_url": str|None,
    }
"""
from __future__ import annotations

import os
import sys
import time
from calendar import timegm
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import requests

from common import WORK_DIR, ensure_dirs, load_people_config, write_json

REQUEST_TIMEOUT = 20
USER_AGENT = "ai-engineering-radar/1.0 (+https://github.com/)"
ARXIV_API = "http://export.arxiv.org/api/query"
GITHUB_SEARCH_API = "https://api.github.com/search/repositories"
GITHUB_USER_API = "https://api.github.com/users/"
HF_MODELS_API = "https://huggingface.co/api/models"
S2_PAPER_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_AUTHOR_API = "https://api.semanticscholar.org/graph/v1/author/"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _struct_to_iso(struct) -> str | None:
    if not struct:
        return None
    return datetime.fromtimestamp(timegm(struct), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# arXiv
# --------------------------------------------------------------------------- #
def fetch_arxiv(cfg: dict) -> list[dict]:
    src = cfg["sources"]["arxiv"]
    if not src.get("enabled", True):
        return []
    people: list[dict] = []
    max_authors = src.get("max_authors_per_paper", 6)

    for category in src.get("categories", []):
        url = (
            f"{ARXIV_API}?search_query=cat:{category}"
            f"&sortBy=submittedDate&sortOrder=descending"
            f"&max_results={src.get('max_results_per_category', 50)}"
        )
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] arXiv {category} failed: {exc}", file=sys.stderr)
            continue

        for entry in feed.entries:
            title = (entry.get("title") or "").strip().replace("\n", " ")
            link = (entry.get("link") or "").strip()
            published = _struct_to_iso(entry.get("published_parsed") or entry.get("updated_parsed"))
            authors = entry.get("authors") or []
            for author in authors[:max_authors]:
                name = (author.get("name") or "").strip()
                if not name:
                    continue
                affiliation = (author.get("arxiv_affiliation") or "").strip()
                people.append({
                    "name": name,
                    "source": "arXiv",
                    "profile_url": f"https://arxiv.org/a/{quote_plus(name)}.html",
                    "discovery_url": f"https://arxiv.org/search/?searchtype=author&query={quote_plus(name)}",
                    "affiliation": affiliation,
                    "location": "",
                    "bio": "",
                    "topics": [category],
                    "recent_work": [{"title": title, "url": link, "date": published}] if title else [],
                    "signals": {},
                    "last_active": published,
                    "avatar_url": None,
                })
        time.sleep(0.5)  # arXiv asks for a short delay between calls

    return people


# --------------------------------------------------------------------------- #
# GitHub Search
# --------------------------------------------------------------------------- #
def _github_headers() -> dict:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_github(cfg: dict) -> list[dict]:
    src = cfg["sources"]["github"]
    if not src.get("enabled", True):
        return []
    headers = _github_headers()
    min_stars = src.get("min_stars", 40)
    include_orgs = src.get("include_orgs", False)
    pushed_since = (_now() - timedelta(days=cfg.get("recency_half_life_days", 45) * 3)).strftime("%Y-%m-%d")

    # Aggregate the best repo per owner.
    by_owner: dict[str, dict] = {}
    for term in cfg.get("search_terms", [])[: src.get("max_queries", 6)]:
        query = f"{term} stars:>={min_stars} pushed:>={pushed_since}"
        url = (
            f"{GITHUB_SEARCH_API}?q={quote_plus(query)}"
            f"&sort=stars&order=desc&per_page={src.get('per_query', 15)}"
        )
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            repos = resp.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] GitHub search '{term}' failed: {exc}", file=sys.stderr)
            continue

        for repo in repos:
            owner = repo.get("owner") or {}
            login = owner.get("login")
            if not login:
                continue
            if owner.get("type") == "Organization" and not include_orgs:
                continue
            stars = repo.get("stargazers_count", 0)
            existing = by_owner.get(login)
            if existing and existing["signals"].get("github_stars", 0) >= stars:
                # Keep the higher-starred repo as the representative work.
                existing["topics"] = sorted(set(existing["topics"]) | set(repo.get("topics") or []))
                continue
            by_owner[login] = {
                "name": login,
                "source": "GitHub",
                "profile_url": owner.get("html_url") or f"https://github.com/{login}",
                "discovery_url": owner.get("html_url") or f"https://github.com/{login}",
                "affiliation": "",
                "location": "",
                "bio": (repo.get("description") or "").strip(),
                "topics": list(repo.get("topics") or []),
                "recent_work": [{
                    "title": repo.get("full_name") or repo.get("name"),
                    "url": repo.get("html_url"),
                    "date": repo.get("pushed_at"),
                }],
                "signals": {"github_stars": stars},
                "last_active": repo.get("pushed_at"),
                "avatar_url": owner.get("avatar_url"),
            }
        time.sleep(1.0)  # GitHub search is rate-limited (esp. unauthenticated)

    # Enrich the top owners with real name / location / bio.
    top = sorted(by_owner.values(), key=lambda p: p["signals"].get("github_stars", 0), reverse=True)
    for person in top[: src.get("max_user_lookups", 25)]:
        login = person["profile_url"].rstrip("/").split("/")[-1]
        try:
            resp = requests.get(GITHUB_USER_API + login, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            user = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] GitHub user '{login}' lookup failed: {exc}", file=sys.stderr)
            continue
        if user.get("type") == "Organization" and not include_orgs:
            person["_drop"] = True
            continue
        if user.get("name"):
            person["name"] = user["name"]
        person["location"] = (user.get("location") or "").strip()
        if user.get("bio"):
            person["bio"] = (person["bio"] + " " + user["bio"]).strip()
        if user.get("company"):
            person["affiliation"] = user["company"].lstrip("@").strip()
        time.sleep(0.3)

    return [p for p in by_owner.values() if not p.get("_drop")]


# --------------------------------------------------------------------------- #
# Hugging Face
# --------------------------------------------------------------------------- #
def fetch_huggingface(cfg: dict) -> list[dict]:
    src = cfg["sources"]["huggingface"]
    if not src.get("enabled", True):
        return []
    by_author: dict[str, dict] = {}

    for term in cfg.get("search_terms", [])[: src.get("max_queries", 6)]:
        url = (
            f"{HF_MODELS_API}?search={quote_plus(term)}"
            f"&sort=likes&direction=-1&limit={src.get('per_query', 20)}"
        )
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            models = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] Hugging Face '{term}' failed: {exc}", file=sys.stderr)
            continue

        for model in models:
            model_id = model.get("id") or model.get("modelId") or ""
            if "/" not in model_id:
                continue  # skip canonical/no-author models
            author = model_id.split("/", 1)[0]
            likes = model.get("likes", 0) or 0
            last_modified = model.get("lastModified")
            tags = [t for t in (model.get("tags") or []) if isinstance(t, str)]
            if model.get("pipeline_tag"):
                tags.append(model["pipeline_tag"])

            person = by_author.get(author)
            if person is None:
                person = {
                    "name": author,
                    "source": "Hugging Face",
                    "profile_url": f"https://huggingface.co/{author}",
                    "discovery_url": f"https://huggingface.co/{author}",
                    "affiliation": "",
                    "location": "",
                    "bio": "",
                    "topics": [],
                    "recent_work": [],
                    "signals": {"hf_likes": 0},
                    "last_active": None,
                    "avatar_url": None,
                }
                by_author[author] = person
            person["signals"]["hf_likes"] = person["signals"].get("hf_likes", 0) + likes
            person["topics"] = sorted(set(person["topics"]) | set(tags))
            person["recent_work"].append({
                "title": model_id,
                "url": f"https://huggingface.co/{model_id}",
                "date": last_modified,
            })
            if last_modified and (person["last_active"] is None or last_modified > person["last_active"]):
                person["last_active"] = last_modified
        time.sleep(0.5)

    # Keep recent_work tidy (top 3 by appearance).
    for person in by_author.values():
        person["recent_work"] = person["recent_work"][:3]
    return list(by_author.values())


# --------------------------------------------------------------------------- #
# Semantic Scholar
# --------------------------------------------------------------------------- #
def fetch_semantic_scholar(cfg: dict) -> list[dict]:
    src = cfg["sources"]["semantic_scholar"]
    if not src.get("enabled", True):
        return []

    author_ids: dict[str, str] = {}  # authorId -> name
    for term in cfg.get("search_terms", [])[: src.get("max_queries", 6)]:
        url = (
            f"{S2_PAPER_SEARCH}?query={quote_plus(term)}"
            f"&limit={src.get('per_query', 20)}"
            f"&fields=title,year,authors.authorId,authors.name"
        )
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            papers = resp.json().get("data", []) or []
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] Semantic Scholar search '{term}' failed: {exc}", file=sys.stderr)
            continue
        for paper in papers:
            for author in (paper.get("authors") or [])[:5]:
                aid = author.get("authorId")
                if aid and aid not in author_ids:
                    author_ids[aid] = author.get("name") or ""
        time.sleep(1.0)  # S2 is strict on unauthenticated rate limits

    people: list[dict] = []
    for aid in list(author_ids)[: src.get("max_author_lookups", 30)]:
        url = (
            f"{S2_AUTHOR_API}{aid}"
            "?fields=name,affiliations,homepage,citationCount,hIndex,paperCount,url"
        )
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            author = resp.json()
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] Semantic Scholar author '{aid}' failed: {exc}", file=sys.stderr)
            time.sleep(1.0)
            continue
        name = (author.get("name") or author_ids.get(aid) or "").strip()
        if not name:
            continue
        affiliations = [a for a in (author.get("affiliations") or []) if a]
        people.append({
            "name": name,
            "source": "Semantic Scholar",
            "profile_url": author.get("url") or f"https://www.semanticscholar.org/author/{aid}",
            "discovery_url": author.get("homepage") or author.get("url")
            or f"https://www.semanticscholar.org/author/{aid}",
            "affiliation": ", ".join(affiliations),
            "location": "",
            "bio": "",
            "topics": [],
            "recent_work": [],
            "signals": {
                "citations": author.get("citationCount", 0) or 0,
                "h_index": author.get("hIndex", 0) or 0,
            },
            "last_active": None,
            "avatar_url": None,
        })
        time.sleep(1.0)

    return people


def fetch_all(cfg: dict) -> list[dict]:
    people: list[dict] = []
    for label, fn in (
        ("arXiv", fetch_arxiv),
        ("GitHub", fetch_github),
        ("Hugging Face", fetch_huggingface),
        ("Semantic Scholar", fetch_semantic_scholar),
    ):
        print(f"  discovering people via {label} ...")
        found = fn(cfg)
        print(f"    -> {len(found)} records")
        people.extend(found)
    return people


def main() -> None:
    ensure_dirs()
    cfg = load_people_config()
    people = fetch_all(cfg)
    write_json(WORK_DIR / "people_raw.json", people)
    print(f"Wrote {len(people)} raw people records")


if __name__ == "__main__":
    main()
