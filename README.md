<h1>
  <img src="docs/assets/logo.png" alt="Bio Trends logo" height="48" align="absmiddle" />
  Bio Trends in Journals
</h1>

Track what biology is *actually* publishing. **Mater-trend** ingests recent articles
from the flagship biology journals and their sister titles via **RSS**, auto-labels
each with research topics, and surfaces the **top**, **emerging**, and **fading**
areas month over month — with the papers behind every trend a click away.

It is the biology sibling of [AI-trend](../AI-trend/) and reuses its
proven, deterministic pipeline; only the ingestion layer is different (RSS feeds
instead of conference paper dumps).

Families: **Nature · Science · Cell Press** (flagships + key biology sister journals).
Feed catalog: **[Journal-RSS.md](Journal-RSS.md)**.

## What it does

- **Topic trends** — top / emerging / fading topics per journal (or family),
  viewable at **Year / Quarter / Month** granularity (the site defaults to Year),
  computed from article counts and period-over-period change.
- **Browse articles** — filter by family / journal / month / topic, search titles,
  abstracts, and authors; sort by recency or citations.
- **Citations & rising papers** — Crossref `is-referenced-by-count` by DOI, tracked
  over time: each paper is snapshotted on first ingest and then up to twice more,
  monthly, within three months of publication (≤3 snapshots). The gain across
  snapshots is the **rising** signal — sort Rising Stars by "Rising (citation gain)".
  History lives in `citations/<journal>/<year>.json` (committed). Follows the Zotero
  *Citation Counts Manager* approach.
- **Static site** — a fast GitHub Pages browser, rebuilt from the data.

The only non-deterministic step is **topic curation** (deciding which keywords map
to which topic); everything else is pure, reproducible Python.

The biology taxonomy (`config/taxonomy.json`, 33 topics) is **derived from the
literature**: scispaCy NER over the ~59k-title corpus surfaces candidate keywords
(`mat-trend candidates`), the `/curate-topics` skill decides each
(existing / new / noise / other), and `mat-trend curate` folds them in — the same
extraction→curation loop as AI-trend.

## How it works

```
Journal-RSS.md ──▶ ingest (poll feeds) ──▶ assign topics ──▶ trends ──▶ static site
(config/journals.json) (data/<key>/<YYYY-MM>.csv)  (substring   (docs/, GitHub Pages)
                        accumulate + dedup by DOI    match vs
                                                     biology taxonomy)
```

RSS feeds are a **rolling window** (latest issue / recent items). Mater-trend polls
them regularly and **accumulates** into a deduplicated per-journal-month store, so
trends build up over time. Running the pipeline with no new items just re-derives
the outputs — safe to run anytime.

**Historical backfill.** RSS only carries the current issue, so to see a full year
of trends use `mat-trend backfill --years 2024,2025`. It pulls historical articles
(title, authors, DOI, date — abstracts when available) from **Crossref** by ISSN
into the same monthly store, deduped by DOI against RSS rows. The site shards
browsable papers **per (journal, year)** and the page lazy-loads only the years you
view, so the full multi-year corpus is browsable without a heavy initial load
(`export-site`/`refresh` accept `--shard-years N` to cap browsable years; trends
always use the full history).

**Polling cadence.** Each journal declares a publication **frequency** in
[`Journal-RSS.md`](Journal-RSS.md) / `config/journals.json`
(`continuous` · `weekly` · `biweekly` · `monthly`). `ingest` polls a feed only when
it is *due* — at least its cadence interval since the last poll (tracked in
`data/.ingest_state.json`). So you can run `ingest`/`refresh` on a frequent schedule
(e.g. weekly) and each journal is fetched no more often than it actually publishes;
`--force` overrides the due-check.

## Usage

All commands run from the repo root, isolated from user site-packages:

```bash
PYTHONNOUSERSITE=1 ./env/bin/mat-trend <command>
```

| Command | What it does |
|---|---|
| `check-feeds [--check]` | List tracked feeds (with frequency); `--check` probes each over the network |
| `ingest [--journal KEY] [--force]` | Poll feeds that are *due* per their frequency; accumulate into `data/<key>/<YYYY-MM>.csv` |
| `backfill --years 2024,2025 [--journal KEY]` | Fetch historical articles from Crossref into the same store |
| `assign <csv>` | Assign biology topics to a papers CSV (deterministic) |
| `trends [--bucket year\|quarter\|month] [--group-by journal\|family]` | Compute top/emerging/fading |
| `candidates <csv>` | Extract candidate keywords (scispaCy) for taxonomy curation |
| `curate <decision.json>` | Apply a curation decision to the taxonomy |
| `citations [--journal KEY] [--years ...]` | Track Crossref citation counts per paper (snapshot on addition + monthly for 3 months) |
| `export-site` | Rebuild the GitHub Pages data (`docs/data/`) |
| `refresh [--no-ingest]` | Full pipeline: ingest → assign → trends → export-site |

Natural-language front doors (Claude Code skills): **`/add-journal`** (paste a feed
URL), **`/curate-topics`** (biology taxonomy curation), **`/track-journals`**
(verify feeds, discover new bio sister journals, poll & ingest).

### Setup (Python 3.10)

```bash
conda create -y -p ./env python=3.10
PYTHONNOUSERSITE=1 ./env/bin/pip install -e .
# optional extras:
#   '.[citations]' / '.[backfill]'  requests (citation counts / Crossref backfill)
#   '.[dev]'                        pytest + coverage
#   '.[curate]'                     scispaCy NER for keyword extraction; also install the model:
PYTHONNOUSERSITE=1 ./env/bin/pip install -e '.[curate]'
PYTHONNOUSERSITE=1 ./env/bin/pip install \
  "https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.1/en_core_sci_lg-0.5.1.tar.gz"
```

### Re-deriving the taxonomy from the corpus

```bash
# 1. extract candidate keywords from all titles (scispaCy NER)
PYTHONNOUSERSITE=1 ./env/bin/mat-trend candidates <all-titles.csv> \
  --model en_core_sci_lg --threshold 40 -o /tmp/candidates.json
# 2. run the /curate-topics skill to decide each candidate -> /tmp/decision.json
# 3. apply, then re-assign + re-trends + re-export
PYTHONNOUSERSITE=1 ./env/bin/mat-trend curate /tmp/decision.json
PYTHONNOUSERSITE=1 ./env/bin/mat-trend refresh --no-ingest
```

### Quick start

```bash
PYTHONNOUSERSITE=1 ./env/bin/mat-trend check-feeds --check   # confirm feeds are live
PYTHONNOUSERSITE=1 ./env/bin/mat-trend refresh               # ingest → assign → trends → site
python -m http.server --directory docs                       # preview the site
```

## Monthly automation

`.github/workflows/refresh.yml` runs on a monthly cron (and `workflow_dispatch`):
`check-feeds` → `refresh` → open a PR. Merging republishes the site (Pages deploys
from `main` / `/docs`). A `scripts/monthly_refresh.sh` + `monthly_prompt.md` pair is
provided for running the agentic pipeline locally via `claude -p`.

## Adding a journal or feed

1. Add a row to **[Journal-RSS.md](Journal-RSS.md)** and a matching entry to
   `config/journals.json` (`key` / `label` / `family` / `feeds[]`).
2. `mat-trend check-feeds --check` to confirm it's live.
3. `mat-trend refresh`.

See **[CLAUDE.md](CLAUDE.md)** for architecture and the environment rule.
