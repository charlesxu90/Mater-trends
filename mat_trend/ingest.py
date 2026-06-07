"""Accumulate fetched RSS records into the per-journal-month data store.

RSS feeds are a rolling window: each poll sees only the latest items. To build a
history for trend analysis we **accumulate** — append newly-seen articles to a
month bucket and de-duplicate, so re-running mid-month is idempotent (adds only
genuinely new entries). This is the RSS analogue of AI-trend's merge-by-title
``ingest.process``.

Layout: ``data/<journal_key>/<YYYY-MM>.csv`` where the month is the article's
publication month (``published_date``), falling back to the ingestion month when a
feed entry carries no date.

De-dup key per bucket: DOI, then link, then title (first occurrence wins).
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from mat_trend.rss import RECORD_COLUMNS, fetch_journal

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from mat_trend.registry import Journal, JournalRegistry

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Tracks the last poll date per journal so ingestion honours each journal's
# publication cadence (declared in config/journals.json). Lives under the
# gitignored data dir.
STATE_FILENAME = ".ingest_state.json"

# How many days must pass before a journal of a given frequency is polled again.
# "continuous" (0) is always due; an unknown frequency defaults to monthly.
FREQUENCY_DAYS = {
    "continuous": 0,
    "daily": 1,
    "weekly": 7,
    "biweekly": 14,
    "monthly": 30,
}
DEFAULT_FREQUENCY_DAYS = 30


def _state_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / STATE_FILENAME


def load_state(data_dir: Path | str = DEFAULT_DATA_DIR) -> dict[str, str]:
    """``{journal_key: 'YYYY-MM-DD'}`` of last successful poll (empty if none)."""
    path = _state_path(data_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_state(state: dict[str, str], data_dir: Path | str = DEFAULT_DATA_DIR) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def is_due(last_poll: str | None, frequency: str, today: datetime.date) -> bool:
    """True if a journal of ``frequency`` is due to be polled again.

    Never polled -> due. ``continuous`` -> always due. Otherwise due once at least
    ``FREQUENCY_DAYS[frequency]`` days have elapsed since ``last_poll``.
    """
    if not last_poll:
        return True
    interval = FREQUENCY_DAYS.get(frequency, DEFAULT_FREQUENCY_DAYS)
    if interval == 0:
        return True
    try:
        last = datetime.date.fromisoformat(last_poll)
    except ValueError:
        return True
    return (today - last).days >= interval


def _dedup_key(row: "pd.Series") -> str:
    for col in ("doi", "link", "title"):
        value = row.get(col)
        if isinstance(value, str) and value.strip():
            return f"{col}:{value.strip()}"
    return ""


def _bucket_of(published_date: object, fallback_month: str) -> str:
    """``YYYY-MM`` from an ISO date string, else the ingestion-month fallback."""
    if isinstance(published_date, str) and len(published_date) >= 7 and published_date[4] == "-":
        return published_date[:7]
    return fallback_month


def accumulate(
    df: "pd.DataFrame",
    journal_key: str,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    today: datetime.date | None = None,
) -> dict[str, int]:
    """Merge ``df`` into ``data/<journal_key>/<YYYY-MM>.csv`` buckets.

    Returns ``{bucket: n_added}`` counting only genuinely new rows per month.
    """
    import pandas as pd

    fallback_month = (today or datetime.date.today()).strftime("%Y-%m")
    out_base = Path(data_dir) / journal_key
    added: dict[str, int] = {}

    if df.empty:
        return added

    df = df.copy()
    df["_bucket"] = [_bucket_of(d, fallback_month) for d in df["published_date"]]

    for bucket, group in df.groupby("_bucket"):
        group = group.drop(columns="_bucket")
        out_base.mkdir(parents=True, exist_ok=True)
        dest = out_base / f"{bucket}.csv"

        if dest.exists():
            existing = pd.read_csv(dest)
            seen = {_dedup_key(r) for _, r in existing.iterrows()}
        else:
            existing = pd.DataFrame(columns=RECORD_COLUMNS)
            seen = set()

        fresh_rows = []
        for _, row in group.iterrows():
            key = _dedup_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            fresh_rows.append(row)

        if not fresh_rows:
            added[bucket] = 0
            continue

        merged = pd.concat([existing, pd.DataFrame(fresh_rows)], ignore_index=True)
        merged = merged.reindex(columns=RECORD_COLUMNS)
        merged.to_csv(dest, index=False)
        added[bucket] = len(fresh_rows)

    return added


def ingest_journal(
    journal: "Journal",
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    today: datetime.date | None = None,
) -> dict[str, int]:
    """Fetch one journal's feeds and accumulate the results."""
    df = fetch_journal(journal)
    return accumulate(df, journal.key, data_dir, today=today)


def ingest_all(
    registry: "JournalRegistry",
    data_dir: Path | str = DEFAULT_DATA_DIR,
    *,
    only: set[str] | None = None,
    force: bool = False,
    today: datetime.date | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, dict[str, int]]:
    """Ingest journals that are *due* per their declared frequency.

    A journal is polled only if at least its cadence interval has elapsed since the
    last poll (tracked in ``data/.ingest_state.json``). ``force=True`` polls every
    selected journal regardless. Returns ``{key: {bucket: n}}`` for polled journals.
    """
    today = today or datetime.date.today()
    state = load_state(data_dir)
    summary: dict[str, dict[str, int]] = {}
    polled = skipped = 0

    for journal in registry.journals:
        if only and journal.key not in only:
            continue
        if not force and not is_due(state.get(journal.key), journal.frequency, today):
            skipped += 1
            log(f"ingest: {journal.key} not due ({journal.frequency}, last {state[journal.key]}) — skipped")
            continue
        try:
            added = ingest_journal(journal, data_dir, today=today)
        except Exception as exc:  # best-effort per journal; one bad feed must not abort the run
            log(f"ingest: {journal.key} failed ({type(exc).__name__}: {exc})")
            continue
        polled += 1
        state[journal.key] = today.isoformat()
        total = sum(added.values())
        summary[journal.key] = added
        log(f"ingest: {journal.key} +{total} new across {len(added)} month(s)")

    save_state(state, data_dir)
    log(f"ingest: polled {polled} journal(s), skipped {skipped} not-due")
    return summary
