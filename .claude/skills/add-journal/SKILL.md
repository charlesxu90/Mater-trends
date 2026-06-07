---
name: add-journal
description: Add a materials-science journal RSS feed to Mater-trend from a feed URL (or journal homepage), then ingest and refresh.
---

# add-journal

Natural-language front door: the user gives a journal name or an RSS feed URL; you
register it and run the pipeline. Run all commands as
`PYTHONNOUSERSITE=1 ./env/bin/mat-trend ...` from the repo root.

## Procedure

1. **Find the feed URL** (if only a journal name/homepage was given). Known patterns:
   - Nature Portfolio: `https://www.nature.com/<code>.rss` (journal) or
     `https://www.nature.com/subjects/<slug>.rss` (subject).
   - Cell Press: `https://www.cell.com/<slug>/current.rss` (and `/inpress.rss`).
   - Science (AAAS): `https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=<code>`.
   - Wiley: `https://onlinelibrary.wiley.com/feed/<eISSN-no-hyphens>/most-recent`.
   - ACS: `https://pubs.acs.org/action/showFeed?type=etoc&feed=rss&jc=<code>`.
   - RSC: `http://feeds.rsc.org/rss/<CODE>` (uppercase, **HTTP-only**).
   - Elsevier: `https://rss.sciencedirect.com/publication/science/<eISSN-no-hyphens>`.
   Use WebFetch/WebSearch to confirm the exact code/slug/ISSN if unsure.

2. **Register it** — add a row to `Journal-RSS.md` (Family, Journal, Key, Feed type,
   RSS URL, Focus, Status `?`) **and** a matching entry to `config/journals.json`
   (`key`, `label`, `family`, `impact_factor`, `frequency`, `issn`, `feeds: [{url,
   type, focus}]`). A journal may have multiple feeds. Keep `journals.json` ordered
   by `impact_factor` (the site preserves that order).

3. **Verify** — `mat-trend check-feeds --check`. If the new feed is live, update its
   `Status` to `✓`; if it 403s/dead, mark `✗` and stop (report the problem).

4. **Ingest + refresh** — `mat-trend ingest --journal <key>` then `mat-trend refresh`.

5. **Smoke-check + PR** — confirm `data/<key>/` has a CSV and the new journal appears
   in `docs/data/manifest.json`. Open a PR summarising the added feed.

## Notes

- `focus`: `high` for materials-dedicated journals, `mixed` for multidisciplinary
  flagships (where you may prefer a materials-science subject feed).
- Wiley/Elsevier feed URLs use the **e-ISSN without hyphens**; the `issn` field
  should hold the ISSN-L (used for Crossref backfill) — they can differ.
- RSS is a rolling window — the first ingest only captures currently-live items;
  history accrues over subsequent monthly runs (or use `backfill` for past years).
