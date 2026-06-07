# CLAUDE.md — Mater-trend architecture & working rules

Mater-trend tracks materials-science research trends from journal **RSS feeds**
(Nature, Science, Cell Press, Wiley, ACS, RSC, Elsevier families). It is the sibling
of `../Bio-trend/` and reuses that project's deterministic pipeline, swapping the
journal registry and topic taxonomy for materials science.

## Critical environment rule

Run **everything** isolated from user site-packages, against the repo-local env:

```bash
PYTHONNOUSERSITE=1 ./env/bin/mat-trend <command>
PYTHONNOUSERSITE=1 ./env/bin/python -m pytest --cov=mat_trend
```

The core pipeline needs only `pandas`, `feedparser`, `python-dateutil` (Python
3.10+). The optional `candidates` extra pulls in **spaCy** plus a model
(`en_core_web_lg`); install it only when curating the taxonomy.

## Pipeline

```
config/journals.json ─▶ rss.fetch_journal ─▶ ingest.accumulate ─▶ assign ─▶ trends ─▶ site
   (Journal-RSS.md)       (feedparser)        data/<key>/<YYYY-MM>.csv
```

- **`rss.py`** — fetch + normalise feed entries (title, link, DOI, authors,
  abstract, ISO date). Sends a browser `User-Agent` (Science / Cell / Wiley / ACS are
  Cloudflare-protected and 403 a naive client).
- **`ingest.py`** — accumulate into `data/<journal_key>/<YYYY-MM>.csv`, bucketed by
  publication month, **deduped by DOI → link → title**. Idempotent. **Cadence-aware**:
  each journal declares a `frequency` (`continuous`/`weekly`/`biweekly`/`monthly`) and
  is polled only when due, tracked in `data/.ingest_state.json` (`--force` overrides).
- **`assign.py`** — deterministic case-sensitive substring match over lowercased
  `title + " " + abstract`. **Taxonomy keywords must be lowercase** to match, and
  should avoid short ambiguous acronyms (`led`, `her`, `oer`, `tem`, `sem`) that
  substring-match unrelated words — prefer distinctive multiword phrases.
- **`backfill.py`** — historical fetch from **Crossref** by ISSN (`mat-trend
  backfill --years 2024,2025`), mapped to the same record schema and merged via
  `ingest.accumulate`. Crossref abstracts are often empty for these publishers, so
  backfilled rows are usually assigned on title alone. (OpenAlex source IDs are also
  stored in config — richer abstracts — but its API is unreachable from some egress
  IPs, so Crossref is the default.)
- **`trends.py`** — top/emerging/fading per *(group, period)* where group is a
  journal (default) or family, and period is **year / quarter / month**. The site
  exports all three granularities and defaults to year.
- **`site.py`** — exports `docs/data/{manifest,trends}.json` + **per-(journal,year)**
  paper shards (`papers/<key>_<YYYY>.json`) for the static GitHub Pages browser in
  `docs/`, which lazy-loads only the years viewed. `trends.json` is keyed by bucket
  (`{year, quarter, month}`). Shards omit zero-topic papers (`topiced_only`) and cap
  authors; `--shard-years N` caps browsable years (trends keep full history).
- **`citations.py`** — citation counts by DOI (Zotero Citation Counts Manager
  approach), **tracked over time**: snapshot on addition + up to two monthly updates
  within 3 months of publication (≤3), so the gain = "rising" signal. Crossref
  (`is-referenced-by-count`, key-less, one paginated query per journal-year) is the
  default. **Optional Semantic Scholar + OpenAlex sources** run **in parallel**
  (`fetch_counts_multi`, one thread/session each) and merge per-DOI by **max** for
  fuller coverage — S2 via its batch endpoint (≤500 DOIs/call, ~1 req/s), OpenAlex
  via the free single-work endpoint (its bulk list endpoint is metered). Keys come
  from `$S2_API_KEY` / `$OPENALEX_API_KEY` (or `--s2-key`/`--openalex-key`); toggle
  with `--no-crossref`/`--no-s2`/`--no-openalex`. Never store keys in the repo (see
  `.env.example`; `.env` is gitignored). History is committed at
  `citations/<key>/<year>.json` (`{doi: [[date, count], …]}`), surfaced on cards as
  `· N cites · ▲ +Δ` and via the Rising sort. CLI: `mat-trend citations`.
- **`candidates.py` / `curate_io.py`** — the taxonomy-curation seam (spaCy NER +
  decision apply). `candidates.py` does a single-pass `nlp.pipe` over titles
  (document-frequency + examples), scaling to large corpora. The reasoning is the
  `/curate-topics` skill. The 33-topic taxonomy is **seeded by hand** to cover the
  major materials-science research themes; the candidates→curate loop expands it from
  the accumulated corpus over time. Needs the `[curate]` extra + the `en_core_web_lg`
  model (`python -m spacy download en_core_web_lg`).

## Config is the source of truth

- `config/journals.json` — tracked journals + feeds (mirrors `Journal-RSS.md`);
  **ordered by `impact_factor`** (the site preserves this order in pickers). Each also
  carries `frequency` (poll cadence), `openalex` (source id) and `issn` (Crossref
  backfill). The per-feed `focus` field is `high` (materials-dedicated) or `mixed`
  (multidisciplinary).
- `config/taxonomy.json` — materials topic → keywords (order significant, lowercase).
- `config/useless_keywords.json` — noise blocklist (filters candidate extraction only).

Adding a journal/feed/topic is a **config edit, not a code change**.

## Data identity comes from file location

A row's journal = its folder name (`data/<key>/`); its period = the filename stem
(`2026-06`). In-file columns are for display, not identity — same discipline as
Bio-trend.

## Tests

`PYTHONNOUSERSITE=1 ./env/bin/python -m pytest`. The deterministic core (assign,
trends, ingest, registry, curate_io, site, refresh, rss parsing) is covered ≥80%.
Network (`citations`) and model (`candidates`) modules are optional extras and are
exercised via mocks / left to manual runs, mirroring Bio-trend.

## Gotchas

- RSS feeds only carry recent items — history is built by **repeated polling**, so
  the first `ingest` captures only what is currently live.
- DOIs are present in most feeds but not all (some Nature subject-feed entries lack
  them); dedup falls back to link, then title.
- Feed URLs in `config/journals.json` are mostly **constructed from publisher
  patterns and not yet verified live** (Status `?` in `Journal-RSS.md`) — run
  `check-feeds --check` and fix/mark any dead ones. RSC feeds are **HTTP-only**
  (`feeds.rsc.org`); Wiley feed paths use the **e-ISSN without hyphens** (distinct
  from the `issn` ISSN-L used for Crossref).
