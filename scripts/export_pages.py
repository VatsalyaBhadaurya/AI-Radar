"""Export pipeline results to docs/ for GitHub Pages.

Writes:
  - docs/data/latest.json
  - docs/data/archive/<date>.json
  - docs/data/archive_index.json   (list of available archive dates)
  - docs/data/sources.json         (source registry, for the Sources page)
  - docs/digest/latest.html
  - docs/digest/<date>.html

Input: data/_work/digest.json
"""
from __future__ import annotations

import html

from common import (
    ARCHIVE_DIR, DIGEST_DIR, DATA_DIR, WORK_DIR,
    ensure_dirs, load_sources, read_json, write_json,
)

PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · AI Engineering Radar</title>
<link rel="stylesheet" href="../assets/styles.css?v=2">
</head>
<body>
<header class="site-header">
  <a class="brand" href="../index.html">AI Engineering Radar</a>
  <nav>
    <a href="../index.html">Home</a>
    <a href="../archive.html">Archive</a>
    <a href="../sources.html">Sources</a>
    <a href="../method.html">Method</a>
  </nav>
</header>
<main class="container">
  <h1>{headline}</h1>
  <p class="meta">Generated {generated_at}</p>
  <p class="summary">{summary}</p>
  {sections_html}
</main>
<footer class="site-footer">
  <p>AI Engineering Radar — generated automatically every 24 hours.</p>
</footer>
</body>
</html>
"""

SECTION_TEMPLATE = """
  <section class="digest-section">
    <h2>{name}</h2>
    {items_html}
  </section>
"""

EMPTY_SECTION = '<p class="empty">No items today.</p>'

ITEM_TEMPLATE = """
    <article class="item">
      {personal_badge}
      <h3><a href="{url}" target="_blank" rel="noopener">{title}</a></h3>
      <p class="item-meta">{source} · {published_at} · score {score}</p>
      <p class="item-summary">{summary}</p>
      <p class="item-why"><strong>Why it matters:</strong> {why_it_matters}</p>
      <p class="item-tags">{tags}</p>
    </article>
"""


def _render_item(item: dict) -> str:
    personal_badge = (
        '<span class="tag tag-personal">★ matches your stack</span>'
        if item.get("personal_match") else ""
    )
    return ITEM_TEMPLATE.format(
        url=html.escape(item["url"]),
        title=html.escape(item["title"]),
        source=html.escape(item["source"]),
        published_at=html.escape(item["published_at"]),
        score=item["score"],
        summary=html.escape(item["summary"]),
        why_it_matters=html.escape(item["why_it_matters"]),
        tags=" ".join(f'<span class="tag">{html.escape(t)}</span>' for t in item["tags"]),
        personal_badge=personal_badge,
    )


def _render_section(section: dict) -> str:
    if not section["items"]:
        items_html = EMPTY_SECTION
    else:
        items_html = "".join(_render_item(it) for it in section["items"])
    return SECTION_TEMPLATE.format(name=html.escape(section["name"]), items_html=items_html)


def render_digest_html(digest: dict) -> str:
    sections_html = "".join(_render_section(s) for s in digest["sections"])
    return PAGE_TEMPLATE.format(
        title=digest["date"],
        headline=html.escape(digest["headline"]),
        generated_at=html.escape(digest["generated_at"]),
        summary=html.escape(digest["summary"]),
        sections_html=sections_html,
    )


def update_archive_index(date: str) -> None:
    index_path = DATA_DIR / "archive_index.json"
    dates = read_json(index_path, default=[])
    if date not in dates:
        dates.append(date)
    dates = sorted(set(dates), reverse=True)
    write_json(index_path, dates)


def export_sources() -> None:
    sources = load_sources()
    public_sources = [
        {
            "id": s["id"],
            "name": s["name"],
            "type": s["type"],
            "category": s["category"],
            "trust": s["trust"],
        }
        for s in sources
    ]
    write_json(DATA_DIR / "sources.json", public_sources)


def main() -> None:
    ensure_dirs()
    digest = read_json(WORK_DIR / "digest.json", default=None)
    if digest is None:
        raise SystemExit("data/_work/digest.json not found - run build_digest.py first")

    date = digest["date"]

    # JSON outputs
    write_json(DATA_DIR / "latest.json", digest)
    write_json(ARCHIVE_DIR / f"{date}.json", digest)
    update_archive_index(date)
    export_sources()

    # HTML outputs
    html_content = render_digest_html(digest)
    (DIGEST_DIR / "latest.html").write_text(html_content, encoding="utf-8")
    (DIGEST_DIR / f"{date}.html").write_text(html_content, encoding="utf-8")

    print(f"Exported digest for {date} to docs/data and docs/digest")


if __name__ == "__main__":
    main()
