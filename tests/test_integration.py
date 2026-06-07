"""Integration: mocked feed fetch -> ingest -> refresh -> site, no network."""

import json
import types

import pandas as pd

from mat_trend import rss
from mat_trend.refresh import refresh
from mat_trend.registry import JournalRegistry
from mat_trend.site import export_site
from mat_trend.taxonomy import Taxonomy


def _make_config(config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "taxonomy.json").write_text(
        json.dumps({"genome editing": ["crispr"], "immunology": ["t cell"]}), encoding="utf-8"
    )
    (config_dir / "useless_keywords.json").write_text("[]", encoding="utf-8")
    (config_dir / "journals.json").write_text(
        json.dumps({"journals": [{"key": "cell", "label": "Cell", "family": "Cell Press",
                                   "feeds": [{"url": "https://x/cell.rss"}]}]}),
        encoding="utf-8",
    )


def _fake_feed(entries):
    return types.SimpleNamespace(status=200, entries=entries, feed={})


def test_fetch_journal_dedupes_across_feeds(monkeypatch):
    entries = [
        {"title": "CRISPR screen", "prism_doi": "10.1016/j.cell.2026.05.001", "published": "2026-05-01", "link": "http://x/a"},
        {"title": "CRISPR screen dup", "prism_doi": "10.1016/j.cell.2026.05.001", "published": "2026-05-01", "link": "http://x/a2"},
        {"title": "T cell atlas", "prism_doi": "10.1016/j.cell.2026.05.003", "published": "2026-05-02", "link": "http://x/b"},
    ]
    monkeypatch.setattr(rss, "parse_feed", lambda url, agent=rss.USER_AGENT: _fake_feed(entries))
    reg = JournalRegistry.from_dicts([
        {"key": "cell", "label": "Cell", "family": "Cell Press", "feeds": [{"url": "https://x/cell.rss"}]}
    ])
    df = rss.fetch_journal(reg.journals[0])
    assert len(df) == 2  # the duplicate DOI is dropped
    assert set(df["doi"]) == {"10.1016/j.cell.2026.05.001", "10.1016/j.cell.2026.05.003"}


def test_refresh_then_export_site(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    site_dir = tmp_path / "site"
    _make_config(config_dir)

    entries = [
        {"title": "CRISPR base editing", "prism_doi": "10.1016/j.cell.2026.05.001", "published": "2026-05-02", "link": "http://x/a", "summary": "crispr"},
        {"title": "T cell receptor map", "prism_doi": "10.1016/j.cell.2026.05.003", "published": "2026-05-03", "link": "http://x/b", "summary": "t cell"},
    ]
    monkeypatch.setattr(rss, "parse_feed", lambda url, agent=rss.USER_AGENT: _fake_feed(entries))

    summary = refresh(
        config_dir=config_dir, data_dir=data_dir, site_dir=site_dir, log=lambda *_: None,
    )
    assert summary["ingested"] == 2
    assert summary["assigned"] == 1
    assert summary["site_papers"] == 2

    # site artifacts exist and are well-formed
    manifest = json.loads((site_dir / "manifest.json").read_text())
    assert manifest["families"] == ["Cell Press"]
    assert "genome editing" in manifest["topics"] and "immunology" in manifest["topics"]
    # browsable papers are sharded per (journal, year)
    shard = json.loads((site_dir / "papers" / "cell_2026.json").read_text())
    assert {r["title"] for r in shard} == {"CRISPR base editing", "T cell receptor map"}
    assert {s["year"] for s in manifest["shards"]} == {"2026"}


def test_export_site_year_shards_and_shard_years_cap(tmp_path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    _make_config(config_dir)
    cell = data_dir / "cell"
    cell.mkdir(parents=True)
    # data across two years (and two months in 2026)
    for month in ("2025-11", "2026-01", "2026-02"):
        pd.DataFrame([{"title": f"CRISPR {month}", "abstract": "crispr", "journal": "Cell",
                       "family": "Cell Press", "published_date": f"{month}-05", "doi": f"10.1/{month}",
                       "link": "", "authors": "", "topic": "genome editing"}]).to_csv(
            cell / f"{month}.csv_topics.csv", index=False
        )

    taxonomy = Taxonomy.load(config_dir)
    registry = JournalRegistry.load(config_dir)
    manifest = export_site(tmp_path / "site", taxonomy=taxonomy, registry=registry,
                           data_dir=data_dir, shard_years=1)

    # only the most recent year is emitted as a browsable shard...
    assert {s["year"] for s in manifest["shards"]} == {"2026"}
    shard = json.loads((tmp_path / "site" / "papers" / "cell_2026.json").read_text())
    assert len(shard) == 2  # both 2026 months merged into the year shard
    # ...but yearly trends still cover 2025 and 2026
    trends = json.loads((tmp_path / "site" / "trends.json").read_text())
    assert {"2025", "2026"} <= {t["period"] for t in trends["year"]}


def test_export_site_attaches_tracked_citations(tmp_path):
    config_dir = tmp_path / "config"
    data_dir = tmp_path / "data"
    citations_dir = tmp_path / "citations"
    _make_config(config_dir)
    cell = data_dir / "cell"
    cell.mkdir(parents=True)
    pd.DataFrame([{"title": "CRISPR", "abstract": "crispr", "journal": "Cell",
                   "family": "Cell Press", "published_date": "2026-05-01", "doi": "10.1016/j.cell.2026.05.001",
                   "link": "", "authors": "", "topic": "genome editing"}]).to_csv(
        cell / "2026-05.csv_topics.csv", index=False
    )
    # tracked history (two snapshots -> count 7, rising +5), keyed by DOI per journal-year
    (citations_dir / "cell").mkdir(parents=True)
    (citations_dir / "cell" / "2026.json").write_text(json.dumps(
        {"10.1016/j.cell.2026.05.001": [["2026-05-02", 2], ["2026-06-02", 7]]}
    ))

    taxonomy = Taxonomy.load(config_dir)
    registry = JournalRegistry.load(config_dir)
    export_site(tmp_path / "site", taxonomy=taxonomy, registry=registry,
                data_dir=data_dir, citations_dir=citations_dir)

    shard = json.loads((tmp_path / "site" / "papers" / "cell_2026.json").read_text())
    assert shard[0]["citations"] == 7
    assert shard[0]["rising"] == 5
