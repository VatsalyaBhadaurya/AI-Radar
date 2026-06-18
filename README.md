# AI Engineering Radar

**A daily intelligence briefing for AI engineers, robotics builders, and embedded/edge ML practitioners.**

AI Engineering Radar continuously scans the AI ecosystem — model releases, inference
and infra tooling, robotics & embodied AI, VLM/VLA and multimodal research, papers
and benchmarks, open-source repo activity, startup hiring, and funding news — and
distills it into a single, ranked daily digest. No sign-up, no inbox clutter, no
hype-driven feed: every item is scored for relevance and engineering value before
it's surfaced.

**Live digest:** https://vatsalyabhadaurya.github.io/AI-Radar/

## What you get

- **Daily digest** — a ranked, de-duplicated summary of what actually matters in AI
  engineering today, refreshed automatically every 24 hours.
- **Matches Your Stack** — items personalized to a configurable technology profile
  (frameworks, hardware, research areas), surfaced ahead of generic noise.
- **Hiring For You** — curated job postings (RemoteOK, Hacker News Jobs/YC, We Work
  Remotely) ranked against a precise experience profile — skills, domains, and
  career stage — so intern/entry-level/new-grad roles that genuinely match come
  first and senior-only postings are filtered down.
- **People Radar** — researchers and builders (Indian and international) doing
  meaningful work in your domain, discovered from public APIs (arXiv, GitHub,
  Hugging Face, Semantic Scholar) and ranked by domain overlap, influence
  (citations / stars / likes / h-index), and recent activity — with a guaranteed
  India/international geography mix and direct links to each person's public
  profiles. (No LinkedIn scraping — see "How it works".)
- **Recent Funding** — fresh startup funding and acquisition news (TechCrunch
  Startups, Crunchbase News, MedCity News for medtech), ranked by relevance to your
  focus areas — AI, robotics, medtech, and industrial automation.
- **Build Today** — hands-on project picks worth trying this week.
- **Robotics & Embodied AI / VLM & Multimodal / Papers & Benchmarks / Repo Watch /
  Industry Moves** — dedicated sections so you can scan exactly the slice of the
  ecosystem you care about.
- **Archive & methodology** — every day's digest is preserved and browsable, and the
  full scoring methodology is published and transparent.

## How it works

AI Engineering Radar runs as a fully automated, self-hosted pipeline:

1. **Collect** — pulls from a curated registry of RSS/Atom feeds, arXiv listings,
   GitHub release feeds, job boards, and funding news sources. For **People Radar**
   it queries public, bot-friendly APIs (arXiv, GitHub Search, Hugging Face,
   Semantic Scholar) to discover people doing domain-relevant work. It deliberately
   does **not** scrape LinkedIn: LinkedIn is auth-walled, forbids scraping in its
   ToS, and blocks the datacenter IPs that the GitHub Actions runner uses — the
   APIs above surface the same people reliably and link out to their public profiles.
2. **Normalize & deduplicate** — cleans and merges near-duplicate stories so the
   same announcement isn't repeated across sources.
3. **Score** — every item is scored on relevance, novelty, source trust, and
   engineering value (with dedicated formulas for job postings and funding news,
   weighted against a configurable experience profile).
4. **Digest & publish** — the day's top items are organized into sections, rendered
   as a static site, and published — no servers, databases, or third-party services
   required.

The whole thing runs on a free GitHub Actions schedule and is served by GitHub
Pages, so it stays online and up to date with zero ongoing maintenance.

## Make it yours

Everything that personalizes the digest lives in a small set of config files —
no code changes required:

- **`config/profile.yaml`** — your experience profile: core skills, domains of
  interest, and career stage. Drives the "Hiring For You" ranking with precise
  skill/domain matching and entry-level vs. senior filtering.
- **`config/sources.yaml`** — the registry of tracked sources (feeds, job boards,
  funding news), each with a category and trust weight.
- **`config/taxonomy.yaml`** — keyword taxonomy used to categorize and score
  general digest items, including your "priority stack" for the "Matches Your
  Stack" section.
- **`config/scoring.yaml`** — scoring weights, thresholds, novelty decay, and
  per-section item limits.
- **`config/people.yaml`** — the "People Radar" config: domain search terms,
  which discovery APIs to use, India-affiliation keywords for the geography mix,
  and the domain/influence/recency weighting used to rank people.

See [`docs/method.html`](docs/method.html) for the full, published scoring
methodology.

## Running it yourself

```bash
pip install -r requirements.txt
cd scripts
python run_pipeline.py
```

This fetches every source in `config/sources.yaml`, scores and ranks the results,
and writes the digest to `docs/data/` and `docs/digest/` — the same files served by
the live site. Preview locally with:

```bash
python -m http.server 8000 --directory docs
```

## Deployment

1. Fork or clone this repo.
2. In **Settings → Pages**, set source to **Deploy from a branch**, branch `main`,
   folder `/docs`.
3. The `.github/workflows/daily-digest.yml` workflow runs on a daily schedule
   (06:00 UTC) and on manual dispatch, regenerating the digest and pushing the
   update — Pages picks it up automatically.

## Roadmap

- Email digest delivery via self-hosted [listmonk](https://listmonk.app/) once
  ranking quality is stable.
