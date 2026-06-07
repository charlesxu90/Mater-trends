"""Pure-function tests for the RSS parsing layer (no network)."""

import time

from mat_trend import rss


def test_strip_html_removes_tags_and_entities():
    assert rss.strip_html("<p>Hello&nbsp;<b>world</b> &amp; more</p>") == "Hello world & more"


def test_normalize_date_prefers_parsed_struct():
    entry = {"published_parsed": time.struct_time((2026, 6, 9, 0, 0, 0, 0, 0, 0))}
    assert rss.normalize_date(entry) == "2026-06-09"


def test_normalize_date_falls_back_to_string():
    assert rss.normalize_date({"published": "2025-12-01T10:00:00Z"}) == "2025-12-01"


def test_normalize_date_empty_when_absent():
    assert rss.normalize_date({}) == ""


def test_extract_doi_from_prism_field():
    assert rss.extract_doi({"prism_doi": "10.1038/s41586-026-10728-9"}) == "10.1038/s41586-026-10728-9"


def test_extract_doi_from_link():
    entry = {"link": "https://www.nature.com/articles/s41586-026-10728-9", "dc_identifier": "doi:10.1038/abc.123"}
    assert rss.extract_doi(entry) == "10.1038/abc.123"


def test_format_authors_from_list():
    entry = {"authors": [{"name": "Alice"}, {"name": "Bob"}]}
    assert rss.format_authors(entry) == "'Alice', 'Bob'"


def test_entry_to_record_skips_titleless():
    assert rss.entry_to_record({"summary": "no title"}, "Cell", "Cell Press") is None


def test_entry_to_record_maps_fields():
    entry = {
        "title": "A CRISPR screen",
        "summary": "<p>We did a screen.</p>",
        "link": "https://www.cell.com/x",
        "prism_doi": "10.1016/j.cell.2026.01.001",
        "author": "Alice; Bob",
        "published": "2026-05-02",
    }
    rec = rss.entry_to_record(entry, "Cell", "Cell Press")
    assert rec["title"] == "A CRISPR screen"
    assert rec["journal"] == "Cell" and rec["family"] == "Cell Press"
    assert rec["abstract"] == "We did a screen."
    assert rec["doi"] == "10.1016/j.cell.2026.01.001"
    assert rec["published_date"] == "2026-05-02"
    assert rec["authors"] == "'Alice', 'Bob'"
