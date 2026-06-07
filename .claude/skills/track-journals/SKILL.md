---
name: track-journals
description: Keep Mater-trend's journal feeds current — verify liveness, discover new materials-science journals, then poll and ingest.
---

# track-journals

The watch loop for tracked materials-science journals. Run commands as
`PYTHONNOUSERSITE=1 ./env/bin/mat-trend ...` from the repo root.

## Procedure

1. **Verify feeds** — `mat-trend check-feeds --check`. For each DEAD feed, try to
   find a working URL (the journal may have changed its RSS path); if found, update
   `Journal-RSS.md` + `config/journals.json`. If not, mark `Status ✗` and note it.

2. **Discover new materials-science journals** (optional, periodic): for each family
   (Nature Portfolio, Science, Cell Press, Wiley, ACS, RSC, Elsevier), check whether a
   notable materials journal is missing from `config/journals.json`. If so, follow the
   `add-journal` skill to register and verify its feed. Prefer materials-focused
   (`focus: high`) titles.

3. **Ingest** — `mat-trend ingest` (all journals) or `--journal <keys>` for a subset.
   This is the step that captures the current rolling window; run it on a schedule
   so history accumulates.

4. **Refresh derived outputs** — `mat-trend refresh --no-ingest` (assign → trends →
   export-site) if you ingested separately, or just `mat-trend refresh` to do both.

5. **Commit / PR** — if `Journal-RSS.md`, `config/`, or `docs/` changed, open a PR
   summarising new articles, journals added, and dead feeds.

## Principles

- Only liveness checks and new-journal discovery touch the network/web; ingestion,
  assignment, trends, and site export are deterministic CLI tools.
- RSS is a rolling window — regular polling is what builds the month-over-month
  history that trends depend on. Don't expect back-history from a single run.
