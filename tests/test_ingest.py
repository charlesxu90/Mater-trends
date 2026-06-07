"""Accumulation buckets by publication month and de-dupes idempotently."""

import datetime
import types

import pandas as pd

from mat_trend import rss
from mat_trend.ingest import accumulate, ingest_all, is_due, load_state
from mat_trend.registry import JournalRegistry
from mat_trend.rss import RECORD_COLUMNS

TODAY = datetime.date(2026, 6, 15)


def _df(rows):
    return pd.DataFrame(rows, columns=RECORD_COLUMNS)


def test_accumulate_buckets_by_publication_month(tmp_path):
    df = _df([
        {"title": "A", "doi": "10.1/a", "published_date": "2026-05-02", "link": "", "journal": "Cell", "family": "Cell Press", "authors": "", "abstract": ""},
        {"title": "B", "doi": "10.1/b", "published_date": "2026-06-09", "link": "", "journal": "Cell", "family": "Cell Press", "authors": "", "abstract": ""},
    ])
    added = accumulate(df, "cell", tmp_path, today=TODAY)
    assert added == {"2026-05": 1, "2026-06": 1}
    assert (tmp_path / "cell" / "2026-05.csv").exists()
    assert (tmp_path / "cell" / "2026-06.csv").exists()


def test_accumulate_is_idempotent(tmp_path):
    df = _df([{"title": "A", "doi": "10.1/a", "published_date": "2026-05-02", "link": "", "journal": "Cell", "family": "Cell Press", "authors": "", "abstract": ""}])
    first = accumulate(df, "cell", tmp_path, today=TODAY)
    second = accumulate(df, "cell", tmp_path, today=TODAY)
    assert first == {"2026-05": 1}
    assert second == {"2026-05": 0}
    saved = pd.read_csv(tmp_path / "cell" / "2026-05.csv")
    assert len(saved) == 1


def test_accumulate_dedup_key_falls_back_to_link_then_title(tmp_path):
    # same link, no DOI -> dedup by link
    rows = [
        {"title": "A", "doi": "", "link": "http://x/1", "published_date": "2026-05-02", "journal": "Cell", "family": "Cell Press", "authors": "", "abstract": ""},
        {"title": "A2", "doi": "", "link": "http://x/1", "published_date": "2026-05-03", "journal": "Cell", "family": "Cell Press", "authors": "", "abstract": ""},
    ]
    added = accumulate(_df(rows), "cell", tmp_path, today=TODAY)
    assert added == {"2026-05": 1}


def test_accumulate_dateless_uses_fallback_month(tmp_path):
    df = _df([{"title": "A", "doi": "10.1/a", "published_date": "", "link": "", "journal": "Cell", "family": "Cell Press", "authors": "", "abstract": ""}])
    added = accumulate(df, "cell", tmp_path, today=TODAY)
    assert added == {"2026-06": 1}


# ---- frequency-aware polling ------------------------------------------------
def test_is_due_never_polled():
    assert is_due(None, "monthly", TODAY) is True


def test_is_due_continuous_always():
    assert is_due("2026-06-15", "continuous", TODAY) is True


def test_is_due_respects_interval():
    # weekly = 7 days
    assert is_due("2026-06-09", "weekly", TODAY) is False  # 6 days elapsed -> not due
    assert is_due("2026-06-08", "weekly", TODAY) is True   # 7 days elapsed -> due
    assert is_due("2026-06-10", "weekly", TODAY) is False  # 5 days elapsed -> not due


def _registry():
    return JournalRegistry.from_dicts([
        {"key": "cell", "label": "Cell", "family": "Cell Press", "frequency": "biweekly",
         "feeds": [{"url": "https://x/cell.rss"}]},
    ])


def _patch_feed(monkeypatch):
    entries = [{"title": "CRISPR work", "prism_doi": "10.1016/j.cell.2026.06.001",
                "published": "2026-06-09", "link": "http://x/a", "summary": "crispr"}]
    fake = types.SimpleNamespace(status=200, entries=entries, feed={})
    monkeypatch.setattr(rss, "parse_feed", lambda url, agent=rss.USER_AGENT: fake)


def test_ingest_all_skips_when_not_due(tmp_path, monkeypatch):
    _patch_feed(monkeypatch)
    reg = _registry()
    # first poll: due (never polled) -> records the date
    ingest_all(reg, tmp_path, today=TODAY, log=lambda *_: None)
    assert load_state(tmp_path)["cell"] == "2026-06-15"
    # 5 days later, biweekly journal is not due -> skipped (no second poll)
    later = datetime.date(2026, 6, 20)
    summary = ingest_all(reg, tmp_path, today=later, log=lambda *_: None)
    assert summary == {}  # nothing polled
    assert load_state(tmp_path)["cell"] == "2026-06-15"  # unchanged


def test_ingest_all_force_overrides_due(tmp_path, monkeypatch):
    _patch_feed(monkeypatch)
    reg = _registry()
    ingest_all(reg, tmp_path, today=TODAY, log=lambda *_: None)
    later = datetime.date(2026, 6, 20)
    summary = ingest_all(reg, tmp_path, today=later, force=True, log=lambda *_: None)
    assert "cell" in summary  # forced despite not being due
    assert load_state(tmp_path)["cell"] == "2026-06-20"
