"""Fetch and normalise article metadata from journal RSS/Atom feeds.

This is Mater-trend's ingestion layer — the analogue of AI-trend's ``openreview.py``
/ ``cvf.py``, but for RSS. It uses ``feedparser`` to fetch each feed and maps every
entry to the flat record schema the rest of the pipeline consumes.

Two practical realities shape this module:

* **Bot protection.** ``science.org`` and ``cell.com`` sit behind Cloudflare and
  return HTTP 403 to a naive client. We send a realistic browser ``User-Agent``
  (feedparser's ``agent=``) which is enough for the table-of-contents feeds.
  ``nature.com`` serves without challenge.
* **Rolling window.** A feed only carries its latest items (current issue / recent
  articles). Accumulation + dedup across polls is handled in ``ingest.py``; this
  module just returns the entries it can see right now.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

    from mat_trend.registry import Journal

# A current desktop-browser UA. Plain library UAs are 403'd by Cloudflare on
# science.org / cell.com; this is enough to retrieve their public RSS feeds.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 (+mat-trend RSS reader)"
)

# Source record schema (pre-assignment). `assign` appends a `topic` column.
RECORD_COLUMNS = ["title", "journal", "family", "published_date", "authors", "abstract", "doi", "link"]

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value: object) -> str:
    """Remove HTML tags and collapse whitespace from a feed text field."""
    if not isinstance(value, str):
        return ""
    text = _TAG_RE.sub(" ", value)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return _WS_RE.sub(" ", text).strip()


def normalize_date(entry: dict) -> str:
    """Return the entry's publication date as an ISO ``YYYY-MM-DD`` string.

    Prefers feedparser's pre-parsed struct_time (``published_parsed`` /
    ``updated_parsed``); falls back to parsing the raw string with dateutil.
    Returns ``""`` if no date can be recovered.
    """
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return f"{parsed.tm_year:04d}-{parsed.tm_mon:02d}-{parsed.tm_mday:02d}"
    for key in ("published", "updated", "date", "prism_publicationdate", "dc_date"):
        raw = entry.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                from dateutil import parser as _dtp

                return _dtp.parse(raw).date().isoformat()
            except (ValueError, OverflowError, ImportError):
                continue
    return ""


def extract_doi(entry: dict) -> str:
    """Best-effort DOI extraction from common feed fields, then from the link."""
    for key in ("prism_doi", "dc_identifier", "dccoi", "id", "guid"):
        raw = entry.get(key)
        if isinstance(raw, str):
            if raw.lower().startswith("doi:"):
                return raw[4:].strip()
            m = _DOI_RE.search(raw)
            if m:
                return m.group(0).rstrip(".")
    link = entry.get("link")
    if isinstance(link, str):
        m = _DOI_RE.search(link)
        if m:
            return m.group(0).rstrip(".")
    return ""


def format_authors(entry: dict) -> str:
    """Serialise authors as ``"'A', 'B'"`` (matches AI-trend's CSV round-trip)."""
    names: list[str] = []
    authors = entry.get("authors")
    if isinstance(authors, list):
        names = [a.get("name", "").strip() for a in authors if isinstance(a, dict) and a.get("name")]
    if not names:
        single = entry.get("author") or entry.get("dc_creator")
        if isinstance(single, str) and single.strip():
            # dc:creator is often a single comma/semicolon-joined string
            names = [n.strip() for n in re.split(r"[;,]", single) if n.strip()]
    return ", ".join(f"'{n}'" for n in names)


def entry_to_record(entry: dict, journal_label: str, family: str) -> dict | None:
    """Map one feed entry to a record, or ``None`` if it has no usable title."""
    title = strip_html(entry.get("title"))
    if not title:
        return None
    abstract = strip_html(entry.get("summary") or entry.get("description"))
    return {
        "title": title,
        "journal": journal_label,
        "family": family,
        "published_date": normalize_date(entry),
        "authors": format_authors(entry),
        "abstract": abstract,
        "doi": extract_doi(entry),
        "link": (entry.get("link") or "").strip() if isinstance(entry.get("link"), str) else "",
    }


def parse_feed(url: str, *, agent: str = USER_AGENT):
    """Fetch and parse a feed URL. Thin wrapper over ``feedparser.parse``."""
    import feedparser

    return feedparser.parse(url, agent=agent)


def feed_status(url: str, *, agent: str = USER_AGENT) -> tuple[bool, int, int]:
    """Probe a feed: returns ``(ok, http_status, n_entries)``.

    ``ok`` is True when the request returned a usable feed with at least one
    entry. Used by ``mat-trend check-feeds``.
    """
    parsed = parse_feed(url, agent=agent)
    status = int(getattr(parsed, "status", 0) or 0)
    entries = getattr(parsed, "entries", []) or []
    ok = bool(entries) and status < 400
    return ok, status, len(entries)


def fetch_journal(journal: "Journal", *, agent: str = USER_AGENT) -> "pd.DataFrame":
    """Fetch every feed of ``journal`` into one de-duplicated DataFrame.

    De-dup key is DOI, then link, then title (first occurrence wins) — so a
    journal that exposes overlapping subject + journal feeds yields each article
    once.
    """
    import pandas as pd

    records: list[dict] = []
    seen: set[str] = set()
    for feed in journal.feeds:
        parsed = parse_feed(feed.url, agent=agent)
        for entry in getattr(parsed, "entries", []) or []:
            rec = entry_to_record(entry, journal.label, journal.family)
            if rec is None:
                continue
            key = rec["doi"] or rec["link"] or rec["title"]
            if key in seen:
                continue
            seen.add(key)
            records.append(rec)
    return pd.DataFrame(records, columns=RECORD_COLUMNS)
