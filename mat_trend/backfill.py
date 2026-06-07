"""Historical backfill of journal articles from Crossref.

RSS feeds only expose the current rolling window, so they cannot provide last
year's papers. Crossref indexes works by journal ISSN and publication date, with
titles, authors, DOIs, and dates (abstracts when the publisher deposits them) —
enough to feed the trend pipeline.

Each work is mapped to the same record schema as :mod:`mat_trend.rss`, so backfilled
rows flow through ``ingest.accumulate`` into ``data/<key>/<YYYY-MM>.csv`` and are
deduped against RSS-sourced rows by DOI.

Caveat: Crossref abstracts are frequently absent for these publishers, so backfilled
articles are usually topic-assigned on **title alone** (lower recall than RSS rows
that carry an abstract). This is acceptable for counting topic trends.

Crossref is free; passing a ``mailto`` uses the faster "polite" pool. Each journal
needs an ``issn`` in ``config/journals.json``.

(OpenAlex was the first choice — richer abstracts — but its API is unreachable from
some hosts/CI egress IPs; Crossref is used as the reliable default.)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable

from mat_trend.rss import RECORD_COLUMNS, strip_html

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    import requests

    from mat_trend.registry import Journal, JournalRegistry

CROSSREF_WORKS = "https://api.crossref.org/works"
ROWS = 200
DEFAULT_THROTTLE = 1.0
DEFAULT_RETRIES = 5
DEFAULT_BACKOFF = 2.0


def crossref_date(item: dict) -> str:
    """Best-effort ``YYYY-MM-DD`` from a Crossref work's date fields."""
    for key in ("published", "published-online", "published-print", "issued", "created"):
        node = item.get(key)
        parts = (node or {}).get("date-parts") if isinstance(node, dict) else None
        if parts and isinstance(parts[0], list) and parts[0] and parts[0][0]:
            y = parts[0][0]
            m = parts[0][1] if len(parts[0]) > 1 else 1
            d = parts[0][2] if len(parts[0]) > 2 else 1
            return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"
    return ""


def _authors(item: dict) -> str:
    names = []
    for a in item.get("author", []) or []:
        name = " ".join(p for p in (a.get("given"), a.get("family")) if p).strip()
        if not name:
            name = (a.get("name") or "").strip()
        if name:
            names.append(name)
    return ", ".join(f"'{n}'" for n in names)


def item_to_record(item: dict, journal_label: str, family: str) -> dict | None:
    titles = item.get("title") or []
    title = strip_html(titles[0]) if titles else ""
    if not title:
        return None
    doi = (item.get("DOI") or "").strip()
    return {
        "title": title,
        "journal": journal_label,
        "family": family,
        "published_date": crossref_date(item),
        "authors": _authors(item),
        "abstract": strip_html(item.get("abstract")),  # often empty for these publishers
        "doi": doi,
        "link": (item.get("URL") or (f"https://doi.org/{doi}" if doi else "")),
    }


def fetch_works(
    issn: str,
    journal_label: str,
    family: str,
    *,
    from_date: str,
    to_date: str,
    mailto: str = "",
    session: "requests.Session | None" = None,
    throttle: float = DEFAULT_THROTTLE,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    sleep=time.sleep,
    log: Callable[[str], None] = lambda *_: None,
) -> "pd.DataFrame":
    """Fetch all journal-article works for ``issn`` in ``[from_date, to_date]``."""
    import pandas as pd
    import requests

    sess = session or requests.Session()
    sess.headers.setdefault("User-Agent", f"mat-trend/0.1 (mailto:{mailto})" if mailto else "mat-trend/0.1")

    filt = f"issn:{issn},from-pub-date:{from_date},until-pub-date:{to_date},type:journal-article"
    records: list[dict] = []
    cursor = "*"
    while cursor:
        params = {"filter": filt, "rows": ROWS, "cursor": cursor,
                  "select": "DOI,title,author,abstract,URL,published,issued,created"}
        if mailto:
            params["mailto"] = mailto
        data = None
        for attempt in range(retries + 1):
            try:
                resp = sess.get(CROSSREF_WORKS, params=params, timeout=60)
                if resp.status_code == 429:
                    if attempt < retries:
                        sleep(backoff * (2 ** attempt))
                        continue
                    raise RuntimeError("Crossref rate-limited (429) after retries")
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception:
                if attempt < retries:
                    sleep(backoff * (2 ** attempt))
                    continue
                raise
        message = data.get("message", {})
        items = message.get("items", [])
        for item in items:
            rec = item_to_record(item, journal_label, family)
            if rec:
                records.append(rec)
        cursor = message.get("next-cursor")
        log(f"  {journal_label}: {len(records)} works so far…")
        if not items:
            break
        sleep(throttle)

    return pd.DataFrame(records, columns=RECORD_COLUMNS)


def backfill_journal(
    journal: "Journal",
    year: int,
    data_dir,
    *,
    mailto: str = "",
    session=None,
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Backfill one journal-year into the monthly store. Returns ``{bucket: n_added}``."""
    from mat_trend.ingest import accumulate

    if not journal.issn:
        log(f"backfill: {journal.key} has no ISSN — skipped")
        return {}
    df = fetch_works(
        journal.issn, journal.label, journal.family,
        from_date=f"{year}-01-01", to_date=f"{year}-12-31",
        mailto=mailto, session=session, log=log,
    )
    added = accumulate(df, journal.key, data_dir)
    log(f"backfill: {journal.key} {year} -> +{sum(added.values())} new ({len(df)} fetched)")
    return added


def backfill_all(
    registry: "JournalRegistry",
    years: list[int],
    data_dir,
    *,
    only: set[str] | None = None,
    mailto: str = "",
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Backfill every journal (or ``only``) across ``years``. Returns ``{key: total_added}``."""
    import requests

    session = requests.Session()
    totals: dict[str, int] = {}
    for journal in registry.journals:
        if only and journal.key not in only:
            continue
        added_total = 0
        for year in years:
            try:
                added = backfill_journal(journal, year, data_dir, mailto=mailto, session=session, log=log)
                added_total += sum(added.values())
            except Exception as exc:  # best-effort per journal-year
                log(f"backfill: {journal.key} {year} failed ({type(exc).__name__}: {exc})")
        totals[journal.key] = added_total
    return totals
