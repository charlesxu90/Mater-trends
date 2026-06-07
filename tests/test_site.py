"""Static-site record building and author parsing."""

from mat_trend.site import build_paper_record, parse_authors


def test_parse_authors_round_trips_repr_format():
    assert parse_authors("'Alice', 'Bob'") == ["Alice", "Bob"]


def test_parse_authors_empty():
    assert parse_authors("") == []
    assert parse_authors(None) == []


def test_build_paper_record_shape_and_truncation():
    row = {
        "title": "A CRISPR screen",
        "authors": "'Alice', 'Bob'",
        "topic": "genome editing;immunology",
        "abstract": "x" * 400,
        "doi": "10.1/abc",
        "link": "https://x/1",
        "published_date": "2026-05-02",
    }
    rec = build_paper_record(row, "Cell", "Cell Press", "2026-05", abstract_chars=50)
    assert rec["journal"] == "Cell" and rec["family"] == "Cell Press"
    assert rec["topics"] == ["genome editing", "immunology"]
    assert rec["period"] == "2026-05" and rec["published"] == "2026-05-02"
    assert rec["abstract"].endswith("…") and len(rec["abstract"]) <= 52


def test_build_paper_record_attaches_citations_and_rising_by_doi():
    row = {"title": "A", "abstract": "", "topic": "", "authors": "", "doi": "10.1/a"}
    rec = build_paper_record(row, "Cell", "Cell Press", "2026-05",
                             counts_by_doi={"10.1/a": 42}, deltas_by_doi={"10.1/a": 5})
    assert rec["citations"] == 42
    assert rec["rising"] == 5  # positive citation gain across snapshots
