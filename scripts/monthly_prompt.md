You are running the monthly Mater-trend refresh. Work from the repo root and run every
`mat-trend` command as `PYTHONNOUSERSITE=1 ./env/bin/mat-trend ...`.

Follow these steps:

1. **Verify feeds** — run `mat-trend check-feeds --check`. If any feed is DEAD,
   mark its `Status` as `✗` in `Journal-RSS.md` and note it; do not delete the row.

2. **(Optional) discover new materials-science journals** — follow the `track-journals`
   skill: if a tracked family has a notable materials-science journal not yet in
   `config/journals.json`, find its RSS URL, add a row to `Journal-RSS.md` and an
   entry to `config/journals.json`, and re-run `check-feeds --check` on it.

3. **Ingest + track citations + refresh**:
   - `mat-trend ingest` — poll feeds, accumulate new articles.
   - `mat-trend citations` — snapshot Crossref citation counts for due papers (new
     ones, and recent papers within 3 months of publication; ≤3 snapshots each).
   - `mat-trend refresh --no-ingest` — re-assign topics, recompute trends, rebuild
     `docs/data/` (surfacing the citation counts + rising deltas).

4. **(Optional) curate topics** — if you ingested a lot of new articles, follow the
   `curate-topics` skill on a recent CSV to fold genuinely new materials themes into
   the taxonomy, then re-run `mat-trend refresh`.

5. **Open a PR** — if `git status` shows changes under `config/`, `docs/`, or
   `Journal-RSS.md`, commit them and open a PR with `gh pr create`, summarising new
   article counts, any new journals added, and any dead feeds found.

Only feed-liveness checks and new-journal discovery use the network/web search;
ingestion, assignment, trends, and site export are deterministic CLI tools.
