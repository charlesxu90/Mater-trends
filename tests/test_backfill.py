"""Crossref backfill mapping (pure functions, no network)."""

from mat_trend.backfill import crossref_date, item_to_record


def test_crossref_date_full():
    assert crossref_date({"published": {"date-parts": [[2025, 6, 9]]}}) == "2025-06-09"


def test_crossref_date_partial_defaults_day_month():
    assert crossref_date({"published": {"date-parts": [[2025]]}}) == "2025-01-01"
    assert crossref_date({"published-print": {"date-parts": [[2025, 7]]}}) == "2025-07-01"


def test_crossref_date_prefers_published_over_created():
    item = {"published": {"date-parts": [[2025, 3, 2]]}, "created": {"date-parts": [[2024, 1, 1]]}}
    assert crossref_date(item) == "2025-03-02"


def test_crossref_date_empty_when_missing():
    assert crossref_date({}) == ""


def test_item_to_record_maps_fields_and_strips_jats():
    item = {
        "title": ["A CRISPR screen in <i>Drosophila</i>"],
        "DOI": "10.1016/j.cell.2025.01.001",
        "author": [{"given": "Alice", "family": "Ng"}, {"given": "Bob", "family": "Li"}],
        "abstract": "<jats:p>We screened genes.</jats:p>",
        "URL": "https://doi.org/10.1016/j.cell.2025.01.001",
        "published": {"date-parts": [[2025, 1, 20]]},
    }
    rec = item_to_record(item, "Cell", "Cell Press")
    assert rec["title"] == "A CRISPR screen in Drosophila"
    assert rec["journal"] == "Cell" and rec["family"] == "Cell Press"
    assert rec["doi"] == "10.1016/j.cell.2025.01.001"
    assert rec["authors"] == "'Alice Ng', 'Bob Li'"
    assert rec["abstract"] == "We screened genes."
    assert rec["published_date"] == "2025-01-20"


def test_item_to_record_skips_titleless():
    assert item_to_record({"DOI": "10.1/x"}, "Cell", "Cell Press") is None
