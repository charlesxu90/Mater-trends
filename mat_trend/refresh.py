"""End-to-end pipeline orchestration for the unattended refresh.

Chains: ingest (poll RSS) -> assign -> trends -> export-site.

Running with no new feed items still re-derives trends and the site, so the
scheduled job is safe to run anytime — it simply produces no diff when nothing
changed (the deterministic core is idempotent).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from mat_trend.ingest import DEFAULT_DATA_DIR, ingest_all
from mat_trend.registry import JournalRegistry
from mat_trend.taxonomy import DEFAULT_CONFIG_DIR, Taxonomy
from mat_trend.trends import (
    BUCKET_MONTH,
    GROUP_JOURNAL,
    compute_all_trends,
    trend_to_dict,
)

DEFAULT_SITE_DIR = Path(__file__).resolve().parent.parent / "docs" / "data"


def _source_csvs(data_dir: Path) -> list[Path]:
    """Source CSVs under data/<key>/, excluding derived *_topics.csv files."""
    out: list[Path] = []
    for path in sorted(Path(data_dir).glob("*/*.csv")):
        if path.name.endswith("_topics.csv"):
            continue
        out.append(path)
    return out


def refresh(
    *,
    config_dir: Path | str = DEFAULT_CONFIG_DIR,
    data_dir: Path | str = DEFAULT_DATA_DIR,
    site_dir: Path | str = DEFAULT_SITE_DIR,
    do_ingest: bool = True,
    only: set[str] | None = None,
    force: bool = False,
    group_by: str = GROUP_JOURNAL,
    bucket: str = BUCKET_MONTH,
    shard_years: int | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run the pipeline and return a summary dict."""
    config_dir = Path(config_dir)
    data_dir = Path(data_dir)
    registry = JournalRegistry.load(config_dir)
    summary: dict[str, Any] = {"ingested": 0, "assigned": 0}

    # 1. ingest (poll due RSS feeds, accumulate)
    if do_ingest:
        ingest_summary = ingest_all(registry, data_dir, only=only, force=force, log=log)
        summary["ingested"] = sum(sum(v.values()) for v in ingest_summary.values())

    # 2. assign topics for every source CSV with the current taxonomy
    from mat_trend.assign import assign_csv

    taxonomy = Taxonomy.load(config_dir)
    sources = _source_csvs(data_dir)
    for csv in sources:
        assign_csv(str(csv), str(csv) + "_topics.csv", taxonomy)
    summary["assigned"] = len(sources)
    log(f"assign: {len(sources)} journal-month CSV(s) labelled")

    # 3. trends
    trends = compute_all_trends(taxonomy, data_dir, group_by=group_by, bucket=bucket)
    trends_path = data_dir / "trends" / "trends.json"
    trends_path.parent.mkdir(parents=True, exist_ok=True)
    trends_path.write_text(
        json.dumps([trend_to_dict(t, include_counts=True) for t in trends], ensure_ascii=False),
        encoding="utf-8",
    )
    summary["trends"] = len(trends)
    log(f"trends: {len(trends)} group-period(s) -> {trends_path}")

    # 4. export static site
    from mat_trend.site import export_site

    manifest = export_site(
        site_dir, taxonomy=taxonomy, registry=registry, data_dir=data_dir,
        group_by=group_by, bucket=bucket, shard_years=shard_years,
    )
    summary["site_papers"] = sum(s["count"] for s in manifest["shards"])
    summary["site_shards"] = len(manifest["shards"])
    log(f"export-site: {summary['site_shards']} shards / {summary['site_papers']} papers")

    return summary
