"""Pre-build compact JSON for the static GitHub Pages site.

Adapted from AI-trend's ``site.py``. GitHub Pages is static, so the browser cannot
read the CSVs directly. This module exports:

* ``trends.json`` — per journal-period top/emerging/fading + topic counts.
* ``papers/<key>_<period>.json`` — one shard per journal-month, loaded on demand.
* ``manifest.json`` — journals, families, available shards, periods, and the topics
  that actually occur (drives the site's filters).

Journal/period identity comes from the **file location** via the registry.
"""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING

from mat_trend.citations import CITATIONS_DIR, citation_delta, counts_path, latest_count, load_history
from mat_trend.ingest import DEFAULT_DATA_DIR
from mat_trend.registry import JournalRegistry
from mat_trend.taxonomy import Taxonomy
from mat_trend.trends import (
    BUCKET_MONTH,
    BUCKET_YEAR,
    BUCKETS,
    DEFAULT_MIN_COUNT,
    DEFAULT_MIN_PREV,
    DEFAULT_TOP_N,
    GROUP_JOURNAL,
    TOPICS_GLOB,
    compute_all_trends,
    month_of,
    trend_to_dict,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    pass

DEFAULT_SITE_DATA_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"
DEFAULT_ABSTRACT_CHARS = 300
MAX_SHARD_AUTHORS = 10  # truncate long author lists in browse shards


def parse_authors(raw: object) -> list[str]:
    """Turn the CSV ``authors`` cell (``"'A', 'B'"``) into a clean list."""
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        value = ast.literal_eval("[" + raw + "]")
        return [str(a).strip() for a in value if str(a).strip()]
    except (ValueError, SyntaxError):
        return [raw.strip()]


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def build_paper_record(
    row: dict,
    journal: str,
    family: str,
    period: str,
    abstract_chars: int = DEFAULT_ABSTRACT_CHARS,
    counts_by_doi: dict | None = None,
    deltas_by_doi: dict | None = None,
) -> dict:
    topics = [t for t in str(row.get("topic", "")).split(";") if t and t != "nan"]
    abstract = _text(row.get("abstract"))
    if len(abstract) > abstract_chars:
        abstract = abstract[:abstract_chars].rstrip() + "…"
    doi = _text(row.get("doi"))
    record = {
        "title": _text(row.get("title")),
        "authors": parse_authors(row.get("authors")),
        "topics": topics,
        "journal": journal,
        "family": family,
        "period": period,
        "published": _text(row.get("published_date")),
        "doi": doi,
        "link": _text(row.get("link")),
        "abstract": abstract,
    }
    key = doi.lower()
    if counts_by_doi and key in counts_by_doi and counts_by_doi[key] is not None:
        record["citations"] = counts_by_doi[key]
    if deltas_by_doi and deltas_by_doi.get(key, 0) > 0:
        record["rising"] = deltas_by_doi[key]  # citation gain across tracked snapshots
    return record


def export_site(
    out_dir: Path | str = DEFAULT_SITE_DATA_DIR,
    *,
    taxonomy: Taxonomy | None = None,
    registry: JournalRegistry | None = None,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    group_by: str = GROUP_JOURNAL,
    bucket: str = BUCKET_MONTH,
    top_n: int = DEFAULT_TOP_N,
    min_prev: int = DEFAULT_MIN_PREV,
    min_count: int = DEFAULT_MIN_COUNT,
    abstract_chars: int = DEFAULT_ABSTRACT_CHARS,
    shard_years: int | None = None,
    max_authors: int = MAX_SHARD_AUTHORS,
    topiced_only: bool = True,
    citations_dir: Path | str = CITATIONS_DIR,
) -> dict:
    """Write the site's JSON data files and return the manifest.

    Browsable papers are sharded **per (journal, year)** — ``papers/<key>_<YYYY>.json``
    — so the site lazy-loads only the years a user actually views. ``shard_years``
    caps shards to the most recent N years (``None`` = all). Trends are always
    computed over the full history regardless of this cap; ``max_authors`` truncates
    long author lists to keep shard files lean. ``topiced_only`` (default) omits
    papers with no biology topic from the browse shards — they never match a topic
    filter and would only bloat the payload (trends still see them via the CSVs).
    """
    import pandas as pd

    taxonomy = taxonomy or Taxonomy.load()
    registry = registry or JournalRegistry.load()
    out_dir = Path(out_dir)
    (out_dir / "papers").mkdir(parents=True, exist_ok=True)
    data_dir = Path(data_dir)

    # Trends at every granularity (year / quarter / month) so the site can toggle.
    trends_by_bucket = {
        b: [
            trend_to_dict(t, include_counts=True)
            for t in compute_all_trends(
                taxonomy, data_dir, group_by=group_by, bucket=b,
                top_n=top_n, min_prev=min_prev, min_count=min_count,
                key_to_label=registry.key_to_label, key_to_family=registry.key_to_family,
            )
        ]
        for b in BUCKETS
    }
    (out_dir / "trends.json").write_text(
        json.dumps(trends_by_bucket, ensure_ascii=False), encoding="utf-8"
    )

    from collections import defaultdict

    key_to_label = registry.key_to_label
    key_to_family = registry.key_to_family
    shards: list[dict] = []
    seen_topics: set[str] = set()

    # Collect every (journal, month) topics file.
    found: list[tuple[str, str, str, str, Path]] = []  # (key, label, family, month, path)
    for key_dir in sorted(p for p in data_dir.iterdir() if p.is_dir()) if data_dir.exists() else []:
        key = key_dir.name
        label = key_to_label.get(key)
        if label is None:
            continue
        family = key_to_family.get(key, label)
        for topics_path in sorted(key_dir.glob(TOPICS_GLOB)):
            month = month_of(topics_path)
            if month is not None:
                found.append((key, label, family, month, topics_path))

    # Full-corpus totals (every month) for the hero stats. Count CSV *records*
    # via csv.reader — abstracts contain embedded newlines, so a physical
    # line count would over-report the article total.
    total_articles = 0
    for _, _, _, _, path in found:
        with open(path, encoding="utf-8", newline="") as fh:
            total_articles += max(0, sum(1 for _ in csv.reader(fh)) - 1)  # minus header

    months_present = sorted({m for _, _, _, m, _ in found})
    years_present = sorted({m[:4] for _, _, _, m, _ in found})
    keep_years = set(years_present[-shard_years:]) if shard_years else set(years_present)

    # Group the monthly files into one browsable shard per (journal, year).
    by_jy: dict[tuple[str, str, str, str], list[tuple[str, Path]]] = defaultdict(list)
    for key, label, family, month, path in found:
        by_jy[(key, label, family, month[:4])].append((month, path))

    for (key, label, family, year), items in sorted(by_jy.items()):
        if year not in keep_years:
            continue
        rel = f"papers/{key}_{year}.json"
        # citation counts + rising delta, tracked per DOI (committed citations/ store)
        history = load_history(counts_path(key, year, citations_dir))
        counts_by_doi = {doi: latest_count(s) for doi, s in history.items()}
        deltas_by_doi = {doi: citation_delta(s) for doi, s in history.items()}

        year_records: list[dict] = []
        for month, path in sorted(items):
            df = pd.read_csv(path)
            for row in df.to_dict("records"):
                rec = build_paper_record(row, label, family, month, abstract_chars,
                                         counts_by_doi, deltas_by_doi)
                if topiced_only and not rec["topics"]:
                    continue  # papers with no biology topic never match a topic browse
                if len(rec["authors"]) > max_authors:
                    rec["authors"] = rec["authors"][:max_authors]
                seen_topics.update(rec["topics"])
                year_records.append(rec)
        (out_dir / rel).write_text(json.dumps(year_records, ensure_ascii=False), encoding="utf-8")
        shards.append({
            "journal": key, "label": label, "family": family,
            "year": year, "count": len(year_records), "file": rel,
        })

    browsable_years = sorted(keep_years)
    manifest = {
        # ordered by impact factor (see config/journals.json); the site preserves this order
        "journals": [
            {"key": j.key, "label": j.label, "family": j.family, "impact_factor": j.impact_factor}
            for j in registry.journals
        ],
        "families": sorted({j.family for j in registry.journals}),
        "topics": sorted(seen_topics),
        # months available within browsable years (drives the month dropdown)
        "periods": [m for m in months_present if m[:4] in keep_years],
        "years": browsable_years,
        "buckets": list(BUCKETS),
        # full-corpus coverage (all years analysed for trends, not just browsable shards)
        "total_articles": total_articles,
        "taxonomy_topics": len(taxonomy.topics),
        "trend_years": sorted({t["period"] for t in trends_by_bucket[BUCKET_YEAR]}),
        "shards": shards,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    return manifest
